"""Population requote pass — COHORT BUILDER (2026-06-21). READ-ONLY.

Selects the PRECISION cohort of visible-scored YouTube ticker_call rows whose
DISPLAYED source_verbatim_quote does NOT carry the call:

  (a) ORPHAN   — the quote names NEITHER the ticker/alias NOR any pronoun anchor
                 (no 'it / they / this / the stock / the company / ...'), so the
                 sentence cannot be read as a call on {ticker} at all.
  (b) OPPOSITE — the quote shows a direction cue OPPOSITE to the labeled direction
                 (a bear cue on a bullish label, or vice-versa) with NO same-side cue.

The 06-12 gate lesson ([[project_requote_representativeness_2026_06_12]]): "quote
omits the ticker name" ALONE flags ~45% — benign pronoun-heavy natural speech, a
near-useless badness signal. Pairing orphan with NO-pronoun-anchor and adding the
opposite-direction cue is the *precision* cohort (~10% in the 06-12 run).

Scope (the task): prediction_category='ticker_call' AND source_type='youtube'
  AND (verified_by='youtube_haiku_v1' OR generating_model='cc_sonnet_recovery_2026_05_17').
Visible-scored = scored outcome set, YT timestamp-resolved, FULL hide bundle clear
(reported_speech / ambiguous_symbol / weak_basket / holding_disclosure / no_claim /
hedged-conviction) — matches services.prediction_visibility + routers._prediction_filters.

Reuses jobs/representativeness_guard pure helpers (ticker_terms / _names / _cue /
_BULL / _BEAR) — the eval-tested orphan/opposite lexicons — plus a pronoun-anchor set.
NO writes. Emits requote_pop_cohort_2026_06_21.json (one record per cohort row).

Run:  DATABASE_PUBLIC_URL=... python3 backend/scripts/requote_pop_cohort_2026_06_21.py
"""
import json
import os
import re
import sys

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import jobs.representativeness_guard as rg  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "requote_pop_cohort_2026_06_21.json")

# Visible-scored bundle (all kill switches default ON in prod). Mirrors
# hedged_filter_sql + YT_VISIBLE_FILTER_SQL + the scored outcome enum set.
VISIBLE_SCORED_SQL = """
  outcome IN ('hit','correct','near','miss','incorrect')
  AND source_timestamp_seconds IS NOT NULL
  AND (conviction_level NOT IN ('hedged','hypothetical') OR conviction_level IS NULL)
  AND COALESCE(is_reported_speech, FALSE) = FALSE
  AND COALESCE(is_ambiguous_symbol, FALSE) = FALSE
  AND COALESCE(is_weak_basket_call, FALSE) = FALSE
  AND COALESCE(is_holding_disclosure, FALSE) = FALSE
  AND COALESCE(is_no_claim, FALSE) = FALSE
"""

SCOPE_SQL = """
  source_type = 'youtube'
  AND prediction_category = 'ticker_call'
  AND (verified_by = 'youtube_haiku_v1'
       OR generating_model = 'cc_sonnet_recovery_2026_05_17')
"""

# A pronoun/anaphor anchor — the quote can plausibly be ABOUT the ticker even
# without naming it. Presence of any of these means NOT an orphan.
_PRON_RX = re.compile(
    r"(?<![a-z])(it|its|it's|they|them|their|theirs|this|that|these|those|"
    r"he|she|him|her|his|hers)(?![a-z])", re.I)
_ANCHOR_PHRASE_RX = re.compile(
    r"\b(?:the|this|that|these|those|my|our)\s+"
    r"(?:stock|stocks|company|companies|name|ticker|share|shares|business|"
    r"firm|play|one|position|holding)\b", re.I)


def has_anchor(quote: str) -> bool:
    q = quote or ""
    return bool(_PRON_RX.search(q) or _ANCHOR_PHRASE_RX.search(q))


