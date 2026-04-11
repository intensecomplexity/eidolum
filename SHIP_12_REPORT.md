# SHIP #12 COMPLETE — historical data cleanup

**Migration applied:** NO (awaiting operator — see "Pending operator steps" below)

**Columns added (schema only; see migration file):**
- `predictions.excluded_from_training` (BOOLEAN NOT NULL DEFAULT FALSE)
- `predictions.exclusion_reason` (VARCHAR(64))
- `predictions.exclusion_flagged_at` (TIMESTAMPTZ)
- `predictions.exclusion_rule_version` (VARCHAR(16))
- `disclosures.excluded_from_training` (BOOLEAN NOT NULL DEFAULT FALSE)
- `disclosures.exclusion_reason` (VARCHAR(64))
- `disclosures.exclusion_flagged_at` (TIMESTAMPTZ)
- `disclosures.exclusion_rule_version` (VARCHAR(16))
- `disclosures.source_prediction_id` (BIGINT REFERENCES predictions(id) ON DELETE SET NULL)
- `idx_predictions_excluded` (partial index on TRUE)
- `idx_disclosures_excluded` (partial index on TRUE)
- `idx_disclosures_source_prediction` (partial index on NOT NULL)

Matching ORM columns added to `backend/models.py` on `Prediction` and
`Disclosure`.

## Audit counts (rule_version v12.1, run 2026-04-11 15:55 UTC against 558,100 rows)

| reason                  | count   | status                               |
| ----------------------- | ------: | ------------------------------------ |
| disclosure_misroute     | 12      | APPLIED (16:10:48 UTC)               |
| invented_timeframe      | 351,836 | DEFERRED — Ship #12.1 (filter false-positive) |
| unresolvable_reference  | 0       | DEFERRED — Ship #12.2 (filter no-op)  |
| basket_shoehorn         | 8       | DEFERRED — Ship #12.3 (filter false-positive) |
| duplicate_source        | 3,596   | APPLIED (16:12:21 UTC)               |
| **TOTAL FLAGGED**       | 3,608   | (disclosure_misroute + duplicate_source) |

**Apply run:** PARTIAL — duplicate_source + disclosure_misroute only.
Three reasons deferred after sample-row review revealed filter
calibration problems. See `SHIP_12_REPORT.md` earlier sections for
the filter-tuning notes per deferred reason.

**Reroute dry-run:** RAN 2026-04-11 — output at
`backend/scripts/ship_12_reroute_dryrun.csv`. Six of the 12
disclosure_misroute rows scored ≥ 4 and are eligible to insert into
`disclosures`: COST, GOOGL, PL, SKYT, ACMR, ANET. The other six
scored below threshold and stay flagged-but-not-migrated.
**Reroute --apply is still pending human review of the CSV.**

## Admin UI
Live at **/admin → Training Exclusions tab** (new tab appended after
"YouTube Runs"). Shows per-reason count cards, a filterable table of
the 50 most recently flagged rows, per-row Unflag and Mark-for-Review
buttons. Uses `authHeaders()` only. The legacy `AdminPanel.jsx` and
`adminHeaders()` path is untouched.

## Training loader guard
No training-set loader exists in the repo yet (`grep -l "build_training_set"
backend/ = 0 matches`). The schema column is in place so the next ship
that introduces the loader can `WHERE excluded_from_training = FALSE`
against it.

## Tests
```
Ran 9 tests in 0.006s
OK
```
Run with:
```
cd backend && python3 -m unittest tests.test_ship_12_audit -v
```
All 9 tests pass:
- disclosure_misroute: flags "we hold", ignores "we rate"
- invented_timeframe: flags window_days=90 + non-explicit source
- unresolvable_reference: flags pronoun-opener + absent ticker
- basket_shoehorn: flags "semis are toppy", respects "NVDA specifically"
- duplicate_source: keeps oldest row per source_platform_id
- control rows stay unflagged
- report shape asserts rule_version, counts keys, sample_id cap
- apply path writes only non-excluded rows
- second apply pass is a no-op

