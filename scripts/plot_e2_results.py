"""Plot run-level E2 summary values without pooling or altering raw measurements."""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("summary_csv")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    summary_path = root / args.summary_csv
    output_prefix = root / "statics/results" / summary_path.stem.replace("e2_summary", "e2")
    with summary_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    versions = {row["dataset_version"] for row in rows}
    if len(versions) != 1:
        raise RuntimeError(f"multiple dataset versions: {versions}")
    grouped: dict[tuple[str, int], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(row["protocol"], int(row["concurrency"]))].append(row)

    def aggregate(protocol: str, concurrency: int, field: str) -> tuple[float, float, float]:
        values = [float(row[field]) for row in grouped[(protocol, concurrency)]]
        return sum(values) / len(values), min(values), max(values)

    colors = {"TCP": "#1565c0", "HTTP": "#ef6c00"}
    levels = sorted({int(row["concurrency"]) for row in rows})
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), sharex=True)
    for protocol in ("TCP", "HTTP"):
        means_p50, lows_p50, highs_p50 = zip(*(aggregate(protocol, level, "p50_ms") for level in levels))
        means_p95, lows_p95, highs_p95 = zip(*(aggregate(protocol, level, "p95_ms") for level in levels))
        axes[0].errorbar(levels, means_p50, yerr=[[(m - lo) for m, lo in zip(means_p50, lows_p50)], [(hi - m) for m, hi in zip(means_p50, highs_p50)]], marker="o", color=colors[protocol], label=f"{protocol} P50")
        axes[0].errorbar(levels, means_p95, yerr=[[(m - lo) for m, lo in zip(means_p95, lows_p95)], [(hi - m) for m, hi in zip(means_p95, highs_p95)]], marker="s", linestyle="--", color=colors[protocol], label=f"{protocol} P95")
        means_t, lows_t, highs_t = zip(*(aggregate(protocol, level, "throughput_req_s") for level in levels))
        axes[1].errorbar(levels, means_t, yerr=[[(m - lo) for m, lo in zip(means_t, lows_t)], [(hi - m) for m, hi in zip(means_t, highs_t)]], marker="o", color=colors[protocol], label=protocol)
    axes[0].set_title("E2 latency (mean run-level values)")
    axes[0].set_ylabel("ms")
    axes[1].set_title("E2 throughput (mean run-level values)")
    axes[1].set_ylabel("request/s")
    for axis in axes:
        axis.set_xlabel("Concurrent clients")
        axis.set_xticks(levels)
        axis.grid(True, alpha=0.3)
        axis.legend()
    fig.suptitle(f"Dataset {next(iter(versions))}; error bars show min–max across 3 runs")
    fig.tight_layout()
    output_path = output_prefix.with_name(output_prefix.name + "_charts.png")
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
    print(f"charts={output_path}")
    print(f"dataset_version={next(iter(versions))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
