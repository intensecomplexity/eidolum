-- Phase 3b (2026-06-11): re-mark the 163 LLM-judged vague-conditional /
-- explanatory over-inference ticker_calls -> 'unresolved'. These were
-- hard-scored (92 HIT + 68 MISS + 3 NEAR) but are NOT committed directional
-- calls (e.g. CLF id 616181 "Cleveland Cliffs matters here because... a major
-- supplier to the auto market"). One-shot claude -p judged the 304 tighter-pool
-- candidates a/b/c with a conservative KEEP-on-doubt bias; only the 163 (a)
-- verdicts are flagged here. The 135 (b) genuine calls + 6 (c) reported-speech
-- are left untouched.
--
-- FLAG-NOT-DELETE: outcome='unresolved' drops them from accuracy (both
-- directions) on every user/leaderboard surface while keeping the rows in the
-- DB for admin visibility/audit. Idempotent (the outcome IN (...) guard skips
-- already-unresolved rows); pinned to the exact 163 audited ids. Run manually
-- against prod (DATABASE_PUBLIC_URL, as owner), then refresh forecaster stats.
--
--   psql "$DATABASE_PUBLIC_URL" -f backend/scripts/phase3b_remark_judged_conditionals.sql
--   curl -XPOST .../api/admin/refresh-forecaster-stats   (server-side, ~2min)

UPDATE predictions
SET outcome = 'unresolved',
    evaluation_summary = 'Phase-3b re-mark: LLM-judged vague-conditional/explanatory over-inference -> unresolved (excluded from accuracy)',
    evaluated_at = NOW()
WHERE id IN (
    605854, 605905, 605906, 605996, 606180, 606250, 606319, 606320, 606346,
    606371, 606400, 606433, 606555, 606606, 606612, 606631, 606649, 606676,
    606781, 607012, 607024, 607124, 607214, 607297, 607323, 607436, 607438,
    607540, 607601, 607682, 607806, 607836, 607847, 607912, 607925, 607961,
    608008, 608027, 608030, 608221, 608414, 608564, 608635, 608640, 608661,
    608985, 608993, 609023, 609062, 609067, 609161, 609171, 609324, 609399,
    609461, 609482, 609533, 609988, 610007, 610080, 610090, 610095, 610440,
    610452, 610460, 610488, 610512, 610700, 610872, 610942, 611015, 611049,
    611216, 611412, 612012, 612021, 612057, 612094, 612121, 612122, 612230,
    612473, 612552, 612553, 612554, 612782, 612901, 612907, 613777, 613846,
    613963, 613979, 614071, 614165, 614243, 614264, 614421, 614703, 614826,
    614841, 614861, 614891, 614892, 614983, 614999, 615106, 615641, 615642,
    615663, 615669, 615670, 615689, 615817, 615830, 616012, 616181, 616183,
    616234, 616236, 616355, 616384, 616468, 616499, 616563, 616581, 616583,
    616720, 616772, 617098, 617215, 619067, 619070, 619079, 619083, 619092,
    619095, 619140, 619168, 619173, 623357, 623764, 623850, 623952, 624016,
    624604, 624734, 624776, 624810, 624815, 624819, 625473, 625930, 625976,
    626020, 626113, 626392, 626398, 626400, 626420, 626551, 627064, 627092,
    629034
)
AND outcome IN ('hit', 'near', 'miss', 'correct', 'incorrect');
