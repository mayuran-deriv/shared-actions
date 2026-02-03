# src/cache_manager/__init__.py
"""
Cache Manager - A powerful multi-backend caching system for Python.

This module provides a unified caching interface with support for multiple
backends, cache invalidation strategies, distributed caching, and cache
warming capabilities.

Version: 1.0.0
Author: Development Team
"""

from __future__ import annotations
import asyncio
import hashlib
import pickle
import time
import json
import zlib
import threading
from typing import (
    Any, Callable, Dict, List, Optional, Type, Union,
    Awaitable, Generic, TypeVar, Set, Tuple, Iterator
)
from dataclasses import dataclass, field
from enum import Enum, auto
from abc import ABC, abstractmethod
from functools import wraps
from collections import OrderedDict
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
import logging
import weakref


T = TypeVar('T')
KeyT = TypeVar('KeyT', bound=str)


class EvictionPolicy(Enum):
    """Cache eviction policies."""
    LRU = auto()      # Least Recently Used
    LFU = auto()      # Least Frequently Used
    FIFO = auto()     # First In First Out
    TTL = auto()      # Time To Live based
    RANDOM = auto()   # Random eviction
    ARC = auto()      # Adaptive Replacement Cache


class CacheEvent(Enum):
    """Events emitted by the cache system."""
    HIT = auto()
    MISS = auto()
    SET = auto()
    DELETE = auto()
    EXPIRE = auto()
    EVICT = auto()
    CLEAR = auto()
    INVALIDATE = auto()


class SerializationFormat(Enum):
    """Supported serialization formats."""
    PICKLE = "pickle"
    JSON = "json"
    MSGPACK = "msgpack"
    RAW = "raw"


@dataclass
class CacheStats:
    """
    Statistics about cache performance.
    
    Attributes:
        hits: Number of cache hits
        misses: Number of cache misses
        sets: Number of set operations
        deletes: Number of delete operations
        evictions: Number of evicted items
        expirations: Number of expired items
        size: Current number of items in cache
        memory_usage: Estimated memory usage in bytes
    """
    hits: int = 0
    misses: int = 0
    sets: int = 0
    deletes: int = 0
    evictions: int = 0
    expirations: int = 0
    size: int = 0
    memory_usage: int = 0
    
    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0
    
    @property
    def miss_rate(self) -> float:
        """Calculate cache miss rate."""
        return 1.0 - self.hit_rate
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert stats to dictionary."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "sets": self.sets,
            "deletes": self.deletes,
            "evictions": self.evictions,
            "expirations": self.expirations,
            "size": self.size,
            "memory_usage": self.memory_usage,
            "hit_rate": self.hit_rate,
            "miss_rate": self.miss_rate
        }
    
    def reset(self) -> None:
        """Reset all statistics."""
        self.hits = 0
        self.misses = 0
        self.sets = 0
        self.deletes = 0
        self.evictions = 0
        self.expirations = 0


@dataclass
class CacheEntry(Generic[T]):
    """
    Represents a single cache entry with metadata.
    
    Attributes:
        key: The cache key
        value: The cached value
        created_at: When the entry was created
        expires_at: When the entry expires (None = never)
        last_accessed: When the entry was last accessed
        access_count: Number of times accessed
        size: Size of the entry in bytes
        tags: Tags for group invalidation
    """
    key: str
    value: T
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    size: int = 0
    tags: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_expired(self) -> bool:
        """Check if the entry has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at
    
    def touch(self) -> None:
        """Update access time and count."""
        self.last_accessed = time.time()
        self.access_count += 1
    
    @property
    def age(self) -> float:
        """Get age of entry in seconds."""
        return time.time() - self.created_at
    
    @property
    def ttl_remaining(self) -> Optional[float]:
        """Get remaining TTL in seconds."""
        if self.expires_at is None:
            return None
        remaining = self.expires_at - time.time()
        return max(0, remaining)


class Serializer(ABC):
    """Abstract base class for cache serializers."""
    
    @abstractmethod
    def serialize(self, value: Any) -> bytes:
        """Serialize a value to bytes."""
        pass
    
    @abstractmethod
    def deserialize(self, data: bytes) -> Any:
        """Deserialize bytes to a value."""
        pass


class PickleSerializer(Serializer):
    """Serializer using Python's pickle module."""
    
    def __init__(self, protocol: int = pickle.HIGHEST_PROTOCOL):
        self.protocol = protocol
    
    def serialize(self, value: Any) -> bytes:
        return pickle.dumps(value, protocol=self.protocol)
    
    def deserialize(self, data: bytes) -> Any:
        return pickle.loads(data)


