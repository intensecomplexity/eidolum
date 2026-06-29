"""Unified deterministic REJECT-RULES judge (eval-gated against gt_gold). 2026-06-29.

Codifies Nimrod's locked reject ruleset into ONE judge and evaluates it on ALL human gold.
EVAL-GATE ONLY — does NOT apply to the population or touch the live classifier.

Design (verify-don't-invent): applies the ruleset to the QUOTE, reusing the lexicons/detectors
in jobs/representativeness_guard.py. Does NOT inherit per-row flags (they carry classifier
false-flags the gold overrides). Exempts claim_type='operational' (tag, don't reject). The
reject REASON maps to the existing hide-flag for a future apply step:
  no_anchor / bare_stance -> is_no_gradeable_claim   hedged -> conviction_level hedged
  reported_speech -> is_reported_speech              holding/buying -> is_holding_disclosure
  buy_wishlist -> is_no_gradeable_claim              (basket/ambiguous already have flags)

Run: DATABASE_URL=$DATABASE_PUBLIC_URL python3 backend/scripts/reject_rules_judge_2026_06_29.py
"""
import os, re, sys, json, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import text as sql
from database import BgSessionLocal
from jobs.representativeness_guard import is_holding_suspect, _FIRST_PERSON

# ANCHOR = real number/level/% (not a bare single digit) OR an explicit timeframe.
NUM = re.compile(r"\$\s?\d|\d+\s?%|\d{2,}|\b\d+\s?(?:dollars|cents|bucks|k)\b|"
                 r"\b(?:double|triple|doubles|triples|tenbagger|multibagger)\b|\b\d+x\b", re.I)  # \d{2,} (not \b-bounded): catch "254ish"
TF = re.compile(r"\b(by\s+(the\s+)?(end\s+of\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|q[1-4]|20\d\d|year|quarter|month)|"
                r"next\s+(year|quarter|month|week|few\s+(months|weeks|years))|in\s+\d+\s+(year|month|week|day)|"
                r"over the (next|coming)|this (year|quarter)|coming (months|weeks|years|quarters)|"
                r"long[- ]?term|short[- ]?term|\d+[- ]?year|years? (from|out|away)|foreseeable future|for years|by 20\d\d)", re.I)
HEDGE = re.compile(r"\b(could go either way|who knows|coin flip|50[/-]50|on the fence|hard to say|"
                   r"toss[- ]?up|no idea|don'?t know which|no clue|either direction|"
                   r"not sure (if|whether|where)|anybody'?s guess)\b", re.I)
REPORTED = re.compile(r"\b(analysts?\b|wall street|consensus (price |target)|price target on it|sell[- ]?side|"
                      r"the street (sees|expects|has)|upgraded by|downgraded by|rating from|morgan stanley|goldman|"
                      r"jpmorgan|citi(group)?|barclays|canaccord|jefferies|raymond james|singular research|"
                      r"unusual whales|whale (bought|sold|is)|"
                      r"(he|she|they)\s+(said|says|expects?|sees|thinks|is calling|predicted|recommended))\b")
# NOTE: dropped the loose "[A-Z][a-z]+ + speech-verb" pattern — it false-fires on capitalized TA
# narration ("Chart says", "Bears think") in real first-person calls. Explicit firm/analyst/pronoun
# markers only. Reported/firm relays are usually still caught; precision over recall here.
WISHLIST = re.compile(r"(on my watch ?list|i'?d (love |like )?(to )?(buy|own|add|get)|would (love |like )?to (buy|own)|"
                      r"wish i|waiting (for|to (buy|get|add))|if it (drops|dips|pulls back|falls|gets) to|"
                      r"on a (pullback|dip)|i'?d be a buyer|love to own)", re.I)
PAST = re.compile(r"\b(was up|was down|i bought (it )?at|i sold|already (up|down|rallied|ran)|"
                  r"last (year|quarter) (it|they|the)|reported (revenue|earnings|eps|q[1-4]))\b", re.I)


def has_anchor(q): return bool(NUM.search(q) or TF.search(q))


def reported_narrow(q):
    if _FIRST_PERSON.search(q or ""):   # own view present -> not a pure third-party relay
        return False
    return bool(REPORTED.search(q or ""))


def reject_judge(row):
    """-> (reject: bool, reason: str). Quote-only; operational exempt.

    A row WITH a firm anchor (number/level OR explicit timeframe) is only rejectable as a relay
    (reported_speech) or a no-conviction musing (hedged) — never by wishlist/holding/past, which
    would false-reject anchored conditional setups ("waiting for a retest at $75k to short").
    Everything else (bare stance / wishlist / holding / brag with NO anchor) -> rejected."""
    if (row.get("claim_type") or "price") == "operational":
        return (False, "operational_keep")
    q = row.get("quote") or ""
    if (row.get("conv") in ("hedged", "hypothetical")) or HEDGE.search(q): return (True, "hedged")
    if reported_narrow(q):                                                 return (True, "reported_speech")
    if has_anchor(q):                                                      return (False, "keep")
    # --- no firm anchor below this line ---
    if WISHLIST.search(q):           return (True, "buy_wishlist")
    if is_holding_suspect(q, ""):    return (True, "holding")
    if PAST.search(q):               return (True, "past_tense")
    return (True, "no_anchor")