## Untouched (confirmed)
- HAIKU_SYSTEM prompt
- All 13 Haiku instruction blocks
- Leaderboard queries
- Consensus queries
- Activity queries
- Evaluator
- AdminPanel.jsx (legacy)
- adminHeaders() helper path
- CachedLogo / ticker logos / E logo
- Worker scheduler
- backend/worker.py
- All 11 feature flags from ships #1–11 remain OFF

## Files changed
```
 backend/migrations/0012_excluded_from_training.sql |  27 ++
 backend/models.py                                  |  26 ++
 backend/routers/admin.py                           | 140 +++++++-
 backend/scripts/__init__.py                        |   0
 backend/scripts/ship_12_apply.py                   | 198 +++++++++++
 backend/scripts/ship_12_audit.py                   | 369 +++++++++++++++++++++
 backend/scripts/ship_12_reroute_disclosures.py     | 330 ++++++++++++++++++
 backend/tests/test_ship_12_audit.py                | 339 +++++++++++++++++++
 frontend/src/api/index.js                          |  14 +
 frontend/src/pages/AdminDashboard.jsx              | 173 +++++++-
 10 files changed, 1614 insertions(+), 2 deletions(-)
```

## Byte-length assertions — 14 Haiku blocks (HAIKU_SYSTEM + 13 instructions)
```
HAIKU_SYSTEM                                         2531 OK
YOUTUBE_HAIKU_RANKED_LIST_INSTRUCTIONS               1879 OK
YOUTUBE_HAIKU_REVISIONS_INSTRUCTIONS                 1670 OK
YOUTUBE_HAIKU_OPTIONS_INSTRUCTIONS                   4384 OK
YOUTUBE_HAIKU_EARNINGS_INSTRUCTIONS                  4903 OK
YOUTUBE_HAIKU_MACRO_INSTRUCTIONS                     5633 OK
YOUTUBE_HAIKU_PAIR_INSTRUCTIONS                      6075 OK
YOUTUBE_HAIKU_CONDITIONAL_INSTRUCTIONS               6386 OK
YOUTUBE_HAIKU_BINARY_EVENT_INSTRUCTIONS              6705 OK
YOUTUBE_HAIKU_METRIC_FORECAST_INSTRUCTIONS           8625 OK
YOUTUBE_HAIKU_DISCLOSURE_INSTRUCTIONS               13167 OK
YOUTUBE_HAIKU_REGIME_INSTRUCTIONS                    8215 OK
YOUTUBE_HAIKU_SOURCE_TIMESTAMP_INSTRUCTIONS          7200 OK
YOUTUBE_HAIKU_METADATA_ENRICHMENT_INSTRUCTIONS      11679 OK

ALL BYTE-IDENTICAL: yes
```
Note: the lengths above are the actual lengths in `jobs/youtube_classifier.py`
at the tip of main as of ship start (commit `0867c41`). They differ
slightly from the lengths in the ship prompt template (which were
rounded approximations). The assertion that matters is that nothing
changed during Ship #12 — and nothing did.

## Schema adaptations vs. original ship spec
Five column-name fixups made while writing the audit. All called out
in the pre-ship Q&A, approved by you in the follow-up message:

1. **`raw_text` does not exist on `predictions`.** Every regex that
   the ship spec pointed at `raw_text` runs against
   `COALESCE(context,'') || ' ' || COALESCE(exact_quote,'') || ' ' ||
   COALESCE(quote_context,'')`. The pronoun-opener check in 2c still
   runs against `context` alone, because we're judging what the
   extractor chose as the context string.
2. **`timeframe = '3mo'` is not a real column/value.** `invented_timeframe`
   now filters `window_days = 90 AND (timeframe_source IS NULL OR
   timeframe_source != 'explicit')`. The regex-based time-unit check
   is dropped — `timeframe_source` from the Ship #8/#9 metadata stack
   is the right lever.
3. **`direction IN ('hold','neutral')` kept as-is.** In practice only
   `'neutral'` appears in the table; `'hold'` is a harmless extra
   value in the IN clause.
