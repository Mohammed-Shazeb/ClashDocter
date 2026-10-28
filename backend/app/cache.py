"""Minimal thread-safe TTL cache (in-memory) for Qloo tag profiles."""
import threading
import time


class TTLCache:
    def __init__(self, ttl_seconds: float = 3600.0):
        self._ttl = ttl_seconds
        self._data: dict = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            value, expires = item
            if expires < time.monotonic():
                del self._data[key]
                return None
            return value

    def set(self, key, value):
        with self._lock:
            self._data[key] = (value, time.monotonic() + self._ttl)

    def clear(self):
        with self._lock:
            self._data.clear()
