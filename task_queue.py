# src/task_queue/__init__.py
"""
Task Queue - A powerful distributed task queue and job scheduler for Python.

This module provides a robust background job processing system with support for
delayed execution, cron scheduling, job dependencies, retries, and distributed
workers.

Version: 1.0.0
Author: Development Team
"""

from __future__ import annotations
import asyncio
import uuid
import time
import inspect
import pickle
import hashlib
import logging
import traceback
from typing import (
    Any, Callable, Dict, List, Optional, Type, Union,
    Awaitable, Generic, TypeVar, Set, Tuple, Coroutine
)
from dataclasses import dataclass, field
from enum import Enum, auto
from abc import ABC, abstractmethod
from functools import wraps, partial
from collections import defaultdict
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from heapq import heappush, heappop
import json
import re


T = TypeVar('T')
ResultT = TypeVar('ResultT')


class JobStatus(Enum):
    """Status of a job in the processing lifecycle."""
    PENDING = auto()
    SCHEDULED = auto()
    QUEUED = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    RETRYING = auto()
    CANCELLED = auto()
    TIMEOUT = auto()
    DEFERRED = auto()


class JobPriority(Enum):
    """Priority levels for job execution."""
    CRITICAL = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4
    BACKGROUND = 5


class RetryStrategy(Enum):
    """Strategies for retrying failed jobs."""
    IMMEDIATE = auto()
    LINEAR = auto()
    EXPONENTIAL = auto()
    FIBONACCI = auto()
    CUSTOM = auto()


@dataclass
class RetryPolicy:
    """
    Configuration for job retry behavior.
    
    Attributes:
        max_retries: Maximum number of retry attempts
        strategy: Retry delay strategy
        initial_delay: Initial delay between retries (seconds)
        max_delay: Maximum delay between retries (seconds)
        retry_on: Exception types to retry on (None = all)
        ignore_on: Exception types to never retry on
    """
    max_retries: int = 3
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    initial_delay: float = 1.0
    max_delay: float = 3600.0
    multiplier: float = 2.0
    retry_on: Optional[Set[Type[Exception]]] = None
    ignore_on: Optional[Set[Type[Exception]]] = None
    
    def should_retry(self, exception: Exception, attempt: int) -> bool:
        """Determine if job should be retried."""
        if attempt >= self.max_retries:
            return False
        
        if self.ignore_on:
            for exc_type in self.ignore_on:
                if isinstance(exception, exc_type):
                    return False
        
        if self.retry_on is None:
            return True
        
        return any(isinstance(exception, exc_type) for exc_type in self.retry_on)
    
    def get_delay(self, attempt: int) -> float:
        """Calculate delay for the given attempt number."""
        if self.strategy == RetryStrategy.IMMEDIATE:
            return 0
        elif self.strategy == RetryStrategy.LINEAR:
            delay = self.initial_delay * (attempt + 1)
        elif self.strategy == RetryStrategy.EXPONENTIAL:
            delay = self.initial_delay * (self.multiplier ** attempt)
        elif self.strategy == RetryStrategy.FIBONACCI:
            a, b = self.initial_delay, self.initial_delay
            for _ in range(attempt):
                a, b = b, a + b
            delay = b
        else:
            delay = self.initial_delay
        
        return min(delay, self.max_delay)