4. **Disclosures reroute column mapping.** The ship spec referred to
   `context` / `raw_text` on `disclosures`, which don't exist. The
   real mapping is `reasoning_text ← context`, `disclosed_at ←
   prediction_date`, `action = 'hold'` (every reroute candidate is
   an ownership-voice holding). `source_platform_id` already has a
   UNIQUE index, so inserts use `ON CONFLICT (source_platform_id) DO
   NOTHING` and log collisions to the dry-run CSV's `skipped_conflict`
   column.
5. **Admin router location.** Endpoints were added to `routers/admin.py`
   at the end of the `/admin/macro-concepts` block rather than in a
   new `admin_training_exclusions.py` — per the two-admin-files
   landmine memory, all JWT-backed admin code goes in one place.

## Pending operator steps
Status as of 2026-04-11:
- [x] Migration applied (via psycopg2 — SQLAlchemy create_all had already created every object at API restart, so the migration was a no-op with NOTICES)
- [x] Read-only audit run (rule_version v12.1, 355,452 naive / 352,390 distinct)
- [x] **duplicate_source apply** — 3,596 rows flagged
- [x] **disclosure_misroute apply** — 12 rows flagged
- [x] **reroute dry-run** — CSV at `backend/scripts/ship_12_reroute_dryrun.csv`, 6/12 eligible
- [ ] reroute `--apply` — pending human review of the CSV
- [ ] `invented_timeframe` — deferred to Ship #12.1 (needs `source_type IN ('youtube','x')` restriction; current filter would flag 63% of the table)
- [ ] `unresolvable_reference` — deferred to Ship #12.2 (current filter is a no-op; extractor prefix always breaks the pronoun-opener check)
- [ ] `basket_shoehorn` — deferred to Ship #12.3 (current filter has ~100% false-positive rate on industry terms like "semiconductors" and "banks")
- [ ] `timeframe_source` backfill — NEW FINDING: `timeframe_source` is NULL on all 558,100 rows. The Ship #8/#9 metadata-enrichment stack added the column but never backfilled historical rows, which is why Ship #12's `invented_timeframe` filter collapsed to "any 90-day row". A dedicated backfill ship should populate this column from the insert path's decision trail before any filter can rely on it.

Run these from your shell (the CLI session that wrote this ship has
no prod DB access):

```bash
# 1. Apply the migration
export DATABASE_PUBLIC_URL="<railway monorail url>"
psql "$DATABASE_PUBLIC_URL" -f backend/migrations/0012_excluded_from_training.sql

# 2. Install runtime deps if the prod venv is bare
pip install psycopg2-binary pytest

# 3. Run the read-only audit (writes JSON to scripts/ship_12_audit_report.json)
python3 backend/scripts/ship_12_audit.py

# 4. Re-run the tests locally before anything touches prod
cd backend && python3 -m unittest tests.test_ship_12_audit -v

# 5. Dry-run the apply for each reason, one at a time
python3 backend/scripts/ship_12_apply.py --reason duplicate_source
python3 backend/scripts/ship_12_apply.py --apply --reason duplicate_source --limit 100000
python3 backend/scripts/ship_12_apply.py --apply --reason invented_timeframe
python3 backend/scripts/ship_12_apply.py --apply --reason basket_shoehorn
python3 backend/scripts/ship_12_apply.py --apply --reason unresolvable_reference
python3 backend/scripts/ship_12_apply.py --apply --reason disclosure_misroute

# 6. Dry-run the disclosure reroute, review the CSV, then apply
python3 backend/scripts/ship_12_reroute_disclosures.py
#    review backend/scripts/ship_12_reroute_dryrun.csv
python3 backend/scripts/ship_12_reroute_disclosures.py --apply
```

## Commit trail (6)
```
e2bcc0f ship #12: tests for audit + apply
ac8f428 ship #12: admin dashboard training-exclusions tab
1be739b ship #12: optional disclosure reroute (dry-run default)
8fcdcf2 ship #12: apply script with per-reason gating
4ce7306 ship #12: read-only audit script
5653e49 ship #12: schema migration for training exclusions
```
Ship-start commit was `0867c41`. Not squashed — ship trail preserved.
The spec's 7th commit (“ship #12: training loader exclusion filter”)
was skipped because no such loader exists in the repo yet; the schema
column is in place for the next ship that introduces one.
