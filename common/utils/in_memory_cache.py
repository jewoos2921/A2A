import threading
import time
from typing import Any, Dict, Optional


class InMemoryCache:
    _instance: Optional["InMemoryCache"] = None
    _lock: threading.Lock = threading.Lock()
    _initialized: bool = False

    def __new__(cls) -> "InMemoryCache":
        if cls._instance is None:
            with cls._lock:
                if not cls._initialized:
                    cls._instance = super().__new__(cls)

        return cls._instance

    def __init__(self):
        if not self._initialized:
            with self._lock:
                if not self._initialized:
                    self._cache_data: Dict[str, Dict[str, Any]] = {}
                    self._ttl: Dict[str, float] = {}
                    self._data_lock: threading.Lock = threading.Lock()
                    self._initialized = True

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        with self._data_lock:
            self._cache_data[key] = value
            if ttl is not None:
                self._ttl[key] = time.time() + ttl
            else:
                if key in self._ttl:
                    del self._ttl[key]

    def get(self, key: str, default: Any = None) -> Any:
        with self._data_lock:
            if key in self._ttl \
                    and time.time() > self._ttl[key]:
                del self._cache_data[key]
                del self._ttl[key]
                return default

            return self._cache_data.get(key, default)

    def delete(self, key: str):
        with self._data_lock:
            if key in self._cache_data:
                del self._cache_data[key]
                if key in self._ttl:
                    del self._ttl[key]
                return True
            return False

    def clear(self) -> bool:
        with self._data_lock:
            self._cache_data.clear()
            self._ttl.clear()
            return True
        return False
