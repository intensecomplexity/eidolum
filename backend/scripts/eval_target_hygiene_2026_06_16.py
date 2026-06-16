"""Auto-eval for the target_hygiene additive rule (2026-06-16).

Runs the REAL classifier prompt (build_cc_prompt + run_cc_classifier, Sonnet)
WITH vs WITHOUT target_hygiene over the gold fixtures and measures:
  catch       = of should-catch windows where WITHOUT extracts a (bogus) target,
                fraction where WITH nulls it (sets price_target=null / drops it).
  false_reject= of must-not-regress windows with a REAL target where WITHOUT
                keeps it, fraction where WITH wrongly nulls it.
  acceptance  = WITH still emits a prediction wherever WITHOUT did (delta ~0;
                target_hygiene is field-scoped so this must hold).
PASS bar: catch materially > 0, false_reject ~0, acceptance delta ~0.
"""
import json, os, sys, importlib.util, threading
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault('DATABASE_URL', 'sqlite:////tmp/x.db')
spec = importlib.util.spec_from_file_location('cc', os.path.join(os.path.dirname(__file__), 'cc_recover_classifier_errors.py'))
cc = importlib.util.module_from_spec(spec); spec.loader.exec_module(cc)

gold = json.load(open(os.path.join(os.path.dirname(__file__), 'classifier_lessons_2026_06_16/gold_fixtures.json')))
N = int(os.environ.get('EVAL_N', '30'))
catch_fx = gold['target_hygiene']['catch'][:N]
keep_fx = [x for x in gold['target_hygiene']['keep'] if x.get('target') is not None][:N]
LOCK = threading.Lock()


def extract(win, vid, hygiene):
    p = cc.build_cc_prompt({vid: win}, target_hygiene=hygiene)
    entries, err = cc.run_cc_classifier(p)
    if err or not entries:
        return None
    preds = []
    for e in entries:
        preds += e.get('predictions', []) or []
    return preds


def tgt_for(preds, ticker):
    if preds is None:
        return ('err', None)
    for pr in preds:
        if (pr.get('ticker') or '').upper() == ticker.upper():
            return ('found', pr.get('price_target'))
    return ('absent', None)


def run_catch(item):
    vid = f"v{item['id']}"
    wo = tgt_for(extract(item['win'], vid, False), item['ticker'])
    wi = tgt_for(extract(item['win'], vid, True), item['ticker'])
    # baseline reproduced the error if WITHOUT extracted a non-null target
    baseline_bad = wo[0] == 'found' and wo[1] is not None
    caught = baseline_bad and (wi[0] == 'absent' or wi[1] is None)
    return {'id': item['id'], 'ticker': item['ticker'], 'baseline_bad': baseline_bad,
            'caught': caught, 'wo': wo, 'wi': wi}


def run_keep(item):
    vid = f"v{item['id']}"
    wo = tgt_for(extract(item['win'], vid, False), item['ticker'])
    wi = tgt_for(extract(item['win'], vid, True), item['ticker'])
    baseline_target = wo[0] == 'found' and wo[1] is not None
    false_reject = baseline_target and (wi[0] == 'absent' or wi[1] is None)
    # acceptance: did WITH still emit the prediction wherever WITHOUT did?
    accept_drop = (wo[0] == 'found') and (wi[0] == 'absent')
    return {'id': item['id'], 'ticker': item['ticker'], 'baseline_target': baseline_target,
            'false_reject': false_reject, 'accept_drop': accept_drop, 'wo': wo, 'wi': wi}


print(f'catch fixtures: {len(catch_fx)} | keep fixtures: {len(keep_fx)}', flush=True)
with ThreadPoolExecutor(8) as ex:
    catch_res = list(ex.map(run_catch, catch_fx))
    keep_res = list(ex.map(run_keep, keep_fx))

bad = [r for r in catch_res if r['baseline_bad']]
caught = [r for r in bad if r['caught']]
kt = [r for r in keep_res if r['baseline_target']]
fr = [r for r in kt if r['false_reject']]
acc = [r for r in keep_res if r['accept_drop']]
print()
print(f'CATCH: baseline reproduced bogus target in {len(bad)}/{len(catch_res)}; WITH nulled {len(caught)}/{len(bad)} ({100*len(caught)//max(1,len(bad))}%)')
print(f'FALSE-REJECT: real targets in baseline {len(kt)}/{len(keep_res)}; WITH wrongly nulled {len(fr)}/{len(kt)} ({100*len(fr)//max(1,len(kt))}%)')
print(f'ACCEPTANCE drop (WITH dropped a prediction WITHOUT had): {len(acc)}/{len(keep_res)}')
json.dump({'catch': catch_res, 'keep': keep_res}, open(os.path.join(os.path.dirname(__file__), 'classifier_lessons_2026_06_16/target_hygiene_eval.json'), 'w'), indent=1)
print('\nFALSE-REJECT detail:', [(r['id'], r['ticker'], r['wo'][1], '->', r['wi']) for r in fr][:8])
