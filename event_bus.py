# src/event_bus/__init__.py
"""
Event Bus - A powerful asynchronous event-driven messaging system for Python.

This module provides a robust publish-subscribe pattern implementation with
support for async handlers, event filtering, middleware, and dead letter queues.

Version: 1.0.0
Author: Development Team
"""

from __future__ import annotations
import asyncio
import uuid
import time
import logging
from typing import (
    Any, Callable, Dict, List, Optional, Type, Union,
    Awaitable, Generic, TypeVar, Set
)
from dataclasses import dataclass, field
from enum import Enum, auto
from abc import ABC, abstractmethod
from functools import wraps
from collections import defaultdict
from datetime import datetime, timedelta
import traceback
import json
import hashlib


# Type variables for generic support
T = TypeVar('T')
EventDataT = TypeVar('EventDataT')


class EventPriority(Enum):
    """Priority levels for event processing."""
    CRITICAL = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4
    BACKGROUND = 5


class EventStatus(Enum):
    """Status of an event in the processing lifecycle."""
    PENDING = auto()
    PROCESSING = auto()
    COMPLETED = auto()
    FAILED = auto()
    RETRYING = auto()
    DEAD_LETTER = auto()
    CANCELLED = auto()


class DeliveryMode(Enum):
    """Event delivery modes."""
    AT_LEAST_ONCE = auto()
    AT_MOST_ONCE = auto()
    EXACTLY_ONCE = auto()


