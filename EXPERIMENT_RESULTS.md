# Experiment results

Date of analysis: 2026-10-29

This is historical report evidence, not the current demo setup. Use the [current README](README.md) and [document index](docs/README.md) for UI v1.2.3 and current test results. Historical `.log` files named below are not distributed by Git; names identify local evidence only. Recorded CSV/JSON/charts remain available in this repository. Missing log downloads do not mean the experiment was rerun or its measurements changed.

This document analyzes the recorded CSV and log files only. No benchmark value was edited or recomputed in the source CSV. The application algorithm and dataset were not changed during analysis.

## Official E2 measurement

The following is the official E2 run produced by [benchmark_e2.py](scripts/benchmark_e2.py) at `2026-10-29 11:41:05` local time. It supersedes the earlier single-request preliminary benchmark. The driver ran 5 warmup requests and 30 measured requests per worker, for 3 runs at each concurrency level 1, 5, 10 and 20, first through TCP and then through a real Uvicorn/FastAPI HTTP socket.

- Raw evidence: [e2_raw_20261029_114105.csv](statics/results/e2_raw_20261029_114105.csv)
- Summary evidence: [e2_summary_20261029_114105.csv](statics/results/e2_summary_20261029_114105.csv)
- Local run log (not distributed): `statics/results/e2_run_20261029_114105.log`; recorded raw/summary CSVs are linked above.
- Local Uvicorn log (not distributed): `statics/results/e2_uvicorn_20261029_114105.log`; no downloadable HTTP server log is supplied here.
- Charts: [e2_20261029_114105_charts.png](statics/results/e2_20261029_114105_charts.png)

Raw integrity checks:

- 7,560 raw rows: 3,780 TCP and 3,780 HTTP.
- 6,480 measured rows and 1,080 warmup rows.
- 7,560 unique client request IDs.
- All rows identify `vi-v2-50-recipes-r1`.
- All raw request rows retain status and error fields; no outlier filtering was applied.
- All 6,480 measured rows and all 1,080 warmup rows completed successfully in this final run.

The TCP rows validate response request IDs against the sent request ID. HTTP rows keep both the generated client `request_id` and the FastAPI-generated `response_request_id`; the Web middleware creates its own request ID rather than echoing the supplied `X-Request-ID`.

### E2 summary by independent run

P50/P95 are nearest-rank percentiles over successful measured requests in each run. Throughput is successful measured requests divided by that run's measured wall-clock duration. `error_rate` is failed/attempted.

| Protocol | Run | C | Attempted | Success | Failed | Error rate | P50 ms | P95 ms | Throughput req/s | Status |
|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|:---|
| TCP | r1 | 1 | 30 | 30 | 0 | 0% | 15.453 | 29.348 | 53.301 | PASS |
| TCP | r2 | 1 | 30 | 30 | 0 | 0% | 15.913 | 31.022 | 48.258 | PASS |
| TCP | r3 | 1 | 30 | 30 | 0 | 0% | 15.637 | 29.900 | 52.407 | PASS |
| TCP | r1 | 5 | 150 | 150 | 0 | 0% | 34.756 | 56.339 | 118.203 | PASS |
| TCP | r2 | 5 | 150 | 150 | 0 | 0% | 38.247 | 43.669 | 110.751 | PASS |
| TCP | r3 | 5 | 150 | 150 | 0 | 0% | 41.734 | 46.483 | 105.935 | PASS |
| TCP | r1 | 10 | 300 | 300 | 0 | 0% | 85.436 | 103.822 | 101.188 | PASS |
| TCP | r2 | 10 | 300 | 300 | 0 | 0% | 83.055 | 98.937 | 104.348 | PASS |
| TCP | r3 | 10 | 300 | 300 | 0 | 0% | 82.753 | 97.896 | 105.498 | PASS |
| TCP | r1 | 20 | 600 | 600 | 0 | 0% | 171.919 | 208.795 | 99.974 | PASS |
| TCP | r2 | 20 | 600 | 600 | 0 | 0% | 179.218 | 219.203 | 94.965 | PASS |
| TCP | r3 | 20 | 600 | 600 | 0 | 0% | 190.151 | 233.284 | 90.081 | PASS |
| HTTP | r1 | 1 | 30 | 30 | 0 | 0% | 24.815 | 48.199 | 34.469 | PASS |
| HTTP | r2 | 1 | 30 | 30 | 0 | 0% | 23.912 | 41.405 | 37.813 | PASS |
| HTTP | r3 | 1 | 30 | 30 | 0 | 0% | 21.620 | 35.549 | 39.436 | PASS |
| HTTP | r1 | 5 | 150 | 150 | 0 | 0% | 45.819 | 59.378 | 96.966 | PASS |
| HTTP | r2 | 5 | 150 | 150 | 0 | 0% | 38.276 | 52.156 | 109.537 | PASS |
| HTTP | r3 | 5 | 150 | 150 | 0 | 0% | 39.809 | 54.207 | 107.851 | PASS |
| HTTP | r1 | 10 | 300 | 300 | 0 | 0% | 101.041 | 124.840 | 85.266 | PASS |
| HTTP | r2 | 10 | 300 | 300 | 0 | 0% | 91.165 | 106.279 | 95.314 | PASS |
| HTTP | r3 | 10 | 300 | 300 | 0 | 0% | 88.074 | 117.103 | 94.697 | PASS |
| HTTP | r1 | 20 | 600 | 600 | 0 | 0% | 191.501 | 242.088 | 89.178 | PASS |
| HTTP | r2 | 20 | 600 | 600 | 0 | 0% | 183.730 | 221.685 | 91.107 | PASS |
| HTTP | r3 | 20 | 600 | 600 | 0 | 0% | 188.901 | 233.834 | 90.053 | PASS |