@dataclass
class JobResult(Generic[ResultT]):
    """
    Result of a job execution.
    
    Attributes:
        job_id: ID of the job
        status: Final status of the job
        result: Return value if successful
        error: Exception if failed
        started_at: When execution started
        completed_at: When execution completed
        attempts: Number of execution attempts
        worker_id: ID of worker that executed the job
    """
    job_id: str
    status: JobStatus
    result: Optional[ResultT] = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    traceback: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    attempts: int = 1
    worker_id: Optional[str] = None
    execution_time: Optional[float] = None
    
    @property
    def is_success(self) -> bool:
        """Check if job completed successfully."""
        return self.status == JobStatus.COMPLETED
    
    @property
    def is_failure(self) -> bool:
        """Check if job failed."""
        return self.status in (JobStatus.FAILED, JobStatus.TIMEOUT, JobStatus.CANCELLED)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary."""
        return {
            "job_id": self.job_id,
            "status": self.status.name,
            "result": self.result,
            "error": self.error,
            "error_type": self.error_type,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "attempts": self.attempts,
            "worker_id": self.worker_id,
            "execution_time": self.execution_time
        }


@dataclass
class JobContext:
    """
    Context information available during job execution.
    
    Provides access to job metadata and utilities for progress
    reporting and sub-task creation.
    """
    job_id: str
    job_name: str
    attempt: int
    queue_name: str
    worker_id: str
    enqueued_at: datetime
    started_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
    _progress_callback: Optional[Callable[[float, str], Awaitable[None]]] = None
    _cancel_event: Optional[asyncio.Event] = None
    
    async def report_progress(self, progress: float, message: str = "") -> None:
        """
        Report job progress.
        
        Args:
            progress: Progress value between 0 and 1
            message: Optional progress message
        """
        if self._progress_callback:
            await self._progress_callback(progress, message)
    
    @property
    def is_cancelled(self) -> bool:
        """Check if job has been cancelled."""
        return self._cancel_event.is_set() if self._cancel_event else False
    
    def check_cancelled(self) -> None:
        """Raise exception if job has been cancelled."""
        if self.is_cancelled:
            raise JobCancelledException(f"Job {self.job_id} was cancelled")


class JobCancelledException(Exception):
    """Raised when a job is cancelled during execution."""
    pass


class JobTimeoutException(Exception):
    """Raised when a job exceeds its timeout."""
    pass


class JobDefinition:
    """
    Defines a job type with its execution logic and configuration.
    
    JobDefinitions are registered with the task queue and can be
    invoked by name to create job instances.
    """
    
    def __init__(
        self,
        name: str,
        func: Callable,
        queue: str = "default",
        priority: JobPriority = JobPriority.NORMAL,
        timeout: Optional[float] = None,
        retry_policy: Optional[RetryPolicy] = None,
        rate_limit: Optional[Tuple[int, float]] = None,  # (count, period)
        unique: bool = False,
        unique_ttl: Optional[float] = None,
        tags: Optional[Set[str]] = None,
        description: str = ""
    ):
        """
        Initialize a job definition.
        
        Args:
            name: Unique name for the job type
            func: The function to execute
            queue: Queue to place jobs in
            priority: Default priority for jobs
            timeout: Maximum execution time in seconds
            retry_policy: Retry configuration
            rate_limit: Rate limit as (count, period_seconds)
            unique: If True, prevent duplicate jobs
            unique_ttl: TTL for uniqueness check
            tags: Tags for job categorization
            description: Human-readable description
        """
        self.name = name
        self.func = func
        self.queue = queue
        self.priority = priority
        self.timeout = timeout
        self.retry_policy = retry_policy or RetryPolicy()
        self.rate_limit = rate_limit
        self.unique = unique
        self.unique_ttl = unique_ttl
        self.tags = tags or set()
        self.description = description
        self._is_async = asyncio.iscoroutinefunction(func)
    
    def get_unique_key(self, args: tuple, kwargs: dict) -> str:
        """Generate a unique key for deduplication."""
        key_data = json.dumps({
            "name": self.name,
            "args": str(args),
            "kwargs": str(sorted(kwargs.items()))
        }, sort_keys=True)
        return hashlib.sha256(key_data.encode()).hexdigest()


@dataclass
class Job:
    """
    Represents a single job instance to be executed.
    
    Jobs are created from JobDefinitions and contain the specific
    arguments and scheduling information for execution.
    
    Example:
        >>> job = Job(
        ...     definition=my_job_definition,
        ...     args=("arg1",),
        ...     kwargs={"key": "value"},
        ...     priority=JobPriority.HIGH
        ... )
    """
    definition: JobDefinition
    args: tuple = ()
    kwargs: Dict[str, Any] = field(default_factory=dict)
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    priority: Optional[JobPriority] = None
    scheduled_at: Optional[datetime] = None
    delay: Optional[float] = None
    timeout: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    status: JobStatus = JobStatus.PENDING
    attempt: int = 0
    parent_job_id: Optional[str] = None
    dependency_ids: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        if self.priority is None:
            self.priority = self.definition.priority
        if self.timeout is None:
            self.timeout = self.definition.timeout
    
    @property
    def effective_priority(self) -> int:
        """Get numeric priority value for sorting."""
        return self.priority.value if self.priority else JobPriority.NORMAL.value
    
    @property
    def execute_at(self) -> datetime:
        """Calculate when the job should be executed."""
        if self.scheduled_at:
            return self.scheduled_at
        if self.delay:
            return self.created_at + timedelta(seconds=self.delay)
        return self.created_at
    
    def __lt__(self, other: 'Job') -> bool:
        """Compare jobs for priority queue ordering."""
        if self.effective_priority != other.effective_priority:
            return self.effective_priority < other.effective_priority
        return self.execute_at < other.execute_at
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize job to dictionary."""
        return {
            "job_id": self.job_id,
            "name": self.definition.name,
            "args": self.args,
            "kwargs": self.kwargs,
            "priority": self.priority.name if self.priority else None,
            "status": self.status.name,
            "attempt": self.attempt,
            "created_at": self.created_at.isoformat(),
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "metadata": self.metadata
        }