class JSONSerializer(Serializer):
    """Serializer using JSON format."""
    
    def __init__(self, ensure_ascii: bool = False):
        self.ensure_ascii = ensure_ascii
    
    def serialize(self, value: Any) -> bytes:
        return json.dumps(value, ensure_ascii=self.ensure_ascii).encode('utf-8')
    
    def deserialize(self, data: bytes) -> Any:
        return json.loads(data.decode('utf-8'))


class CompressedSerializer(Serializer):
    """Wrapper serializer that adds compression."""
    
    def __init__(
        self, 
        inner_serializer: Serializer,
        compression_level: int = 6,
        min_size: int = 1024  # Only compress if larger than this
    ):
        self.inner = inner_serializer
        self.compression_level = compression_level
        self.min_size = min_size
    
    def serialize(self, value: Any) -> bytes:
        data = self.inner.serialize(value)
        if len(data) >= self.min_size:
            compressed = zlib.compress(data, self.compression_level)
            # Prefix with 'C' for compressed, 'R' for raw
            return b'C' + compressed
        return b'R' + data
    
    def deserialize(self, data: bytes) -> Any:
        marker = data[0:1]
        payload = data[1:]
        if marker == b'C':
            payload = zlib.decompress(payload)
        return self.inner.deserialize(payload)


class CacheBackend(ABC):
    """
    Abstract base class for cache backends.
    
    Implement this class to create custom cache storage backends
    such as Redis, Memcached, or database-backed caches.
    """
    
    @abstractmethod
    async def get(self, key: str) -> Optional[CacheEntry]:
        """Retrieve an entry from the cache."""
        pass
    
    @abstractmethod
    async def set(
        self, 
        key: str, 
        value: Any, 
        ttl: Optional[int] = None,
        tags: Optional[Set[str]] = None
    ) -> bool:
        """Store an entry in the cache."""
        pass
    
    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete an entry from the cache."""
        pass
    
    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if a key exists in the cache."""
        pass
    
    @abstractmethod
    async def clear(self) -> int:
        """Clear all entries. Returns count of cleared entries."""
        pass
    
    @abstractmethod
    async def keys(self, pattern: str = "*") -> List[str]:
        """Get keys matching a pattern."""
        pass
    
    @abstractmethod
    async def size(self) -> int:
        """Get the number of entries in the cache."""
        pass
    
    async def get_many(self, keys: List[str]) -> Dict[str, Any]:
        """Get multiple entries at once."""
        result = {}
        for key in keys:
            entry = await self.get(key)
            if entry and not entry.is_expired():
                result[key] = entry.value
        return result
    
    async def set_many(
        self, 
        items: Dict[str, Any], 
        ttl: Optional[int] = None
    ) -> Dict[str, bool]:
        """Set multiple entries at once."""
        results = {}
        for key, value in items.items():
            results[key] = await self.set(key, value, ttl)
        return results
    
    async def delete_many(self, keys: List[str]) -> int:
        """Delete multiple entries. Returns count of deleted entries."""
        count = 0
        for key in keys:
            if await self.delete(key):
                count += 1
        return count


