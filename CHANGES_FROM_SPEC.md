# Changes from SPEC.md

Status: implementation phases 1–4, TCP core, Web gateway, MySQL repository, expanded dataset and E2 experiment artifacts.

## Deliberate differences

1. The runtime interpreter available in this workspace is Python 3.13.7, not a pinned 3.11 environment. This remains within the SPEC requirement “Python 3.11 trở lên”.
2. The seed dataset is the four-ingredient fixture from TEST_PLAN.md, not the target 30–60 ingredient / 30–50 recipe provenance dataset. It is for protocol and integration testing only.
3. E2 TCP/HTTP benchmark scripts and raw evidence are implemented. Independent recommendation quality evaluation and final Word-report screenshots remain pending.
4. Server log timing fields currently preserve the required names but use zero placeholders for receive/send phase timings; service timing and request correlation are real. A later measurement pass must split these phases before claiming benchmark results.
5. The original 15-ingredient/10-recipe fixture remains in the repository for regression tests; the active MySQL dataset contains 50 ingredients, 50 recipes and 252 relations.
6. Runtime TCP Server storage is now MySQL by default and requires `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, and `MYSQL_DATABASE` from `.env`. SQLite is intentionally retained for rollback/regression comparison until the migration is verified.
7. MySQL integration tests remain conditional in code on a reachable configured database, as required for a portable test suite. In the configured migration environment they were executed, not skipped: **2 passed, 0 failed, 0 skipped**.
8. Phase 4 adds an additive MySQL seed with recipes 11–50 and ingredients 16–50. The script is intentionally non-destructive. Direct audit now confirms 50 recipes, 50 ingredients, 252 relations and `dataset_version=vi-v2-50-recipes-r1` after instruction refinement.
9. Phase 4 adds [mysql_recipe_instructions_update.sql](source/database/mysql_recipe_instructions_update.sql) for recipes 1–10. It has now been applied and the audit confirms at least three numbered steps for all 50 recipes; IDs, relations and cooking times remain unchanged.
10. Phase 4 includes real-socket benchmark and B0/P1 comparison scripts. The recorded CSVs use `vi-v2-50-recipes-r1`; they report observed ranking outputs and timing only, not Precision@5/nDCG@5 or algorithm superiority.

## Confirmed unchanged

The frame format, 65536-byte limit, UUID correlation, supported TCP operations, error codes, validation limits, per-handler database connection, B0/P1 formulas, ranking tie-breakers, and bounded 32-connection accept policy follow SPEC 1.0. FastAPI routes use real TCP sockets and do not access SQLite/MySQL or perform ranking. The MySQL repository uses a thread-safe connection pool with one checked-out connection per TCP handler/request.

These differences remain documented in the report. The migration verification is now complete for the configured MySQL environment.

## Phase 2 UI correction record

- No TCP framing, envelope, operation, validation limit, or ranking algorithm was changed.
- The Web state now keeps available and excluded ingredient IDs in disjoint collections; moving an item between them removes it from the previous collection before sending `RECOMMEND`.
- Recipe instructions are rendered as numbered UI steps only when the database contains multiple instruction lines. The current fixture stores single-line instructions, so the UI displays that text verbatim and explicitly reports that structured steps are not present.
- The detail page uses an explicit Vietnamese-capable font fallback stack and a solid sticky header background to prevent content showing through while scrolling.

## Verification

The full regression suite completed with **16 passed, 0 failed, 0 skipped**. The focused MySQL/Web suite completed with **5 passed, 0 failed, 0 skipped**. Official E2 completed with **24/24 run summaries Pass**, including TCP and separate HTTP measurements with 7,560 raw rows. E3 labeled-quality experiments and some evidence captures remain incomplete as documented in `EXPERIMENT_RESULTS.md`. SQLite remains only as a preserved regression/rollback path; production `TCPServer()` uses `MySQLRepository`.
