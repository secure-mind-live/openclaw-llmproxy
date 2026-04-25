import hashlib
import json
import time
from collections import OrderedDict

from proxy.config import CACHE_TTL_S, CACHE_MAX_ENTRIES


class ResponseCache:
    def __init__(self, max_entries: int = CACHE_MAX_ENTRIES, ttl_s: int = CACHE_TTL_S):
        self._cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._max_entries = max_entries
        self._ttl_s = ttl_s
        self._hits = 0
        self._misses = 0

    @staticmethod
    def make_key(model: str, messages: list[dict]) -> str:
        raw = json.dumps({"model": model, "messages": messages}, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def is_cacheable(request_body: dict | None) -> bool:
        if not request_body or not isinstance(request_body, dict):
            return False
        if request_body.get("stream") is True:
            return False
        if (request_body.get("temperature") or 0) > 0:
            return False
        if "messages" not in request_body or "model" not in request_body:
            return False
        return True

    def get(self, key: str) -> dict | None:
        if key not in self._cache:
            self._misses += 1
            return None
        ts, entry = self._cache[key]
        if time.time() - ts > self._ttl_s:
            del self._cache[key]
            self._misses += 1
            return None
        self._cache.move_to_end(key)
        self._hits += 1
        return entry

    def put(self, key: str, response_body: dict, status_code: int, headers: dict):
        if status_code != 200:
            return
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = (time.time(), {
            "body": response_body,
            "status_code": status_code,
            "headers": headers,
        })
        while len(self._cache) > self._max_entries:
            self._cache.popitem(last=False)

    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 4) if total > 0 else 0.0,
        }


_cache = ResponseCache()


def get(key: str) -> dict | None:
    return _cache.get(key)


def put(key: str, response_body: dict, status_code: int, headers: dict):
    _cache.put(key, response_body, status_code, headers)


def make_key(model: str, messages: list) -> str:
    return ResponseCache.make_key(model, messages)


def is_cacheable(request_body: dict | None) -> bool:
    return ResponseCache.is_cacheable(request_body)


def cache_stats() -> dict:
    return _cache.stats()
