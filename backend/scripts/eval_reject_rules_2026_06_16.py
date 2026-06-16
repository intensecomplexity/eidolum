"""Strict auto-eval for the 4 held REJECT rules (2026-06-16).

REJECT rules drop whole predictions (irreversible) and can collapse acceptance.
Per rule, over the REAL build_cc_prompt (live config + the one candidate reject):
  CATCH       = of should-catch windows where baseline extracts the bad pred,
                fraction WITH drops it.
  FALSE-REJECT= of real-call (Opus/Sonnet=OK) windows where baseline extracts the
                ticker, fraction WITH wrongly drops it.
  ACCEPTANCE  = total predictions extracted across the real-call sample, WITH vs
                baseline (delta must be ~flat — the collapse guard).
PASS = catch material AND false-reject ~0 AND acceptance flat (AND marginal value,
measured separately: guards miss 52-67% of these). Else HOLD (guard is reversible).
"""
import json, os, importlib.util, threading
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault('DATABASE_URL', 'sqlite:////tmp/x.db')
spec = importlib.util.spec_from_file_location('cc', os.path.join(os.path.dirname(__file__), 'cc_recover_classifier_errors.py'))
cc = importlib.util.module_from_spec(spec); spec.loader.exec_module(cc)

BASE = dict(conditional=True, long_horizon_rule=True, target_hygiene=True)  # current live config
RULES = {
    'unnamed_macro':   dict(reject_unnamed=True),
    'reported_speech': dict(reject_reported=True),
    'chart_commentary': dict(reject_chart=True),
    'holding':         dict(reject_holding=True),
}
gold = json.load(open(os.path.join(os.path.dirname(__file__), 'classifier_lessons_2026_06_16/gold_fixtures.json')))
keep = json.load(open('/tmp/reject_keep_sample.json'))  # real calls (Opus/Sonnet=OK), must-keep
NC = int(os.environ.get('NC', '16'))  # catch fixtures per rule
catch = {p: gold[p]['catch'][:NC] for p in RULES}


def preds(win, vid, kw):
    e, err = cc.run_cc_classifier(cc.build_cc_prompt({vid: win}, **BASE, **kw))
    if err or not e:
        return None
    out = []
    for ent in e:
        out += ent.get('predictions', []) or []
    return out


def has_ticker(ps, tk):
    return ps is not None and any((p.get('ticker') or '').upper() == tk.upper() for p in ps)


def eval_rule(rule, kw):
    # CATCH
    cwins = catch[rule]
    def c1(it):
        b = preds(it['win'], f"v{it['id']}", {})
        w = preds(it['win'], f"v{it['id']}", kw)
        baseline_bad = has_ticker(b, it['ticker'])
        return (baseline_bad, baseline_bad and not has_ticker(w, it['ticker']))
    with ThreadPoolExecutor(8) as ex:
        cres = list(ex.map(c1, cwins))
    cbad = [r for r in cres if r[0]]; caught = [r for r in cbad if r[1]]
    # FALSE-REJECT + ACCEPTANCE (real-call keep sample)
    def k1(it):
        b = preds(it['win'], f"v{it['id']}", {})
        w = preds(it['win'], f"v{it['id']}", kw)
        base_has = has_ticker(b, it['ticker'])
        fr = base_has and not has_ticker(w, it['ticker'])
        return {'nb': len(b) if b else 0, 'nw': len(w) if w else 0, 'base_has': base_has, 'fr': fr}
    with ThreadPoolExecutor(8) as ex:
        kres = list(ex.map(k1, keep))
    base_has = [r for r in kres if r['base_has']]; fr = [r for r in base_has if r['fr']]
    tot_b = sum(r['nb'] for r in kres); tot_w = sum(r['nw'] for r in kres)
    return {
        'catch': f"{len(caught)}/{len(cbad)}" + (f" ({100*len(caught)//len(cbad)}%)" if cbad else ""),
        'false_reject': f"{len(fr)}/{len(base_has)}" + (f" ({100*len(fr)//len(base_has)}%)" if base_has else ""),
        'acceptance': f"preds base={tot_b} with={tot_w} delta={tot_b-tot_w} ({100*(tot_b-tot_w)//max(1,tot_b)}%)",
    }


print(f"keep_sample={len(keep)} catch/rule={NC}", flush=True)
for rule, kw in RULES.items():
    r = eval_rule(rule, kw)
    print(f"\n### {rule}\n  CATCH {r['catch']} | FALSE-REJECT {r['false_reject']} | ACCEPTANCE {r['acceptance']}", flush=True)
print("\nREJECT-EVAL DONE", flush=True)
