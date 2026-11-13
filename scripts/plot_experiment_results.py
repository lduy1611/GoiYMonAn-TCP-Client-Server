"""Create charts from the recorded benchmark CSV without changing measurements."""
from __future__ import annotations

import csv
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    csv_path = root / "statics/results/benchmark_tcp.csv"
    image_dir = root / "statics/results"
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise RuntimeError("benchmark CSV is empty")
    versions = {row["dataset_version"] for row in rows}
    if len(versions) != 1:
        raise RuntimeError(f"benchmark contains multiple dataset versions: {versions}")

    concurrency = [int(row["concurrency"]) for row in rows]
    p50 = [float(row["p50_ms"]) for row in rows]
    p95 = [float(row["p95_ms"]) for row in rows]
    throughput = [float(row["throughput_req_s"]) for row in rows]

    plt.figure(figsize=(8, 4.8))
    plt.plot(concurrency, p50, marker="o", linewidth=2, label="P50")
    plt.plot(concurrency, p95, marker="o", linewidth=2, label="P95")
    plt.xlabel("Số client đồng thời")
    plt.ylabel("Độ trễ (ms)")
    plt.title(f"TCP latency — {next(iter(versions))}")
    plt.xticks(concurrency)
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(image_dir / "benchmark_latency.png", dpi=160)
    plt.close()

    plt.figure(figsize=(8, 4.8))
    plt.plot(concurrency, throughput, marker="o", linewidth=2, color="#16803c")
    plt.xlabel("Số client đồng thời")
    plt.ylabel("Throughput (request/s)")
    plt.title(f"TCP throughput — {next(iter(versions))}")
    plt.xticks(concurrency)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(image_dir / "benchmark_throughput.png", dpi=160)
    plt.close()
    print("latency_plot=statics/results/benchmark_latency.png")
    print("throughput_plot=statics/results/benchmark_throughput.png")
    print("dataset_version=" + next(iter(versions)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