@dataclass
class EventMetadata:
    """
    Metadata associated with an event.
    
    Attributes:
        event_id: Unique identifier for the event
        timestamp: When the event was created
        source: Origin of the event
        correlation_id: ID linking related events
        causation_id: ID of the event that caused this one
        retry_count: Number of delivery attempts
        priority: Event priority level
        ttl: Time-to-live in seconds
        headers: Custom headers/attributes
    """
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str = ""
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    retry_count: int = 0
    priority: EventPriority = EventPriority.NORMAL
    ttl: Optional[int] = None
    headers: Dict[str, Any] = field(default_factory=dict)
    
    def is_expired(self) -> bool:
        """Check if the event has exceeded its TTL."""
        if self.ttl is None:
            return False
        elapsed = (datetime.utcnow() - self.timestamp).total_seconds()
        return elapsed > self.ttl
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary."""
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "retry_count": self.retry_count,
            "priority": self.priority.name,
            "ttl": self.ttl,
            "headers": self.headers
        }


@dataclass
class Event(Generic[EventDataT]):
    """
    Base event class representing a message in the event bus.
    
    Events are the fundamental unit of communication in the event bus system.
    They carry data and metadata about something that happened in the system.
    
    Example:
        >>> event = Event(
        ...     name="user.created",
        ...     data={"user_id": 123, "email": "user@example.com"},
        ...     metadata=EventMetadata(source="user-service")
        ... )
    """
    name: str
    data: EventDataT
    metadata: EventMetadata = field(default_factory=EventMetadata)
    status: EventStatus = EventStatus.PENDING
    
    def __post_init__(self):
        if not self.name:
            raise ValueError("Event name cannot be empty")
    
    def with_correlation(self, correlation_id: str) -> Event[EventDataT]:
        """Create a copy of the event with a correlation ID."""
        self.metadata.correlation_id = correlation_id
        return self
    
    def derive(self, name: str, data: Any) -> Event:
        """Create a derived event with causation tracking."""
        return Event(
            name=name,
            data=data,
            metadata=EventMetadata(
                correlation_id=self.metadata.correlation_id or self.metadata.event_id,
                causation_id=self.metadata.event_id,
                source=self.metadata.source
            )
        )
    
    def to_json(self) -> str:
        """Serialize event to JSON string."""
        return json.dumps({
            "name": self.name,
            "data": self.data,
            "metadata": self.metadata.to_dict(),
            "status": self.status.name
        })
    
    @classmethod
    def from_json(cls, json_str: str) -> Event:
        """Deserialize event from JSON string."""
        obj = json.loads(json_str)
        metadata = EventMetadata(
            event_id=obj["metadata"]["event_id"],
            timestamp=datetime.fromisoformat(obj["metadata"]["timestamp"]),
            source=obj["metadata"]["source"],
            correlation_id=obj["metadata"]["correlation_id"],
            causation_id=obj["metadata"]["causation_id"],
            retry_count=obj["metadata"]["retry_count"],
            priority=EventPriority[obj["metadata"]["priority"]],
            ttl=obj["metadata"]["ttl"],
            headers=obj["metadata"]["headers"]
        )
        return cls(
            name=obj["name"],
            data=obj["data"],
            metadata=metadata,
            status=EventStatus[obj["status"]]
        )


@dataclass
class Subscription:
    """
    Represents a subscription to events.
    
    Attributes:
        handler: The callback function to invoke
        event_pattern: Pattern to match event names (supports wildcards)
        filter_fn: Optional function to filter events
        priority: Handler priority for ordering
        max_concurrent: Maximum concurrent executions
        timeout: Handler timeout in seconds
    """
    handler: Callable[[Event], Awaitable[None]]
    event_pattern: str
    subscription_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    filter_fn: Optional[Callable[[Event], bool]] = None
    priority: int = 0
    max_concurrent: int = 10
    timeout: Optional[float] = 30.0
    active: bool = True
    
    def matches(self, event_name: str) -> bool:
        """Check if this subscription matches an event name."""
        pattern_parts = self.event_pattern.split('.')
        name_parts = event_name.split('.')
        
        if len(pattern_parts) > len(name_parts) and '#' not in pattern_parts:
            return False
        
        for i, part in enumerate(pattern_parts):
            if part == '#':
                return True
            if part == '*':
                continue
            if i >= len(name_parts) or part != name_parts[i]:
                return False
        
        return len(pattern_parts) == len(name_parts) or pattern_parts[-1] == '#'
    
    def should_handle(self, event: Event) -> bool:
        """Determine if this subscription should handle the event."""
        if not self.active:
            return False
        if not self.matches(event.name):
            return False
        if self.filter_fn and not self.filter_fn(event):
            return False
        return True


class Middleware(ABC):
    """
    Abstract base class for event bus middleware.
    
    Middleware can intercept and modify events before and after
    they are processed by handlers.
    """
    
    @abstractmethod
    async def before_publish(self, event: Event) -> Optional[Event]:
        """
        Called before an event is published.
        
        Args:
            event: The event being published
            
        Returns:
            The modified event, or None to cancel publishing
        """
        pass
    
    @abstractmethod
    async def after_publish(self, event: Event, success: bool) -> None:
        """
        Called after an event has been published.
        
        Args:
            event: The event that was published
            success: Whether publishing was successful
        """
        pass
    
    @abstractmethod
    async def before_handle(self, event: Event, subscription: Subscription) -> Optional[Event]:
        """
        Called before a handler processes an event.
        
        Args:
            event: The event being handled
            subscription: The subscription handling the event
            
        Returns:
            The modified event, or None to skip this handler
        """
        pass
    
    @abstractmethod
    async def after_handle(
        self, 
        event: Event, 
        subscription: Subscription, 
        error: Optional[Exception]
    ) -> None:
        """
        Called after a handler has processed an event.
        
        Args:
            event: The event that was handled
            subscription: The subscription that handled it
            error: Any exception raised during handling
        """
        pass


class LoggingMiddleware(Middleware):
    """Middleware that logs all event activity."""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
    
    async def before_publish(self, event: Event) -> Optional[Event]:
        self.logger.info(f"Publishing event: {event.name} [{event.metadata.event_id}]")
        return event
    
    async def after_publish(self, event: Event, success: bool) -> None:
        status = "succeeded" if success else "failed"
        self.logger.info(f"Publish {status}: {event.name} [{event.metadata.event_id}]")
    
    async def before_handle(self, event: Event, subscription: Subscription) -> Optional[Event]:
        self.logger.debug(
            f"Handling event: {event.name} with subscription {subscription.subscription_id}"
        )
        return event
    
    async def after_handle(
        self, 
        event: Event, 
        subscription: Subscription, 
        error: Optional[Exception]
    ) -> None:
        if error:
            self.logger.error(f"Handler error for {event.name}: {error}")
        else:
            self.logger.debug(f"Handler completed for {event.name}")


class MetricsMiddleware(Middleware):
    """Middleware that collects metrics about event processing."""
    
    def __init__(self):
        self.published_count: Dict[str, int] = defaultdict(int)
        self.handled_count: Dict[str, int] = defaultdict(int)
        self.error_count: Dict[str, int] = defaultdict(int)
        self.processing_times: Dict[str, List[float]] = defaultdict(list)
        self._start_times: Dict[str, float] = {}
    
    async def before_publish(self, event: Event) -> Optional[Event]:
        return event
    
    async def after_publish(self, event: Event, success: bool) -> None:
        if success:
            self.published_count[event.name] += 1
    
    async def before_handle(self, event: Event, subscription: Subscription) -> Optional[Event]:
        key = f"{event.metadata.event_id}:{subscription.subscription_id}"
        self._start_times[key] = time.time()
        return event
    
    async def after_handle(
        self, 
        event: Event, 
        subscription: Subscription, 
        error: Optional[Exception]
    ) -> None:
        key = f"{event.metadata.event_id}:{subscription.subscription_id}"
        if key in self._start_times:
            elapsed = time.time() - self._start_times[key]
            self.processing_times[event.name].append(elapsed)
            del self._start_times[key]
        
        self.handled_count[event.name] += 1
        if error:
            self.error_count[event.name] += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get collected metrics."""
        stats = {}
        for event_name in set(self.published_count.keys()) | set(self.handled_count.keys()):
            times = self.processing_times.get(event_name, [])
            stats[event_name] = {
                "published": self.published_count.get(event_name, 0),
                "handled": self.handled_count.get(event_name, 0),
                "errors": self.error_count.get(event_name, 0),
                "avg_processing_time": sum(times) / len(times) if times else 0,
                "max_processing_time": max(times) if times else 0,
            }
        return stats