class CronSchedule:
    """
    Cron-like schedule parser and calculator.
    
    Supports standard cron expressions with extensions for
    seconds and special keywords.
    
    Format: second minute hour day_of_month month day_of_week
    
    Example:
        >>> schedule = CronSchedule("0 */5 * * * *")  # Every 5 minutes
        >>> next_run = schedule.next_run()
    """
    
    SPECIAL_EXPRESSIONS = {
        "@yearly": "0 0 0 1 1 *",
        "@annually": "0 0 0 1 1 *",
        "@monthly": "0 0 0 1 * *",
        "@weekly": "0 0 0 * * 0",
        "@daily": "0 0 0 * * *",
        "@midnight": "0 0 0 * * *",
        "@hourly": "0 0 * * * *",
        "@minutely": "0 * * * * *",
    }
    
    def __init__(self, expression: str):
        """
        Initialize with a cron expression.
        
        Args:
            expression: Cron expression string
        """
        self.original = expression
        
        # Handle special expressions
        if expression.startswith("@"):
            expression = self.SPECIAL_EXPRESSIONS.get(expression.lower(), expression)
        
        parts = expression.split()
        
        # Support both 5-part and 6-part expressions
        if len(parts) == 5:
            parts = ["0"] + parts  # Add seconds
        
        if len(parts) != 6:
            raise ValueError(f"Invalid cron expression: {expression}")
        
        self.second = self._parse_field(parts[0], 0, 59)
        self.minute = self._parse_field(parts[1], 0, 59)
        self.hour = self._parse_field(parts[2], 0, 23)
        self.day_of_month = self._parse_field(parts[3], 1, 31)
        self.month = self._parse_field(parts[4], 1, 12)
        self.day_of_week = self._parse_field(parts[5], 0, 6)
    
    def _parse_field(self, field: str, min_val: int, max_val: int) -> Set[int]:
        """Parse a single cron field into a set of values."""
        if field == "*":
            return set(range(min_val, max_val + 1))
        
        values = set()
        
        for part in field.split(","):
            if "/" in part:
                range_part, step = part.split("/")
                step = int(step)
                if range_part == "*":
                    start, end = min_val, max_val
                elif "-" in range_part:
                    start, end = map(int, range_part.split("-"))
                else:
                    start = int(range_part)
                    end = max_val
                values.update(range(start, end + 1, step))
            elif "-" in part:
                start, end = map(int, part.split("-"))
                values.update(range(start, end + 1))
            else:
                values.add(int(part))
        
        return values
    
    def next_run(self, after: Optional[datetime] = None) -> datetime:
        """
        Calculate the next run time.
        
        Args:
            after: Calculate next run after this time (default: now)
            
        Returns:
            Next scheduled run time
        """
        if after is None:
            after = datetime.utcnow()
        
        # Start from the next second
        current = after.replace(microsecond=0) + timedelta(seconds=1)
        
        # Iterate until we find a matching time (max 4 years)
        max_iterations = 365 * 4 * 24 * 60 * 60
        for _ in range(max_iterations):
            if (current.second in self.second and
                current.minute in self.minute and
                current.hour in self.hour and
                current.day in self.day_of_month and
                current.month in self.month and
                current.weekday() in self.day_of_week):
                return current
            current += timedelta(seconds=1)
        
        raise ValueError("Could not find next run time")
    
    def get_runs_between(
        self, 
        start: datetime, 
        end: datetime,
        max_runs: int = 1000
    ) -> List[datetime]:
        """Get all run times between two dates."""
        runs = []
        current = start
        
        while current < end and len(runs) < max_runs:
            next_run = self.next_run(current)
            if next_run >= end:
                break
            runs.append(next_run)
            current = next_run
        
        return runs


