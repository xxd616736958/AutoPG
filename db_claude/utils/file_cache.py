"""
File state LRU cache + context memoization.
Claude Code equivalents: FileStateCache (LRU 100 entries, 25MB), memoize on getGitStatus/getUserContext.
"""
import os, functools, time
from typing import Optional
from collections import OrderedDict


# ── File state LRU cache (Claude Code: FileStateCache) ──

class FileStateCache:
    """LRU cache for file contents. Path-normalized keys, 100 entries, 25MB max."""

    def __init__(self, max_entries: int = 100, max_size_bytes: int = 25 * 1024 * 1024):
        self._max_entries = max_entries
        self._max_size = max_size_bytes
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._total_size = 0
        self.hits = 0
        self.misses = 0

    def _normalize(self, path: str) -> str:
        return os.path.realpath(os.path.expanduser(path))

    def get(self, path: str) -> Optional[str]:
        key = self._normalize(path)
        if key in self._cache:
            self._cache.move_to_end(key)
            self.hits += 1
            return self._cache[key]["content"]
        self.misses += 1
        return None

    def set(self, path: str, content: str):
        key = self._normalize(path)
        size = len(content.encode("utf-8"))
        # Evict old entries if needed
        while self._total_size + size > self._max_size and self._cache:
            _, old = self._cache.popitem(last=False)
            self._total_size -= old["size"]
        while len(self._cache) >= self._max_entries:
            _, old = self._cache.popitem(last=False)
            self._total_size -= old["size"]
        self._cache[key] = {"content": content, "size": size, "timestamp": time.time()}
        self._cache.move_to_end(key)
        self._total_size += size

    def has(self, path: str) -> bool:
        return self._normalize(path) in self._cache

    def stats(self) -> dict:
        return {"entries": len(self._cache), "size_bytes": self._total_size,
                "hits": self.hits, "misses": self.misses, "hit_rate": self.hits / max(1, self.hits + self.misses)}


# ── Context memoization (Claude Code: lodash memoize on getUserContext/getSystemContext) ──

_memo_store: dict[str, tuple[float, any]] = {}
MEMO_TTL = 5.0  # 5 second TTL — long enough for a turn, short enough to catch changes


def memoized(ttl: float = MEMO_TTL):
    """Decorator: memoize async function result for `ttl` seconds."""
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            key = f"{fn.__name__}:{args}:{sorted(kwargs.items())}"
            now = time.time()
            if key in _memo_store:
                ts, val = _memo_store[key]
                if now - ts < ttl:
                    return val
            result = await fn(*args, **kwargs)
            _memo_store[key] = (now, result)
            return result
        return wrapper
    return deco


def clear_memo():
    _memo_store.clear()