class InMemoryBackend(CacheBackend):
    """
    In-memory cache backend with LRU/LFU eviction support.
    
    Features:
        - Multiple eviction policies
        - Memory limit enforcement
        - Tag-based invalidation
        - Automatic expiration cleanup
    """
    
    def __init__(
        self,
        max_size: int = 10000,
        max_memory: Optional[int] = None,  # bytes
        eviction_policy: EvictionPolicy = EvictionPolicy.LRU,
        cleanup_interval: float = 60.0
    ):
        self.max_size = max_size
        self.max_memory = max_memory
        self.eviction_policy = eviction_policy
        self.cleanup_interval = cleanup_interval
        
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._tags: Dict[str, Set[str]] = {}  # tag -> keys
        self._lock = asyncio.Lock()
        self._memory_usage = 0
        self._cleanup_task: Optional[asyncio.Task] = None
        self._stats = CacheStats()
    
    async def start_cleanup(self) -> None:
        """Start the background cleanup task."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    async def stop_cleanup(self) -> None:
        """Stop the background cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
    
    async def _cleanup_loop(self) -> None:
        """Background task to clean up expired entries."""
        while True:
            await asyncio.sleep(self.cleanup_interval)
            await self._remove_expired()
    
    async def _remove_expired(self) -> int:
        """Remove all expired entries."""
        async with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items() 
                if entry.is_expired()
            ]
            for key in expired_keys:
                self._remove_entry(key)
                self._stats.expirations += 1
            return len(expired_keys)
    
    def _remove_entry(self, key: str) -> None:
        """Remove an entry and update tags."""
        if key in self._cache:
            entry = self._cache[key]
            self._memory_usage -= entry.size
            for tag in entry.tags:
                if tag in self._tags:
                    self._tags[tag].discard(key)
            del self._cache[key]
    
    def _evict_if_needed(self) -> None:
        """Evict entries if cache is over capacity."""
        while len(self._cache) >= self.max_size:
            self._evict_one()
        
        if self.max_memory:
            while self._memory_usage > self.max_memory and self._cache:
                self._evict_one()
    
    def _evict_one(self) -> None:
        """Evict a single entry based on policy."""
        if not self._cache:
            return
        
        if self.eviction_policy == EvictionPolicy.LRU:
            # OrderedDict maintains insertion order; move_to_end on access
            key = next(iter(self._cache))
        elif self.eviction_policy == EvictionPolicy.LFU:
            key = min(self._cache.keys(), key=lambda k: self._cache[k].access_count)
        elif self.eviction_policy == EvictionPolicy.FIFO:
            key = next(iter(self._cache))
        elif self.eviction_policy == EvictionPolicy.TTL:
            # Evict entry with shortest remaining TTL
            key = min(
                self._cache.keys(),
                key=lambda k: self._cache[k].expires_at or float('inf')
            )
        else:
            # Random
            import random
            key = random.choice(list(self._cache.keys()))
        
        self._remove_entry(key)
        self._stats.evictions += 1
    
    async def get(self, key: str) -> Optional[CacheEntry]:
        async with self._lock:
            if key not in self._cache:
                self._stats.misses += 1
                return None
            
            entry = self._cache[key]
            
            if entry.is_expired():
                self._remove_entry(key)
                self._stats.expirations += 1
                self._stats.misses += 1
                return None
            
            entry.touch()
            
            # Move to end for LRU
            if self.eviction_policy == EvictionPolicy.LRU:
                self._cache.move_to_end(key)
            
            self._stats.hits += 1
            return entry
    
    async def set(
        self, 
        key: str, 
        value: Any, 
        ttl: Optional[int] = None,
        tags: Optional[Set[str]] = None
    ) -> bool:
        async with self._lock:
            # Calculate size
            try:
                size = len(pickle.dumps(value))
            except Exception:
                size = 0
            
            # Create entry
            expires_at = time.time() + ttl if ttl else None
            entry = CacheEntry(
                key=key,
                value=value,
                expires_at=expires_at,
                size=size,
                tags=tags or set()
            )
            
            # Remove old entry if exists
            if key in self._cache:
                self._remove_entry(key)
            
            # Evict if needed
            self._evict_if_needed()
            
            # Add new entry
            self._cache[key] = entry
            self._memory_usage += size
            
            # Update tags
            for tag in entry.tags:
                if tag not in self._tags:
                    self._tags[tag] = set()
                self._tags[tag].add(key)
            
            self._stats.sets += 1
            self._stats.size = len(self._cache)
            self._stats.memory_usage = self._memory_usage
            
            return True
    
    async def delete(self, key: str) -> bool:
        async with self._lock:
            if key not in self._cache:
                return False
            self._remove_entry(key)
            self._stats.deletes += 1
            self._stats.size = len(self._cache)
            return True
    
    async def exists(self, key: str) -> bool:
        async with self._lock:
            if key not in self._cache:
                return False
            if self._cache[key].is_expired():
                self._remove_entry(key)
                return False
            return True
    
    async def clear(self) -> int:
        async with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._tags.clear()
            self._memory_usage = 0
            self._stats.size = 0
            return count
    
    async def keys(self, pattern: str = "*") -> List[str]:
        import fnmatch
        async with self._lock:
            if pattern == "*":
                return list(self._cache.keys())
            return [k for k in self._cache.keys() if fnmatch.fnmatch(k, pattern)]
    
    async def size(self) -> int:
        return len(self._cache)
    
    async def invalidate_tag(self, tag: str) -> int:
        """Invalidate all entries with a specific tag."""
        async with self._lock:
            if tag not in self._tags:
                return 0
            keys = list(self._tags[tag])
            for key in keys:
                self._remove_entry(key)
            return len(keys)
    
    @property
    def stats(self) -> CacheStats:
        """Get cache statistics."""
        return self._stats