def build_alias_map(cur):
    """Same construction as rg.alias_map but via psycopg2 (no SessionLocal)."""
    am = {}
    try:
        cur.execute("SELECT etf_ticker, alias FROM sector_etf_aliases")
        for t, a in cur.fetchall():
            if t and a:
                am.setdefault(t.strip().upper(), set()).add(a.strip().lower())
    except Exception:
        pass
    try:
        cur.execute("SELECT ticker, alias FROM company_name_aliases")
        for t, a in cur.fetchall():
            if t and a:
                am.setdefault(t.strip().upper(), set()).add(a.strip().lower())
    except Exception:
        pass
    try:
        cur.execute("SELECT primary_etf, secondary_etfs, aliases FROM macro_concept_aliases")
        for primary, sec, csv in cur.fetchall():
            if not csv:
                continue
            al = {a.strip().lower() for a in csv.split(",") if a.strip()}
            etfs = set()
            if primary:
                etfs.add(primary.strip().upper())
            if sec:
                etfs.update(s.strip().upper() for s in sec.split(",") if s.strip())
            for e in etfs:
                am.setdefault(e, set()).update(al)
    except Exception:
        pass
    return am


def build_company_names(cur):
    m = {}
    cur.execute("SELECT ticker, company_name FROM ticker_sectors WHERE company_name IS NOT NULL")
    for t, nm in cur.fetchall():
        if t and nm and nm.strip():
            m[t.strip().upper()] = nm.strip()
    return m


def opposite_cue(quote, direction):
    bull = rg._cue(quote, rg._BULL)
    bear = rg._cue(quote, rg._BEAR)
    if direction == "bullish" and bear and not bull:
        return True
    if direction == "bearish" and bull and not bear:
        return True
    return False


def main():
    conn = psycopg2.connect(os.environ["DATABASE_PUBLIC_URL"])
    cur = conn.cursor()
    amap = build_alias_map(cur)
    cnames = build_company_names(cur)
    print(f"alias map: {len(amap)} tickers; company names: {len(cnames)}")

    cur.execute(f"""
        SELECT p.id, p.ticker, p.direction, p.source_verbatim_quote, p.context,
               p.source_timestamp_seconds, p.source_timestamp_method,
               p.transcript_video_id, p.video_id, p.outcome, p.verified_by,
               p.generating_model, ts.company_name
        FROM predictions p
        LEFT JOIN ticker_sectors ts ON ts.ticker = p.ticker
        WHERE {SCOPE_SQL} AND {VISIBLE_SCORED_SQL}
    """)
    rows = cur.fetchall()
    print(f"visible-scored population in scope: {len(rows)}")

    cohort = []
    n_orphan = n_opp = n_both = 0
    for (pid, ticker, direction, vq, ctx, ts, tsm, tvid, vid,
         outcome, vby, gm, cn) in rows:
        quote = vq or ""
        terms = rg.ticker_terms(ticker, amap, cnames)
        names_ticker = rg._names(quote, terms)
        orphan = (not names_ticker) and (not has_anchor(quote))
        opp = opposite_cue(quote, direction)
        if not (orphan or opp):
            continue
        if orphan and opp:
            flag = "ab_both"; n_both += 1
        elif opp:
            flag = "b_opposite"; n_opp += 1
        else:
            flag = "a_orphan"; n_orphan += 1
        cohort.append({
            "id": pid, "ticker": ticker, "direction": direction,
            "vq": quote, "ctx": ctx or "", "ts": ts, "tsm": tsm,
            "vid": tvid, "video_id": vid, "outcome": outcome,
            "verified_by": vby, "generating_model": gm,
            "company_name": cn, "flag": flag,
        })

    cohort.sort(key=lambda r: r["id"])
    payload = {
        "generated": "2026-06-21",
        "ship": "population requote pass (evidence-only) — precision cohort",
        "scope": "visible-scored youtube_haiku_v1 + cc_sonnet ticker_call",
        "population": len(rows),
        "cohort_size": len(cohort),
        "by_flag": {"a_orphan": n_orphan, "b_opposite": n_opp, "ab_both": n_both},
        "rows": cohort,
    }
    json.dump(payload, open(OUT, "w"), indent=0)
    print(f"COHORT: {len(cohort)} / {len(rows)} "
          f"({100*len(cohort)/max(1,len(rows)):.1f}%)  "
          f"orphan={n_orphan} opposite={n_opp} both={n_both}")
    # how many cohort videos already have a cached timed transcript?
    have = sum(1 for r in cohort if r["vid"] and
               os.path.exists(f"/tmp/heal/timed/{r['vid']}.json"))
    vids = {r["vid"] for r in cohort if r["vid"]}
    print(f"distinct videos: {len(vids)}; rows with cached transcript: {have}")
    conn.close()


if __name__ == "__main__":
    main()