@dataclass
class RetryPolicy:
    """
    Configuration for event retry behavior.
    
    Attributes:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries
        exponential_base: Base for exponential backoff
        retry_on: Exception types to retry on (None = all)
    """
    max_retries: int = 3
    initial_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    retry_on: Optional[Set[Type[Exception]]] = None
    
    def should_retry(self, error: Exception, attempt: int) -> bool:
        """Determine if a retry should be attempted."""
        if attempt >= self.max_retries:
            return False
        if self.retry_on is None:
            return True
        return any(isinstance(error, exc_type) for exc_type in self.retry_on)
    
    def get_delay(self, attempt: int) -> float:
        """Calculate delay for the given attempt number."""
        delay = self.initial_delay * (self.exponential_base ** attempt)
        return min(delay, self.max_delay)


class DeadLetterQueue:
    """
    Storage for events that failed processing after all retries.
    
    Dead letter queues allow inspection and replay of failed events
    for debugging and recovery purposes.
    """
    
    def __init__(self, max_size: int = 10000):
        self.max_size = max_size
        self._events: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()
    
    async def add(self, event: Event, error: Exception, handler_id: str) -> None:
        """Add a failed event to the dead letter queue."""
        async with self._lock:
            entry = {
                "event": event,
                "error": str(error),
                "error_type": type(error).__name__,
                "traceback": traceback.format_exc(),
                "handler_id": handler_id,
                "failed_at": datetime.utcnow().isoformat()
            }
            self._events.append(entry)
            
            # Trim if exceeding max size
            if len(self._events) > self.max_size:
                self._events = self._events[-self.max_size:]
    
    async def get_all(self) -> List[Dict[str, Any]]:
        """Get all events in the dead letter queue."""
        async with self._lock:
            return list(self._events)
    
    async def get_by_event_name(self, event_name: str) -> List[Dict[str, Any]]:
        """Get failed events by event name."""
        async with self._lock:
            return [e for e in self._events if e["event"].name == event_name]
    
    async def clear(self) -> int:
        """Clear all events from the queue. Returns count of cleared events."""
        async with self._lock:
            count = len(self._events)
            self._events.clear()
            return count
    
    async def replay(self, event_bus: 'EventBus', event_id: Optional[str] = None) -> int:
        """
        Replay events from the dead letter queue.
        
        Args:
            event_bus: The event bus to replay events to
            event_id: Specific event ID to replay (None = all)
            
        Returns:
            Number of events replayed
        """
        async with self._lock:
            to_replay = self._events
            if event_id:
                to_replay = [e for e in self._events if e["event"].metadata.event_id == event_id]
            
            count = 0
            for entry in to_replay:
                event = entry["event"]
                event.status = EventStatus.PENDING
                event.metadata.retry_count = 0
                await event_bus.publish(event)
                count += 1
            
            # Remove replayed events
            if event_id:
                self._events = [e for e in self._events if e["event"].metadata.event_id != event_id]
            else:
                self._events.clear()
            
            return count