@dataclass
class ScheduledJob:
    """
    A job that runs on a schedule.
    
    Attributes:
        name: Unique name for the scheduled job
        job_definition: The job to run
        schedule: Cron schedule
        args: Arguments for the job
        kwargs: Keyword arguments for the job
        enabled: Whether the schedule is active
        last_run: When the job last ran
        next_run: When the job will next run
    """
    name: str
    job_definition: JobDefinition
    schedule: CronSchedule
    args: tuple = ()
    kwargs: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    run_count: int = 0
    error_count: int = 0
    
    def __post_init__(self):
        if self.next_run is None:
            self.update_next_run()
    
    def update_next_run(self) -> None:
        """Update the next run time based on schedule."""
        self.next_run = self.schedule.next_run()


class JobStore(ABC):
    """
    Abstract base class for job persistence.
    
    Implement this to store jobs in a database, Redis, or other
    persistent storage for durability and distributed processing.
    """
    
    @abstractmethod
    async def save_job(self, job: Job) -> None:
        """Save a job to the store."""
        pass
    
    @abstractmethod
    async def get_job(self, job_id: str) -> Optional[Job]:
        """Retrieve a job by ID."""
        pass
    
    @abstractmethod
    async def update_job_status(
        self, 
        job_id: str, 
        status: JobStatus,
        result: Optional[JobResult] = None
    ) -> None:
        """Update job status."""
        pass
    
    @abstractmethod
    async def get_pending_jobs(
        self, 
        queue: str,
        limit: int = 100
    ) -> List[Job]:
        """Get pending jobs for a queue."""
        pass
    
    @abstractmethod
    async def get_scheduled_jobs(
        self, 
        before: datetime,
        limit: int = 100
    ) -> List[Job]:
        """Get jobs scheduled to run before a given time."""
        pass
    
    @abstractmethod
    async def save_result(self, result: JobResult) -> None:
        """Save a job result."""
        pass
    
    @abstractmethod
    async def get_result(self, job_id: str) -> Optional[JobResult]:
        """Get a job result by job ID."""
        pass


class InMemoryJobStore(JobStore):
    """In-memory job store for testing and single-process deployments."""
    
    def __init__(self, max_results: int = 10000):
        self.max_results = max_results
        self._jobs: Dict[str, Job] = {}
        self._results: Dict[str, JobResult] = {}
        self._lock = asyncio.Lock()
    
    async def save_job(self, job: Job) -> None:
        async with self._lock:
            self._jobs[job.job_id] = job
    
    async def get_job(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)
    
    async def update_job_status(
        self, 
        job_id: str, 
        status: JobStatus,
        result: Optional[JobResult] = None
    ) -> None:
        async with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].status = status
            if result:
                await self.save_result(result)
    
    async def get_pending_jobs(self, queue: str, limit: int = 100) -> List[Job]:
        async with self._lock:
            jobs = [
                j for j in self._jobs.values()
                if j.definition.queue == queue and j.status == JobStatus.PENDING
            ]
            jobs.sort()
            return jobs[:limit]
    
    async def get_scheduled_jobs(self, before: datetime, limit: int = 100) -> List[Job]:
        async with self._lock:
            jobs = [
                j for j in self._jobs.values()
                if j.status == JobStatus.SCHEDULED and j.execute_at <= before
            ]
            jobs.sort(key=lambda j: j.execute_at)
            return jobs[:limit]
    
    async def save_result(self, result: JobResult) -> None:
        async with self._lock:
            self._results[result.job_id] = result
            
            # Trim old results
            if len(self._results) > self.max_results:
                oldest = sorted(
                    self._results.items(),
                    key=lambda x: x[1].completed_at or datetime.min
                )[:len(self._results) - self.max_results]
                for job_id, _ in oldest:
                    del self._results[job_id]
    
    async def get_result(self, job_id: str) -> Optional[JobResult]:
        return self._results.get(job_id)


class JobQueue:
    """
    Priority queue for pending jobs.
    
    Manages job ordering based on priority and scheduled time,
    with support for delayed execution.
    """
    
    def __init__(self, name: str):
        self.name = name
        self._queue: List[Tuple[float, int, Job]] = []  # (execute_at, priority, job)
        self._counter = 0
        self._lock = asyncio.Lock()
        self._not_empty = asyncio.Event()
    
    async def put(self, job: Job) -> None:
        """Add a job to the queue."""
        async with self._lock:
            execute_at = job.execute_at.timestamp()
            heappush(
                self._queue,
                (execute_at, job.effective_priority, self._counter, job)
            )
            self._counter += 1
            self._not_empty.set()
    
    async def get(self, timeout: Optional[float] = None) -> Optional[Job]:
        """
        Get the next job from the queue.
        
        Waits for a job to be ready for execution.
        """
        while True:
            async with self._lock:
                if not self._queue:
                    self._not_empty.clear()
                else:
                    execute_at, priority, counter, job = self._queue[0]
                    now = time.time()
                    
                    if execute_at <= now:
                        heappop(self._queue)
                        return job
                    
                    # Wait until job is ready
                    wait_time = execute_at - now
                    if timeout is not None:
                        wait_time = min(wait_time, timeout)
            
            try:
                if not self._queue:
                    await asyncio.wait_for(self._not_empty.wait(), timeout)
                else:
                    await asyncio.sleep(min(wait_time, 1.0))
            except asyncio.TimeoutError:
                return None
    
    async def size(self) -> int:
        """Get the number of jobs in the queue."""
        return len(self._queue)
    
    async def peek(self) -> Optional[Job]:
        """Peek at the next job without removing it."""
        async with self._lock:
            if self._queue:
                return self._queue[0][3]
            return None


