import statistics
import time
from collections import Counter
from typing import Sequence, Any

from load_tests.client import RequestResult


def display_metrics(
    results: Sequence[RequestResult],
    total_time: float,
    additional_stats: dict[str, Any] = None,
):
    print("=" * 50)
    print("LOAD TEST RESULTS")
    print("=" * 50)

    total_requests = len(results)
    successful = sum(1 for r in results if r.is_success)
    errors = total_requests - successful

    print(f"Total Requests:      {total_requests}")
    print(f"Total Time:          {total_time:.2f} s")
    if total_time > 0:
        print(f"Requests per second: {total_requests / total_time:.2f} req/s")
    print("-" * 50)
    print(f"Successful (2xx):    {successful}")
    
    status_codes = Counter(r.status_code for r in results if r.status_code is not None)
    for code, count in sorted(status_codes.items()):
        print(f"  Status {code}: {count}")

    network_errors = sum(1 for r in results if r.error is not None)
    if network_errors > 0:
        print(f"Network/Timeouts:    {network_errors}")
    
    print("-" * 50)
    latencies = [r.latency for r in results if r.status_code is not None]
    if latencies:
        print("Latency Distribution:")
        print(f"  Min:  {min(latencies):.4f} s")
        print(f"  Max:  {max(latencies):.4f} s")
        print(f"  Avg:  {statistics.mean(latencies):.4f} s")
        if len(latencies) >= 2:
            print(f"  p50:  {statistics.median(latencies):.4f} s")
            try:
                quants = statistics.quantiles(latencies, n=100)
                print(f"  p95:  {quants[94]:.4f} s")
                print(f"  p99:  {quants[98]:.4f} s")
            except statistics.StatisticsError:
                pass
                
    if additional_stats:
        print("-" * 50)
        for k, v in additional_stats.items():
            print(f"{k}: {v}")
    
    print("=" * 50)
