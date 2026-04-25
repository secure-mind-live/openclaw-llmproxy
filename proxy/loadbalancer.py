import random
import time
from collections import defaultdict


class LoadBalancer:
    def __init__(self):
        self._rr_counters: dict[str, int] = defaultdict(int)
        self._url_stats: dict[str, dict] = defaultdict(
            lambda: {"count": 0, "total_latency": 0.0}
        )

    def pick_url(self, backend_name: str, urls: list[str], strategy: str = "round_robin") -> str:
        if len(urls) == 1:
            return urls[0]
        if strategy == "random":
            return self._random(urls)
        if strategy == "least_latency":
            return self._least_latency(urls)
        return self._round_robin(backend_name, urls)

    def _round_robin(self, backend_name: str, urls: list[str]) -> str:
        idx = self._rr_counters[backend_name] % len(urls)
        self._rr_counters[backend_name] += 1
        return urls[idx]

    def _random(self, urls: list[str]) -> str:
        return random.choice(urls)

    def _least_latency(self, urls: list[str]) -> str:
        best_url = urls[0]
        best_avg = float("inf")
        for url in urls:
            stats = self._url_stats[url]
            if stats["count"] == 0:
                return url  # untested URL gets priority
            avg = stats["total_latency"] / stats["count"]
            if avg < best_avg:
                best_avg = avg
                best_url = url
        return best_url

    def record_latency(self, url: str, latency_ms: float):
        self._url_stats[url]["count"] += 1
        self._url_stats[url]["total_latency"] += latency_ms

    def get_stats(self) -> dict:
        result = {}
        for url, stats in self._url_stats.items():
            avg = stats["total_latency"] / stats["count"] if stats["count"] > 0 else 0
            result[url] = {"count": stats["count"], "avg_latency_ms": round(avg, 2)}
        return result


_balancer = LoadBalancer()


def pick_url(backend_name: str, urls: list[str], strategy: str = "round_robin") -> str:
    return _balancer.pick_url(backend_name, urls, strategy)


def record_latency(url: str, latency_ms: float):
    _balancer.record_latency(url, latency_ms)


def get_lb_stats() -> dict:
    return _balancer.get_stats()