class Worker:
    """
    Job execution worker.
    
    Workers pull jobs from queues and execute them, handling
    retries, timeouts, and result storage.
    
    Example:
        >>> worker = Worker(
        ...     task_queue=queue,
        ...     queues=["default", "high-priority"],
        ...     concurrency=4
        ... )
        >>> await worker.start()
    """
    
    def __init__(
        self,
        task_queue: 'TaskQueue',
        queues: List[str] = None,
        concurrency: int = 4,
        worker_id: Optional[str] = None,
        poll_interval: float = 1.0
    ):
        """
        Initialize the worker.
        
        Args:
            task_queue: The task queue to pull jobs from
            queues: List of queue names to process
            concurrency: Maximum concurrent jobs
            worker_id: Unique worker identifier
            poll_interval: Seconds between queue polls
        """
        self.task_queue = task_queue
        self.queues = queues or ["default"]
        self.concurrency = concurrency
        self.worker_id = worker_id or str(uuid.uuid4())[:8]
        self.poll_interval = poll_interval
        
        self._running = False
        self._current_jobs: Dict[str, asyncio.Task] = {}
        self._semaphore = asyncio.Semaphore(concurrency)
        self._logger = logging.getLogger(f"{__name__}.Worker.{self.worker_id}")
        self._stats = WorkerStats()
    
    async def start(self) -> None:
        """Start the worker."""
        self._running = True
        self._logger.info(f"Worker {self.worker_id} starting...")
        
        await asyncio.gather(
            self._process_loop(),
            self._heartbeat_loop()
        )
    
    async def stop(self, graceful: bool = True) -> None:
        """
        Stop the worker.
        
        Args:
            graceful: If True, wait for current jobs to complete
        """
        self._running = False
        
        if graceful and self._current_jobs:
            self._logger.info("Waiting for current jobs to complete...")
            await asyncio.gather(*self._current_jobs.values(), return_exceptions=True)
        
        self._logger.info(f"Worker {self.worker_id} stopped")
    
    async def _process_loop(self) -> None:
        """Main job processing loop."""
        while self._running:
            await self._semaphore.acquire()
            
            try:
                job = await self._get_next_job()
                if job:
                    task = asyncio.create_task(self._execute_job(job))
                    self._current_jobs[job.job_id] = task
                    task.add_done_callback(
                        lambda t, jid=job.job_id: self._job_completed(jid)
                    )
                else:
                    self._semaphore.release()
                    await asyncio.sleep(self.poll_interval)
            except Exception as e:
                self._logger.error(f"Error in process loop: {e}")
                self._semaphore.release()
                await asyncio.sleep(self.poll_interval)
    
    async def _get_next_job(self) -> Optional[Job]:
        """Get the next job from configured queues."""
        for queue_name in self.queues:
            queue = self.task_queue._get_queue(queue_name)
            job = await queue.get(timeout=0.1)
            if job:
                return job
        return None
    
    def _job_completed(self, job_id: str) -> None:
        """Callback when a job completes."""
        self._current_jobs.pop(job_id, None)
        self._semaphore.release()
    
    async def _execute_job(self, job: Job) -> JobResult:
        """Execute a single job."""
        started_at = datetime.utcnow()
        job.status = JobStatus.RUNNING
        job.attempt += 1
        
        self._logger.info(f"Executing job {job.job_id} ({job.definition.name})")
        self._stats.jobs_started += 1
        
        # Create context
        context = JobContext(
            job_id=job.job_id,
            job_name=job.definition.name,
            attempt=job.attempt,
            queue_name=job.definition.queue,
            worker_id=self.worker_i