class TieredBackend(CacheBackend):
    """
    Multi-tier cache backend supporting L1/L2/L3 caching.
    
    Implements a hierarchy of cache backends where faster caches
    are checked first, and cache misses populate upper tiers.
    """
    
    def __init__(self, tiers: List[CacheBackend]):
        """
        Initialize with a list of backends from fastest to slowest.
        
        Args:
            tiers: List of cache backends (e.g., [memory, redis, database])
        """
        if not tiers:
            raise ValueError("At least one tier is required")
        self.tiers = tiers
    
    async def get(self, key: str) -> Optional[CacheEntry]:
        for i, tier in enumerate(self.tiers):
            entry = await tier.get(key)
            if entry and not entry.is_expired():
                # Populate upper tiers
                for upper_tier in self.tiers[:i]:
                    await upper_tier.set(
                        key, 
                        entry.value, 
                        ttl=int(entry.ttl_remaining) if entry.ttl_remaining else None,
                        tags=entry.tags
                    )
                return entry
        return None
    
    async def set(
        self, 
        key: str, 
        value: Any, 
        ttl: Optional[int] = None,
        tags: Optional[Set[str]] = None
    ) -> bool:
        # Write to all tiers
        results = await asyncio.gather(
            *[tier.set(key, value, ttl, tags) for tier in self.tiers],
            return_exceptions=True
        )
        return all(r is True for r in results)
    
    async def delete(self, key: str) -> bool:
        results = await asyncio.gather(
            *[tier.delete(key) for tier in self.tiers],
            return_exceptions=True
        )
        return any(r is True for r in results)
    
    async def exists(self, key: str) -> bool:
        for tier in self.tiers:
            if await tier.exists(key):
                return True
        return False
    
    async def clear(self) -> int:
        results = await asyncio.gather(*[tier.clear() for tier in self.tiers])
        return max(results)
    
    async def keys(self, pattern: str = "*") -> List[str]:
        all_keys: Set[str] = set()
        for tier in self.tiers:
            keys = await tier.keys(pattern)
            all_keys.update(keys)
        return list(all_keys)
    
    async def size(self) -> int:
        # Return size of largest tier
        sizes = await asyncio.gather(*[tier.size() for tier in self.tiers])
        return max(sizes)


class CacheEventListener(ABC):
    """Abstract base class for cache event listeners."""
    
    @abstractmethod
    async def on_event(
        self, 
        event: CacheEvent, 
        key: str, 
        value: Any = None,
        metadata: Dict[str, Any] = None
    ) -> None:
        """Handle a cache event."""
        pass


