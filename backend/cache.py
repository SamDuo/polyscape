"""Redis caching layer for SHAP values with Parquet fallback.

Provides fast per-hex SHAP lookups via Redis, with an in-memory
dictionary fallback when Redis is unavailable.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Optional

import pandas as pd

try:
    import redis
except ImportError:
    redis = None  # type: ignore[assignment]

from backend.model import FEATURE_COLUMNS

# Redis key prefix for SHAP values
REDIS_KEY_PREFIX = "polyscape:shap:"
# TTL for cached values (24 hours)
REDIS_TTL_SECONDS = 86400


class SHAPCache:
    """Cache for per-hex SHAP values backed by Redis or in-memory dict.

    On initialization, attempts to connect to Redis. If Redis is
    unavailable, falls back to an in-memory dictionary loaded from
    the SHAP Parquet cache file.
    """

    def __init__(self, redis_url: Optional[str] = None) -> None:
        """Initialize the SHAP cache.

        Parameters
        ----------
        redis_url : str | None
            Redis connection URL (e.g., "redis://localhost:6379/0").
            If None or connection fails, falls back to in-memory cache.
        """
        self._redis_client: Optional[object] = None
        self._memory_cache: dict[str, dict] = {}
        self._using_redis = False

        if redis_url and redis is not None:
            try:
                self._redis_client = redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=3,
                )
                # Test connection
                self._redis_client.ping()  # type: ignore[union-attr]
                self._using_redis = True
                print(f"SHAPCache: connected to Redis at {redis_url}")
            except Exception as exc:
                print(f"SHAPCache: Redis unavailable ({exc}), using memory fallback")
                self._redis_client = None
                self._using_redis = False
        else:
            if redis is None and redis_url:
                print("SHAPCache: redis package not installed, using memory fallback")
            print("SHAPCache: using in-memory cache")

    @property
    def using_redis(self) -> bool:
        """Whether the cache is backed by Redis."""
        return self._using_redis

    @property
    def size(self) -> int:
        """Number of cached hex entries."""
        if self._using_redis and self._redis_client is not None:
            try:
                keys = self._redis_client.keys(f"{REDIS_KEY_PREFIX}*")  # type: ignore[union-attr]
                return len(keys)
            except Exception:
                return len(self._memory_cache)
        return len(self._memory_cache)

    def load_from_parquet(self, path: str | Path) -> int:
        """Bulk load SHAP values from a Parquet cache file.

        Parameters
        ----------
        path : str | Path
            Path to shap_cache.parquet.

        Returns
        -------
        int
            Number of hex entries loaded.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"SHAP cache file not found: {path}")

        df = pd.read_parquet(path)
        loaded = 0

        for _, row in df.iterrows():
            h3_index = str(row["h3_index"])
            entry: dict = {
                "base_value": float(row.get("base_value", 0.0)),
            }
            for col in FEATURE_COLUMNS:
                shap_col = f"shap_{col}"
                if shap_col in row.index:
                    val = row[shap_col]
                    entry[col] = float(val) if pd.notna(val) else 0.0
                else:
                    entry[col] = 0.0

            if self._using_redis and self._redis_client is not None:
                try:
                    key = f"{REDIS_KEY_PREFIX}{h3_index}"
                    self._redis_client.setex(  # type: ignore[union-attr]
                        key, REDIS_TTL_SECONDS, json.dumps(entry)
                    )
                except Exception:
                    # Fall back to memory for this entry
                    self._memory_cache[h3_index] = entry
            else:
                self._memory_cache[h3_index] = entry
            loaded += 1

        print(
            f"SHAPCache: loaded {loaded} hexes from {path} "
            f"({'Redis' if self._using_redis else 'memory'})"
        )
        return loaded

    def get(self, h3_index: str) -> Optional[dict]:
        """Retrieve SHAP values for a single hex.

        Parameters
        ----------
        h3_index : str
            H3 cell index.

        Returns
        -------
        dict | None
            Dict with base_value and per-feature SHAP values, or None if
            not found.
        """
        if self._using_redis and self._redis_client is not None:
            try:
                key = f"{REDIS_KEY_PREFIX}{h3_index}"
                raw = self._redis_client.get(key)  # type: ignore[union-attr]
                if raw is not None:
                    return json.loads(raw)  # already a fresh dict from deserialization
            except Exception:
                pass
            # Fall through to memory cache
            entry = self._memory_cache.get(h3_index)
            return copy.copy(entry) if entry is not None else None
        entry = self._memory_cache.get(h3_index)
        return copy.copy(entry) if entry is not None else None

    def get_batch(self, h3_indices: list[str]) -> dict[str, dict]:
        """Retrieve SHAP values for multiple hexes.

        Parameters
        ----------
        h3_indices : list[str]
            List of H3 cell indices.

        Returns
        -------
        dict[str, dict]
            Mapping from h3_index to SHAP value dicts. Missing indices
            are omitted from the result.
        """
        results: dict[str, dict] = {}

        if self._using_redis and self._redis_client is not None:
            try:
                keys = [f"{REDIS_KEY_PREFIX}{idx}" for idx in h3_indices]
                values = self._redis_client.mget(keys)  # type: ignore[union-attr]
                for idx, val in zip(h3_indices, values):
                    if val is not None:
                        results[idx] = json.loads(val)
                return results
            except Exception:
                pass

        # Memory fallback
        for idx in h3_indices:
            entry = self._memory_cache.get(idx)
            if entry is not None:
                results[idx] = entry

        return results

    def clear(self) -> None:
        """Clear all cached SHAP values."""
        if self._using_redis and self._redis_client is not None:
            try:
                keys = self._redis_client.keys(f"{REDIS_KEY_PREFIX}*")  # type: ignore[union-attr]
                if keys:
                    self._redis_client.delete(*keys)  # type: ignore[union-attr]
            except Exception:
                pass
        self._memory_cache.clear()
        print("SHAPCache: cleared")


if __name__ == "__main__":
    import sys

    cache_path = sys.argv[1] if len(sys.argv) > 1 else "data/models/shap_cache.parquet"
    redis_url = sys.argv[2] if len(sys.argv) > 2 else None

    cache = SHAPCache(redis_url=redis_url)

    try:
        loaded = cache.load_from_parquet(cache_path)
        print(f"Loaded {loaded} entries, cache size: {cache.size}")

        # Test retrieval
        if cache.size > 0:
            # Get a sample key from memory cache
            sample_key = next(iter(cache._memory_cache)) if cache._memory_cache else None
            if sample_key:
                result = cache.get(sample_key)
                print(f"\nSample entry for {sample_key}:")
                if result:
                    for k, v in result.items():
                        print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
    except FileNotFoundError as exc:
        print(f"Cache file not found: {exc}")
        print("Run the pipeline first to generate SHAP cache.")
