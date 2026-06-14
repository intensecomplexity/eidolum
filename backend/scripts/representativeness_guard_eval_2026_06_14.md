# Classifier hardening — representativeness guard eval (2026-06-14)

Forward guards for the quote-quality failure classes remediated this week
(commits ed18faa→e6370aa). Guard: `backend/jobs/representativeness_guard.py`,
hooked into `insert_youtube_prediction` (ticker_call). Classifier was STOPPED for
the ship; takes effect on Nimrod's restart. **Eval before merge (sacred).**

## Fixture (203 rows, from this week's gold)
`representativeness_guard_fixture_2026_06_14.json`: 80 requote_clean + 60
clean_pronoun + 20 normal_clean (gold KEEP — the false-reject tripwire) + 30
no_call + 7 reported_speech + 6 flip (gold actions). Transcripts from the cached
±90s windows fetched during the requote/heal ships.

## What shipped vs what the eval rejected
| guard | decision | basis |
|---|---|---|
| (a) ground quote on fuzzy match | SHIP (pure code) | stores transcript segment text, not the model paraphrase |
| (c) direction flip correction | SHIP | opposite-cue suspect → Sonnet verify → corrects direction (KEEP, never reject). flip 4/6, dir-acc 97.1% |
| (d) reported-speech hide flag | SHIP | reported-near suspect → verify → `is_reported_speech`. reversible. 4/7 |
| (e) no-call | SHIP **as reversible flag**, NOT reject | LLM no-call precision too low to hard-drop; `REPRESENTATIVENESS_NO_CALL_ACTION=flag` (default) hides via bundle. 50% catch, 6.2% clean soft-flag (upper bound) |
| (f) deterministic orphan reject | **REJECTED at merge** | unbiased 400-row sample: ±90s reject drops **23.5%** of valid calls, whole-transcript still **14.5%** (spoken-name/ASR variance defeats the ticker_sectors name map). Fails "no material clean-row regression." Orphan narration is instead caught by (e). |

## Verify model
Haiku FAILED its eval gate (34.4% clean false-reject, 60% catch) → fell back to
**Sonnet** (`REPRESENTATIVENESS_VERIFY_MODEL=sonnet`), per the documented small-gate lesson.

## Final numbers (Sonnet, no_call=flag, no (f) reject)
- **Genuinely-clean hard-reject: 0/80 (0.0%)** · clean soft-flag (reversible): 5/80 (6.2%)
- **requote_clean hard-reject: 0/80** · direction accuracy on kept: 168/173 (97.1%)
- no_call catch (flag): 15/30 (50%) · reported flagged: 4/7 · flip corrected: 4/6
- second-pass rate: **20.8% on an unbiased production sample** (62% on the suspect-enriched fixture)

## Knobs (all env, default-on after passing eval)
- `ENABLE_REPRESENTATIVENESS_GUARD` (default true) — master kill switch
- `REPRESENTATIVENESS_VERIFY_MODEL` (default sonnet) — haiku|sonnet
- `REPRESENTATIVENESS_NO_CALL_ACTION` (default flag) — flag|reject|off

No HAIKU_SYSTEM / 14-block edits. CLASSIFIER_VALIDATION_GATE stays shadow. Fail-open throughout.