class LoggingListener(CacheEventListener):
    """Listener that logs cache events."""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
    
    async def on_event(
        self, 
        event: CacheEvent, 
        key: str, 
        value: Any = None,
        metadata: Dict[str, Any] = None
    ) -> None:
        self.logger.debug(f"Cache {event.name}: {key}")


class CacheNamespace:
    """
    Provides namespaced access to a cache.
    
    Useful for organizing cache keys and avoiding collisions
    between different parts of an application.
    """
    
    def __init__(self, cache: 'Cache', namespace: str):
        self._cache = cache
        self._namespace = namespace
    
    def _prefixed_key(self, key: str) -> str:
        return f"{self._namespace}:{key}"
    
    async def get(self, key: str, default: T = None) -> Optional[T]:
        return await self._cache.get(self._prefixed_key(key), default)
    
    async def set(
        self, 
        key: str, 
        value: Any, 
        ttl: Optional[int] = None,
        tags: Optional[Set[str]] = None
    ) -> bool:
        prefixed_tags = {f"{self._namespace}:{t}" for t in (tags or set())}
        return await self._cache.set(self._prefixed_key(key), value, ttl, prefixed_tags)
    
    async def delete(self, key: str) -> bool:
        return await self._cache.delete(self._prefixed_key(key))
    
    async def clear(self) -> int:
        """Clear all keys in this namespace."""
        keys = await self._cache.keys(f"{self._namespace}:*")
        return await self._cache.delete_many(keys)


