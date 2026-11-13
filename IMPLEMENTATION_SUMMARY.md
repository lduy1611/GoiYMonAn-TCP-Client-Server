# Implementation summary

Historical implementation summary for phases 1–4 and the submitted report. The operation counts and test results below describe that milestone. For the current five-operation/UI v1.2.3 demo, use the [README](README.md) and [document index](docs/README.md). No historical measurements have been updated to current results.

## Scope

This project implements the “Hệ thống gợi ý món ăn sử dụng TCP Client–Server” with a TCP JSON protocol, a MySQL-backed server repository, a FastAPI Web gateway, and a Vietnamese Web interface. Phase 4 adds a non-destructive Vietnamese recipe dataset and reproducible experiment scripts.

## Modules

- `source/common/protocol.py`: 4-byte big-endian length-prefixed JSON framing, UTF-8 validation, request envelope validation, UUID `request_id`, protocol errors and the 65536-byte frame limit.
- `source/server/main.py`: bounded TCP accept loop, per-client handler, request/response logging, error mapping and shutdown.
- `source/server/handler.py`: operation validation and dispatch for PING, LIST_INGREDIENTS, GET_RECIPE and RECOMMEND.
- `source/server/repository.py`: legacy read-only SQLite repository plus the production `MySQLRepository`; MySQL uses a 32-connection pool and returns each checked-out connection to the pool after a request.
- `source/server/ranking.py`: unchanged B0 baseline and P1 proposed ranking formulas, filtering and tie-break rules.
- `source/client/tcp_client.py`: independent TCP client with connection timeout, total request budget and request ID correlation.
- `source/web/main.py`: FastAPI gateway that communicates with the TCP Server through real sockets. It does not import a repository or ranking function and does not connect to MySQL.
- `source/web/templates/` and `source/web/static/`: Vietnamese responsive interface, ingredient selection/exclusion state, loading/error/empty/success states and recipe details.

## MySQL and dataset

- [source/database/database.sql](source/database/database.sql) creates the MySQL schema with the same primary keys, foreign keys and relation table as SQLite.
- [source/database/mysql_seed.sql](source/database/mysql_seed.sql) is the original fixture seed.
- [source/database/mysql_expanded_seed.sql](source/database/mysql_expanded_seed.sql) is the phase 4 additive seed. It adds recipe IDs 11–50, ingredient IDs 16–50, ingredient relations and multi-step instructions, then sets `dataset_version` to `vi-v2-50-recipes`. It contains no delete operation.
- [source/database/mysql_recipe_instructions_update.sql](source/database/mysql_recipe_instructions_update.sql) refines recipes 1–10 with ingredient-compatible numbered steps and advances the version to `vi-v2-50-recipes-r1` without changing IDs, relations or cooking times.
- The expanded dataset and instruction refinement are confirmed by a direct MySQL audit: 50 ingredients, 50 recipes, 252 relations, `dataset_version=vi-v2-50-recipes-r1`, and at least three numbered steps for every recipe.

## TCP and Web behavior

The TCP protocol remains unchanged: version 1 envelope, UUID request ID, 4-byte header, JSON body, and the four existing operation names. RECOMMEND continues to support `algorithm=baseline` for B0 and `algorithm=proposed` for P1. FastAPI sends HTTP requests to the TCP Server and returns HTTP 503 when the upstream server is unavailable.

## Verification already completed

- Full regression suite: **16 passed, 0 failed, 0 skipped**.
- MySQL/Web target suite: **5 passed, 0 failed, 0 skipped**.
- MySQL integration coverage includes the four TCP operations, ten concurrent TCP clients and HTTP 503 during TCP outage.
- Dataset quality audit: **PASS** for all 50 recipes and 252 relations.
- Phase 4 E2 contains 7,560 raw TCP/HTTP rows and 24 run summaries against `dataset_version=vi-v2-50-recipes-r1`; all 24 summary rows passed in the official run.

Current audit evidence:

- Dataset hash: `c97ab2c7d127be738efc9c97c2e299bea5af69e7c3884757fd09814fbfb3fcdf`
- Code hash: `fa4a3309b3c844480fd2e08ffd15f61aaa8c700ebc81af9cf578e2fe78fbc028`
- Local audit log: `statics/results/phase4_dataset_audit.log` (not distributed); the recorded [JSON audit](statics/results/phase4_dataset_audit.json) is available.

The final audit and experiment artifacts are recorded in [phase4_dataset_audit.json](statics/results/phase4_dataset_audit.json), [e2_raw_20261029_114105.csv](statics/results/e2_raw_20261029_114105.csv), [e2_summary_20261029_114105.csv](statics/results/e2_summary_20261029_114105.csv) and [EXPERIMENT_RESULTS.md](EXPERIMENT_RESULTS.md). Associated local logs `statics/results/phase4_dataset_audit.log` and `statics/results/e2_run_20261029_114105.log` are not distributed by Git; they are not required to run the demo.

## Phase 4 experiment commands

From the project root, using the configured virtual environment:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_tcp.py
.\.venv\Scripts\python.exe scripts\compare_algorithms.py
```

These commands start the production MySQL-backed TCP Server on a temporary local port and write real results to `statics/results/benchmark_tcp.csv`, `statics/results/benchmark_tcp.log`, `statics/results/algorithm_comparison.csv` and `statics/results/algorithm_comparison.log`. A nonzero exit code means at least one measured request failed.