class EventStore(ABC):
    """
    Abstract base class for event persistence.
    
    Implement this to add durable event storage for replay
    and audit purposes.
    """
    
    @abstractmethod
    async def save(self, event: Event) -> None:
        """Save an event to the store."""
        pass
    
    @abstractmethod
    async def get(self, event_id: str) -> Optional[Event]:
        """Retrieve an event by ID."""
        pass
    
    @abstractmethod
    async def get_by_correlation(self, correlation_id: str) -> List[Event]:
        """Get all events with a correlation ID."""
        pass
    
    @abstractmethod
    async def get_by_name(
        self, 
        event_name: str, 
        since: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Event]:
        """Get events by name with optional time filter."""
        pass


class InMemoryEventStore(EventStore):
    """In-memory implementation of EventStore for testing and development."""
    
    def __init__(self, max_events: int = 100000):
        self.max_events = max_events
        self._events: Dict[str, Event] = {}
        self._by_name: Dict[str, List[str]] = defaultdict(list)
        self._by_correlation: Dict[str, List[str]] = defaultdict(list)
        self._lock = asyncio.Lock()
    
    async def save(self, event: Event) -> None:
        async with self._lock:
            event_id = event.metadata.event_id
            self._events[event_id] = event
            self._by_name[event.name].append(event_id)
            
            if event.metadata.correlation_id:
                self._by_correlation[event.metadata.correlation_id].append(event_id)
            
            # Trim old events if needed
            if len(self._events) > self.max_events:
                oldest_ids = list(self._events.keys())[:len(self._events) - self.max_events]
                for old_id in oldest_ids:
                    del self._events[old_id]
    
    async def get(self, event_id: str) -> Optional[Event]:
        return self._events.get(event_id)
    
    async def get_by_correlation(self, correlation_id: str) -> List[Event]:
        event_ids = self._by_correlation.get(correlation_id, [])
        return [self._events[eid] for eid in event_ids if eid in self._events]
    
    async def get_by_name(
        self, 
        event_name: str, 
        since: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Event]:
        event_ids = self._by_name.get(event_name, [])
        events = [self._events[eid] for eid in event_ids if eid in self._events]
        
        if since:
            events = [e for e in events if e.metadata.timestamp >= since]
        
        return events[-limit:]