Across the 12 TCP runs, all 3,240 measured requests succeeded. Across the 12 HTTP runs, all 3,240 measured requests succeeded. The measurements show increasing latency as concurrency rises in this run, but they do not establish a production capacity limit.

### E2 limitations and remaining TEST_PLAN work

- This run satisfies the E2 request counts and three repetitions, but it is a closed-loop loopback test on one Windows machine, not a LAN or multi-machine capacity test.
- TCP `bytes_in`/`bytes_out` are complete framed bytes. HTTP byte fields are request/response body bytes measured by the HTTP driver, not full Ethernet/TCP wire bytes.
- E2 does not evaluate recommendation quality. The project still lacks the independent 30-query labeled set, A1 comparison, P@5, nDCG@5, IDCG=0 handling and optional bootstrap confidence interval required by E3.
- A separate HTTP run was performed, but no claim is made that HTTP and TCP runs are statistically identical because they were sequential runs and not interleaved.
- LAN/mobile, Wireshark stream capture and clean-machine reproduction evidence remain pending.

## Dataset and code identity

The benchmark and algorithm comparison logs both identify the server as `MySQL-backed TCPServer` and every CSV row contains:

```text
dataset_version=vi-v2-50-recipes-r1
```

The dataset audit independently confirms 50 ingredients, 50 recipes, 252 `recipe_ingredients` relations and all recipe IDs 1–50.

- Dataset SHA-256: `c97ab2c7d127be738efc9c97c2e299bea5af69e7c3884757fd09814fbfb3fcdf`
- Code SHA-256: `fa4a3309b3c844480fd2e08ffd15f61aaa8c700ebc81af9cf578e2fe78fbc028`
- Dataset audit: [phase4_dataset_audit.json](statics/results/phase4_dataset_audit.json)
- Local dataset audit log (not distributed): `statics/results/phase4_dataset_audit.log`; the recorded JSON audit is linked above.

## Configuration and method

- Platform: Windows, Python 3.13.7 in `.venv`.
- Server: production `MySQL-backed TCPServer` on loopback with a temporary TCP port; the official E2 log records TCP port `57174` and HTTP port `57173`.
- Database access: MySQL repository with the configured 32-connection pool.
- Workload: `RECOMMEND`, selected ingredient IDs `[1, 2]`, empty exclusions, `top_k=5`, `algorithm=proposed`.
- Client mode: the benchmark creates a new TCP connection for each request; the workload is closed-loop.
- Each recorded concurrency level sent one request per client in one run. The script performed a readiness PING before measurement.
- Latency is measured by the client with `perf_counter`; p50 and p95 are based on successful requests in that row.
- Throughput is successful requests divided by the measured wall-clock duration.
- Error rate is `failed / requests * 100`.

## Historical preliminary TCP benchmark (superseded by official E2 above)

Source: [benchmark_tcp.csv](statics/results/benchmark_tcp.csv). Associated local log: `statics/results/benchmark_tcp.log` (not distributed).

| Concurrent clients | Requests | Success | Failed | Error rate | P50 (ms) | P95 (ms) | Throughput (req/s) | Status |
|---:|---:|---:|---:|---:|---:|---:|---:|:---|
| 1 | 1 | 1 | 0 | 0.00% | 22.532 | 22.532 | 43.223 | PASS |
| 5 | 5 | 5 | 0 | 0.00% | 8.809 | 9.921 | 440.187 | PASS |
| 10 | 10 | 10 | 0 | 0.00% | 33.176 | 34.912 | 258.325 | PASS |
| 20 | 20 | 20 | 0 | 0.00% | 70.918 | 78.001 | 232.087 | PASS |

Observed in this run: all 36 measured requests succeeded. The lowest observed p95 was 9.921 ms at concurrency 5. At concurrency 20, p95 was 78.001 ms and throughput was 232.087 request/s. These are observations for this single local-loopback run, not a capacity limit or a general performance guarantee.

