import json, os, subprocess, sys, time
JUDGE='/home/nimroddd/quantanalytics/backend/scripts/preguard_cohort_judge_2026_06_15.py'
SUS='/tmp/preguard_suspects.json'; VP='/tmp/preguard_verdicts.json'
def judgeable():
    s=json.load(open(SUS)); v=json.load(open(VP)) if os.path.exists(VP) else {}
    return sum(1 for r in s if str(r['id']) not in v and os.path.exists(f"/tmp/heal/timed/{r['vid']}.json"))
loops=0
while True:
    loops+=1
    n=judgeable()
    print(f'[driver loop {loops}] judgeable={n} fetch_done={os.path.exists("/tmp/preguard_fetch_wave_done")}', flush=True)
    if n>0:
        subprocess.run([sys.executable, JUDGE, SUS, VP], env=os.environ)
    if os.path.exists('/tmp/preguard_fetch_wave_done') and judgeable()==0:
        break
    time.sleep(120)
open('/tmp/preguard_judge_all_done','w').write('1')
print('JUDGE DRIVER COMPLETE', flush=True)