class EventBus:
    """
    Main event bus class for publishing and subscribing to events.
    
    The EventBus is the central hub for event-driven communication.
    It manages subscriptions, routes events to handlers, and provides
    features like middleware, retries, and dead letter queues.
    
    Example:
        >>> bus = EventBus()
        >>> 
        >>> @bus.on("user.created")
        >>> async def handle_user_created(event: Event):
        ...     print(f"User created: {event.data}")
        >>> 
        >>> await bus.publish(Event(name="user.created", data={"id": 1}))
    
    Features:
        - Wildcard subscriptions (user.* or user.#)
        - Async handlers with concurrency control
        - Middleware pipeline
        - Automatic retries with exponential backoff
        - Dead letter queue for failed events
        - Event persistence and replay
    """
    
    def __init__(
        self,
        retry_policy: Optional[RetryPolicy] = None,
        dead_letter_queue: Optional[DeadLetterQueue] = None,
        event_store: Optional[EventStore] = None,
        delivery_mode: DeliveryMode = DeliveryMode.AT_LEAST_ONCE
    ):
        """
        Initialize the EventBus.
        
        Args:
            retry_policy: Policy for retrying failed handlers
            dead_letter_queue: Queue for storing failed events
            event_store: Optional persistent storage for events
            delivery_mode: Delivery guarantee mode
        """
        self._subscriptions: List[Subscription] = []
        self._middlewares: List[Middleware] = []
        self._retry_policy = retry_policy or RetryPolicy()
        self._dlq = dead_letter_queue or DeadLetterQueue()
        self._event_store = event_store
        self._delivery_mode = delivery_mode
        self._running = False
        self._processed_ids: Set[str] = set()  # For exactly-once delivery
        self._lock = asyncio.Lock()
        self._logger = logging.getLogger(__name__)
    
    def use(self, middleware: Middleware) -> 'EventBus':
        """
        Add middleware to the event bus.
        
        Args:
            middleware: The middleware to add
            
        Returns:
            Self for method chaining
        """
        self._middlewares.append(middleware)
        return self
    
    def subscribe(
        self,
        event_pattern: str,
        handler: Callable[[Event], Awaitable[None]],
        filter_fn: Optional[Callable[[Event], bool]] = None,
        priority: int = 0,
        max_concurrent: int = 10,
        timeout: Optional[float] = 30.0
    ) -> Subscription:
        """
        Subscribe a handler to events matching a pattern.
        
        Args:
            event_pattern: Pattern to match (supports * and # wildcards)
            handler: Async function to handle events
            filter_fn: Optional filter function
            priority: Handler priority (lower = higher priority)
            max_concurrent: Max concurrent handler executions
            timeout: Handler timeout in seconds
            
        Returns:
            The created Subscription
        """
        subscription = Subscription(
            handler=handler,
            event_pattern=event_pattern,
            filter_fn=filter_fn,
            priority=priority,
            max_concurrent=max_concurrent,
            timeout=timeout
        )
        self._subscriptions.append(subscription)
        self._subscriptions.sort(key=lambda s: s.priority)
        return subscription
    
    def on(
        self,
        event_pattern: str,
        filter_fn: Optional[Callable[[Event], bool]] = None,
        priority: int = 0,
        max_concurrent: int = 10,
        timeout: Optional[float] = 30.0
    ) -> Callable:
        """
        Decorator for subscribing handlers to events.
        
        Example:
            >>> @bus.on("user.*")
            >>> async def handle_user_events(event: Event):
            ...     print(event.name)
        """
        def decorator(func: Callable[[Event], Awaitable[None]]) -> Callable:
            self.subscribe(
                event_pattern=event_pattern,
                handler=func,
                filter_fn=filter_fn,
                priority=priority,
                max_concurrent=max_concurrent,
                timeout=timeout
            )
            return func
        return decorator
    
    def unsubscribe(self, subscription_id: str) -> bool:
        """
        Remove a subscription by ID.
        
        Args:
            subscription_id: ID of the subscription to remove
            
        Returns:
            True if subscription was found and removed
        """
        for i, sub in enumerate(self._subscriptions):
            if sub.subscription_id == subscription_id:
                self._subscriptions.pop(i)
                return True
        return False
    
    async def publish(self, event: Event) -> bool:
        """
        Publish an event to all matching subscribers.
        
        Args:
            event: The event to publish
            
        Returns:
            True if event was successfully published
        """
        # Exactly-once check
        if self._delivery_mode == DeliveryMode.EXACTLY_ONCE:
            if event.metadata.event_id in self._processed_ids:
                return True
        
        # Check TTL
        if event.metadata.is_expired():
            self._logger.warning(f"Event {event.metadata.event_id} expired, skipping")
            return False
        
        # Run before_publish middleware
        for middleware in self._middlewares:
            result = await middleware.before_publish(event)
            if result is None:
                return False
            event = result
        
        # Store event if persistence enabled
        if self._event_store:
            await self._event_store.save(event)
        
        # Find matching subscriptions
        matching_subs = [s for s in self._subscriptions if s.should_handle(event)]
        
        if not matching_subs:
            self._logger.debug(f"No subscribers for event: {event.name}")
            await self._run_after_publish_middleware(event, True)
            return True
        
        # Process handlers
        event.status = EventStatus.PROCESSING
        success = True
        
        for subscription in matching_subs:
            handler_success = await self._execute_handler(event, subscription)
            if not handler_success:
                success = False
        
        event.status = EventStatus.COMPLETED if success else EventStatus.FAILED
        
        # Mark as processed for exactly-once
        if self._delivery_mode == DeliveryMode.EXACTLY_ONCE:
            self._processed_ids.add(event.metadata.event_id)
        
        await self._run_after_publish_middleware(event, success)
        return success
    
    async def _execute_handler(self, event: Event, subscription: Subscription) -> bool:
        """Execute a single handler with retry logic."""
        # Run before_handle middleware
        modified_event = event
        for middleware in self._middlewares:
            result = await middleware.before_handle(modified_event, subscription)
            if result is None:
                return True  # Skip this handler
            modified_event = result
        
        last_error: Optional[Exception] = None
        
        for attempt in range(self._retry_policy.max_retries + 1):
            try:
                if subscription.timeout:
                    await asyncio.wait_for(
                        subscription.handler(modified_event),
                        timeout=subscription.timeout
                    )
                else:
                    await subscription.handler(modified_event)
                
                # Success - run after_handle middleware
                for middleware in self._middlewares:
                    await middleware.after_handle(modified_event, subscription, None)
                
                return True
                
            except asyncio.TimeoutError as e:
                last_error = e
                self._logger.warning(
                    f"Handler timeout for {event.name} (attempt {attempt + 1})"
                )
            except Exception as e:
                last_error = e
                self._logger.error(
                    f"Handler error for {event.name}: {e} (attempt {attempt + 1})"
                )
            
            # Check if we should retry
            if not self._retry_policy.should_retry(last_error, attempt + 1):
                break
            
            # Wait before retry
            delay = self._retry_policy.get_delay(attempt)
            event.status = EventStatus.RETRYING
            event.metadata.retry_count = attempt + 1
            await asyncio.sleep(delay)
        
        # All retries exhausted - add to DLQ
        event.status = EventStatus.DEAD_LETTER
        await self._dlq.add(event, last_error, subscription.subscription_id)
        
        # Run after_handle middleware with error
        for middleware in self._middlewares:
            await middleware.after_handle(modified_event, subscription, last_error)
        
        return False
    
    async def _run_after_publish_middleware(self, event: Event, success: bool) -> None:
        """Run after_publish middleware for all middleware."""
        for middleware in self._middlewares:
            await middleware.after_publish(event, success)
    
    async def emit(self, name: str, data: Any, **metadata_kwargs) -> bool:
        """
        Convenience method to create and publish an event.
        
        Args:
            name: Event name
            data: Event data
            **metadata_kwargs: Additional metadata fields
            
        Returns:
            True if event was published successfully
        """
        metadata = EventMetadata(**metadata_kwargs)
        event = Event(name=name, data=data, metadata=metadata)
        return await self.publish(event)
    
    @property
    def dead_letter_queue(self) -> DeadLetterQueue:
        """Access the dead letter queue."""
        return self._dlq
    
    @property
    def subscriptions(self) -> List[Subscription]:
        """Get list of active subscriptions."""
        return list(self._subscriptions)
    
    def get_subscription_count(self, event_pattern: Optional[str] = None) -> int:
        """Get count of subscriptions, optionally filtered by pattern."""
        if event_pattern is None:
            return len(self._subscriptions)
        return sum(1 for s in self._subscriptions if s.event_pattern == event_pattern)


class EventAggregator:
    """
    Aggregates multiple events into batches for efficient processing.
    
    Useful for scenarios where you want to process events in batches
    rather than individually, such as bulk database inserts.
    """
    
    def __init__(
        self,
        event_bus: EventBus,
        event_pattern: str,
        batch_size: int = 100,
        flush_interval: float = 5.0,
        handler: Callable[[List[Event]], Awaitable[None]] = None
    ):
        self.event_bus = event_bus
        self.event_pattern = event_pattern
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self._handler = handler
        self._buffer: List[Event] = []
        self._lock = asyncio.Lock()
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self) -> None:
        """Start the aggregator."""
        self._running = True
        self.event_bus.subscribe(
            self.event_pattern,
            self._on_event,
            priority=-100  # High priority to intercept events
        )