class Cache:
    """
    Main cache class providing a high-level caching interface.
    
    The Cache class wraps a backend and provides additional features
    like namespacing, event listeners, decorators, and cache warming.
    
    Example:
        >>> cache = Cache(InMemoryBackend(max_size=1000))
        >>> await cache.set("user:123", {"name": "John"}, ttl=3600)
        >>> user = await cache.get("user:123")
        >>> print(user["name"])
        John
    
    Features:
        - Multiple backend support
        - Namespace isolation
        - Event listeners for monitoring
        - Function result caching decorator
        - Cache warming utilities
        - Tag-based invalidation
    """
    
    def __init__(
        self,
        backend: CacheBackend,
        serializer: Optional[Serializer] = None,
        default_ttl: Optional[int] = None,
        key_prefix: str = ""
    ):
        """
        Initialize the Cache.
        
        Args:
            backend: The cache backend to use
            serializer: Optional serializer for values
            default_ttl: Default TTL for entries (seconds)
            key_prefix: Prefix added to all keys
        """
        self._backend = backend
        self._serializer = serializer
        self._default_ttl = default_ttl
        self._key_prefix = key_prefix
        self._listeners: List[CacheEventListener] = []
        self._lock = asyncio.Lock()
    
    def _make_key(self, key: str) -> str:
        """Generate the full key with prefix."""
        if self._key_prefix:
            return f"{self._key_prefix}:{key}"
        return key
    
    async def _emit_event(
        self, 
        event: CacheEvent, 
        key: str, 
        value: Any = None,
        metadata: Dict[str, Any] = None
    ) -> None:
        """Emit an event to all listeners."""
        for listener in self._listeners:
            try:
                await listener.on_event(event, key, value, metadata)
            except Exception:
                pass  # Don't let listener errors affect cache operations
    
    def add_listener(self, listener: CacheEventListener) -> None:
        """Add an event listener."""
        self._listeners.append(listener)
    
    def remove_listener(self, listener: CacheEventListener) -> None:
        """Remove an event listener."""
        self._listeners.remove(listener)
    
    def namespace(self, name: str) -> CacheNamespace:
        """
        Get a namespaced view of the cache.
        
        Args:
            name: Namespace name
            
        Returns:
            CacheNamespace for isolated access
        """
        return CacheNamespace(self, name)
    
    async def get(self, key: str, default: T = None) -> Optional[T]:
        """
        Get a value from the cache.
        
        Args:
            key: The cache key
            default: Default value if key not found
            
        Returns:
            The cached value or default
        """
        full_key = self._make_key(key)
        entry = await self._backend.get(full_key)
        
        if entry is None:
            await self._emit_event(CacheEvent.MISS, key)
            return default
        
        await self._emit_event(CacheEvent.HIT, key, entry.value)
        return entry.value
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        tags: Optional[Set[str]] = None
    ) -> bool:
        """
        Set a value in the cache.
        
        Args:
            key: The cache key
            value: The value to cache
            ttl: Time-to-live in seconds (None = use default)
            tags: Tags for group invalidation
            
        Returns:
            True if successful
        """
        full_key = self._make_key(key)
        effective_ttl = ttl if ttl is not None else self._default_ttl
        
        result = await self._backend.set(full_key, value, effective_ttl, tags)
        
        if result:
            await self._emit_event(CacheEvent.SET, key, value, {"ttl": effective_ttl})
        
        return result
    
    async def delete(self, key: str) -> bool:
        """
        Delete a value from the cache.
        
        Args:
            key: The cache key
            
        Returns:
            True if the key existed and was deleted
        """
        full_key = self._make_key(key)
        result = await self._backend.delete(full_key)
        
        if result:
            await self._emit_event(CacheEvent.DELETE, key)
        
        return result
    
    async def exists(self, key: str) -> bool:
        """Check if a key exists in the cache."""
        return await self._backend.exists(self._make_key(key))
    
    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Awaitable[T]],
        ttl: Optional[int] = None,
        tags: Optional[Set[str]] = None
    ) -> T:
        """
        Get a value from cache, or compute and cache it.
        
        Args:
            key: The cache key
            factory: Async function to compute the value if not cached
            ttl: Time-to-live in seconds
            tags: Tags for group invalidation
            
        Returns:
            The cached or computed value
        """
        value = await self.get(key)
        if value is not None:
            return value
        
        # Compute value
        value = await factory()
        await self.set(key, value, ttl, tags)
        return value
    
    async def get_many(self, keys: List[str]) -> Dict[str, Any]:
        """Get multiple values at once."""
        full_keys = [self._make_key(k) for k in keys]
        results = await self._backend.get_many(full_keys)
        
        # Remove prefix from keys in result
        prefix_len = len(self._key_prefix) + 1 if self._key_prefix else 0
        return {k[prefix_len:]: v for k, v in results.items()}
    
    async def set_many(
        self,
        items: Dict[str, Any],
        ttl: Optional[int] = None
    ) -> Dict[str, bool]:
        """Set multiple values at once."""
        full_items = {self._make_key(k): v for k, v in items.items()}
        results = await self._backend.set_many(full_items, ttl or self._default_ttl)
        
        prefix_len = len(self._key_prefix) + 1 if self._key_prefix else 0
        return {k[prefix_len:]: v for k, v in results.items()}
    
    async def delete_many(self, keys: List[str]) -> int:
        """Delete multiple keys at once."""
        full_keys = [self._make_key(k) for k in keys]
        return await self._backend.delete_many(full_keys)
    
    async def clear(self) -> int:
        """Clear all cache entries."""
        count = await self._backend.clear()
        await self._emit_event(CacheEvent.CLEAR, "*", metadata={"count": count})
        return count
    
    async def keys(self, pattern: str = "*") -> List[str]:
        """Get keys matching a pattern."""
        full_pattern = self._make_key(pattern)
        keys = await self._backend.keys(full_pattern)
        
        prefix_len = len(self._key_prefix) + 1 if self._key_prefix else 0
        return [k[prefix_len:] for k in keys]
    
    async def invalidate_tag(self, tag: str) -> int:
        """
        Invalidate all entries with a specific tag.
        
        Args:
            tag: The tag to invalidate
            
        Returns:
            Number of entries invalidated
        """
        if hasattr(self._backend, 'invalidate_tag'):
            count = await self._backend.invalidate_tag(tag)
            await self._emit_event(
                CacheEvent.INVALIDATE, 
                f"tag:{tag}", 
                metadata={"count": count}
            )