def load_gold(db):
    rows = db.execute(sql("""
      SELECT g.prediction_id pid, g.gold_verdict gv, g.gold_valid valid, g.haiku_verdict hv,
        COALESCE(p.claim_type,'price') claim_type, p.conviction_level conv,
        COALESCE(NULLIF(p.source_verbatim_quote,''),p.exact_quote,p.context,'') quote,
        p.source_type st, p.source_timestamp_seconds ts,
        COALESCE(p.is_reported_speech,FALSE) rs, COALESCE(p.is_ambiguous_symbol,FALSE) amb,
        COALESCE(p.is_weak_basket_call,FALSE) basket, COALESCE(p.is_holding_disclosure,FALSE) hold,
        COALESCE(p.is_no_claim,FALSE) noclaim, COALESCE(p.is_no_gradeable_claim,FALSE) nograd
      FROM gt_gold g JOIN predictions p ON p.id=g.prediction_id ORDER BY g.prediction_id""")).mappings().all()
    return [dict(r) for r in rows]


def visible(r):
    if r["st"] == "youtube" and r["ts"] is None: return False
    if (r["conv"] or "") in ("hedged", "hypothetical"): return False
    return not (r["rs"] or r["amb"] or r["basket"] or r["hold"] or r["noclaim"] or r["nograd"])


def main():
    db = BgSessionLocal()
    GOLD = load_gold(db)
    valid = [r for r in GOLD if r["valid"]]; invalid = [r for r in GOLD if not r["valid"]]
    tp = fp = tn = fn = 0; catch_by = collections.Counter(); fr = []
    for r in GOLD:
        rej, reason = reject_judge(r)
        if not r["valid"]:
            (catch_by.update([reason]) or True) if rej else None
            tp += rej; fn += (not rej)
        else:
            fp += rej; tn += (not rej)
            if rej: fr.append((r, reason))
    print(f"eval-set: {len(GOLD)} gold ({len(valid)} valid / {len(invalid)} invalid)")
    print(f"CATCH:        {tp}/{len(invalid)} = {100*tp/len(invalid):.1f}%")
    print(f"FALSE-REJECT: {fp}/{len(valid)} = {100*fp/len(valid):.1f}%  (must be ~0)")
    print(f"confusion: catch(tp)={tp} miss(fn)={fn} false-reject(fp)={fp} correct-keep(tn)={tn}")
    print(f"catch by rule: {dict(catch_by)}")
    print("FALSE-REJECTS:", "NONE" if not fr else "")
    for r, reason in fr:
        print(f"  [{r['pid']}] {reason}: {' '.join((r['quote'] or '').split())[:160]}")

    # post-stratified projected user-facing precision (GOLD_FINDINGS visible-pop weights)
    PUB = {'OK':76.5,'target_error':7.8,'conditional':6.0,'direction_mismatch':4.5,'hedged':2.3,
           'wrong_ticker':1.4,'reported_speech':0.8,'holding':0.3,'chart_commentary':0.2,'other':0.1}
    cells = collections.defaultdict(lambda: [0, 0, 0, 0])  # sample, valid, kept_total, kept_valid
    for r in [x for x in GOLD if visible(x)]:
        c = r["hv"]; kept = not reject_judge(r)[0]
        cells[c][0] += 1; cells[c][1] += int(r["valid"])
        if kept: cells[c][2] += 1; cells[c][3] += int(r["valid"])

    def proj(use_kept):
        num = den = 0.0
        for c, w in PUB.items():
            s, v, kt, kv = cells.get(c, [0, 0, 0, 0])
            if s == 0: continue
            num += w * ((kv if use_kept else v) / s)
            den += w * ((kt if use_kept else s) / s)
        return 100 * num / den if den else 0
    print(f"\nPROJECTED user-facing precision (post-stratified): {proj(False):.1f}% -> {proj(True):.1f}%")
    kept = [r for r in GOLD if not reject_judge(r)[0]]
    print(f"gold-sample kept-precision: {sum(r['valid'] for r in kept)}/{len(kept)} = "
          f"{100*sum(r['valid'] for r in kept)/len(kept):.1f}% (raw valid-rate was {100*len(valid)/len(GOLD):.1f}%)")


if __name__ == "__main__":
    main()
