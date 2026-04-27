"""Prometheus-compatible metrics endpoint.

Exposes /metrics in Prometheus text format for scraping by
Prometheus, Grafana Agent, Datadog, etc.
"""

import time
from collections import defaultdict
from threading import Lock

from fastapi import APIRouter

router = APIRouter()

_lock = Lock()
_counters = defaultdict(int)
_histograms: dict[str, list[float]] = defaultdict(list)


def inc(name: str, labels: dict | None = None, value: int = 1):
    key = _key(name, labels)
    with _lock:
        _counters[key] += value


def observe(name: str, value: float, labels: dict | None = None):
    key = _key(name, labels)
    with _lock:
        _histograms[key].append(value)


def _key(name: str, labels: dict | None) -> str:
    if not labels:
        return name
    parts = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return f"{name}{{{parts}}}"


def _format_prometheus() -> str:
    lines = []
    with _lock:
        # Counters
        seen_counters = set()
        for key, val in sorted(_counters.items()):
            name = key.split("{")[0]
            if name not in seen_counters:
                lines.append(f"# TYPE {name} counter")
                seen_counters.add(name)
            lines.append(f"{key} {val}")

        # Histograms as summaries
        seen_histograms = set()
        for key, values in sorted(_histograms.items()):
            name = key.split("{")[0]
            if name not in seen_histograms:
                lines.append(f"# TYPE {name} summary")
                seen_histograms.add(name)
            if values:
                s = sorted(values)
                count = len(s)
                total = sum(s)
                p50 = s[int(count * 0.5)] if count > 0 else 0
                p99 = s[int(count * 0.99)] if count > 0 else 0
                base = key.split("{")[0]
                labels = key[len(base):]
                lines.append(f'{base}_count{labels} {count}')
                lines.append(f'{base}_sum{labels} {total:.2f}')
                lines.append(f'{base}_p50{labels} {p50:.2f}')
                lines.append(f'{base}_p99{labels} {p99:.2f}')

    return "\n".join(lines) + "\n"


@router.get("/metrics")
async def metrics():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(_format_prometheus(), media_type="text/plain; version=0.0.4")


# ── Convenience functions for the proxy ──

def record_request(backend: str, model: str | None, status_code: int,
                   latency_ms: float, cache_hit: bool = False):
    labels = {"backend": backend, "model": model or "unknown"}
    inc("llmproxy_requests_total", labels)
    inc(f"llmproxy_status_{status_code}_total", {"backend": backend})
    observe("llmproxy_request_duration_ms", latency_ms, labels)

    if cache_hit:
        inc("llmproxy_cache_hits_total", {"backend": backend})
    else:
        inc("llmproxy_cache_misses_total", {"backend": backend})

    if status_code >= 400:
        inc("llmproxy_errors_total", labels)


def record_tokens(backend: str, model: str | None,
                  prompt: int | None, completion: int | None):
    labels = {"backend": backend, "model": model or "unknown"}
    if prompt:
        inc("llmproxy_prompt_tokens_total", labels, prompt)
    if completion:
        inc("llmproxy_completion_tokens_total", labels, completion)


def record_spend(backend: str, cost_usd: float | None):
    if cost_usd and cost_usd > 0:
        inc("llmproxy_spend_usd_total", {"backend": backend}, int(cost_usd * 1_000_000))


def record_security_event(event_type: str, backend: str):
    inc("llmproxy_security_events_total", {"type": event_type, "backend": backend})