Charts generated directly from the CSV:

- [benchmark_latency.png](statics/results/benchmark_latency.png)
- [benchmark_throughput.png](statics/results/benchmark_throughput.png)
- Reproduction script: [plot_experiment_results.py](scripts/plot_experiment_results.py)

## B0 versus P1 comparison

Source: [algorithm_comparison.csv](statics/results/algorithm_comparison.csv). Associated local log: `statics/results/algorithm_comparison.log` (not distributed).

The recorded columns measure: scenario, input ingredient IDs, algorithm name, request status, number of returned items, returned recipe ID order, server-computed ranking scores and one-request elapsed time. They do not contain human relevance labels.

| Scenario | Input IDs | Algorithm | Items | Returned recipe IDs | Scores | Elapsed (ms) |
|:---|:---|:---|---:|:---|:---|---:|
| basic | [1, 2] | B0 baseline | 5 | 1, 2, 3, 4, 10 | 2.0, 2.0, 1.0, 1.0, 1.0 | 6.461 |
| basic | [1, 2] | P1 proposed | 5 | 1, 3, 2, 10, 4 | 1.0, 0.85, 0.65, 0.5, 0.5 | 16.332 |
| soup | [1, 2, 3] | B0 baseline | 5 | 2, 1, 10, 3, 4 | 3.0, 2.0, 2.0, 1.0, 1.0 | 14.978 |
| soup | [1, 2, 3] | P1 proposed | 5 | 1, 10, 2, 3, 4 | 0.9, 0.9, 0.825, 0.8, 0.45 | 5.152 |
| meat | [4, 7] | B0 baseline | 5 | 2, 5, 8, 20, 48 | 1.0, 1.0, 1.0, 1.0, 1.0 | 4.985 |
| meat | [4, 7] | P1 proposed | 5 | 5, 20, 8, 2, 48 | 0.5, 0.383333, 0.325, 0.325, 0.325 | 4.877 |

The measured score definitions are the implementation's ranking scores:

- B0: `score = number of matched required ingredients`; ties sort by recipe ID.
- P1: `score = 0.7 * coverage + 0.3 * input_use`; ties then use missing count, cooking time and recipe ID.

These rows demonstrate that B0 and P1 can return different orderings and score scales under the same input. They do not establish that one algorithm is more accurate. In particular, the comparison is **not Precision@5, recall, MAP or nDCG@5** because there is no independent relevance-labeled query set. The elapsed times are only three single-request observations and should not be used as a statistically significant latency comparison.

## Test results associated with the experiment

- Full suite: **16 passed, 0 failed, 0 skipped**; historical local log `statics/results/phase4_final_dataset_pytest.log` is not distributed. This retains the reported result, not a new execution verified from the clone.
- Focused MySQL/Web suite: **5 passed, 0 failed, 0 skipped**; historical local log `statics/results/phase4_mysql_web_pytest.log` is not distributed. Current test commands and results are in the [README](README.md).
- The focused suite covers MySQL PING, LIST_INGREDIENTS, GET_RECIPE, RECOMMEND, ten concurrent TCP clients, FastAPI TCP routing and HTTP 503 during TCP outage.

## Experiments still missing versus TEST_PLAN.md

The official E2 artifact above completes the requested TCP and separate HTTP load matrix: 5 warmups and 30 measured requests per worker, 3 independent runs at C=1/5/10/20, raw per-request records, and run-level P50/P95/throughput/error rate. The following TEST_PLAN work remains:

- E3 still requires at least 30 independently labeled queries, fixed constraints, B0/P1/A1 paired evaluation, per-query results, P@5 and nDCG@5 with IDCG=0 handling, and optionally a seeded bootstrap confidence interval. None of those quality experiments were run, so no algorithm superiority claim is made.
- Additional evidence still not present in these artifacts includes LAN/mobile access (T32), Wireshark TCP stream capture (T37), and a clean-machine README reproduction (T38).

## Evidence photos for the Word report

Capture real screenshots only after recording the test timestamp, code hash and dataset hash in the caption:

1. TCP Server console plus CLI PING/RECOMMEND response.
2. Web page showing selected ingredients, returned ranking, score, matched/missing ingredients and recipe detail.
3. Web loading state and no-result state.
4. Web HTTP 503/error state while the TCP Server is stopped.
5. A TCP request ID visible in both client output and the server JSONL log.
6. MySQL Workbench showing the dataset version and the three counts: 50 ingredients, 50 recipes and 252 relations.
7. Benchmark CSV or terminal output showing the four concurrency rows and `dataset_version=vi-v2-50-recipes-r1`.
8. Optional: Wireshark Follow TCP Stream on the TCP port, with passwords and unrelated personal information excluded.

Recommended caption format:

```text
Test ID | timestamp | code SHA-256 | dataset SHA-256 | actual result | evidence file
```
