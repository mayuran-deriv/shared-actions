# src/feature_flags/__init__.py
"""
Feature Flags - A comprehensive feature flag and experimentation platform.

This module provides a complete feature management system with support for
gradual rollouts, A/B testing, user segmentation, remote configuration,
and real-time flag updates.

Version: 1.0.0
Author: Development Team
License: MIT
"""

from __future__ import annotations
import asyncio
import hashlib
import json
import time
import random
import threading
import logging
from typing import (
    Any, Callable, Dict, List, Optional, Type, Union,
    Awaitable, Generic, TypeVar, Set, Tuple, Literal,
    Protocol, runtime_checkable, overload
)
from dataclasses import dataclass, field
from enum import Enum, auto
from abc import ABC, abstractmethod
from functools import wraps
from collections import defaultdict
from datetime import datetime, timedelta
from contextlib import contextmanager, asynccontextmanager
import re
import uuid
import copy


T = TypeVar('T')
FlagValueT = TypeVar('FlagValueT', bool, str, int, float, dict, list)


class FlagType(Enum):
    """
    Types of feature flags supported by the system.
    
    Attributes:
        BOOLEAN: Simple on/off toggle
        STRING: String value flag for configuration
        INTEGER: Numeric integer flag
        FLOAT: Numeric float flag
        JSON: Complex JSON object flag
    """
    BOOLEAN = "boolean"
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    JSON = "json"


class FlagStatus(Enum):
    """Status of a feature flag."""
    ACTIVE = auto()
    INACTIVE = auto()
    ARCHIVED = auto()
    SCHEDULED = auto()


class RolloutStrategy(Enum):
    """
    Strategies for rolling out feature flags.
    
    Attributes:
        ALL: Enable for all users
        NONE: Disable for all users
        PERCENTAGE: Enable for percentage of users
        USER_LIST: Enable for specific users
        GROUP_LIST: Enable for specific groups
        GRADUAL: Gradually increase percentage over time
        RING: Deploy in rings (internal -> beta -> GA)
        CUSTOM: Custom targeting rules
    """
    ALL = auto()
    NONE = auto()
    PERCENTAGE = auto()
    USER_LIST = auto()
    GROUP_LIST = auto()
    GRADUAL = auto()
    RING = auto()
    CUSTOM = auto()


class EvaluationReason(Enum):
    """Reason for a flag evaluation result."""
    DEFAULT = "default"
    TARGETING_MATCH = "targeting_match"
    PERCENTAGE_ROLLOUT = "percentage_rollout"
    USER_TARGETED = "user_targeted"
    GROUP_TARGETED = "group_targeted"
    RULE_MATCH = "rule_match"
    PREREQUISITE_FAILED = "prerequisite_failed"
    FLAG_DISABLED = "flag_disabled"
    FLAG_NOT_FOUND = "flag_not_found"
    ERROR = "error"


@dataclass
class EvaluationContext:
    """
    Context for evaluating feature flags.
    
    Contains all information about the user/request that can be used
    for targeting and segmentation decisions.
    
    Attributes:
        user_id: Unique identifier for the user
        anonymous_id: Anonymous identifier for non-logged-in users
        email: User's email address
        groups: Groups/segments the user belongs to
        attributes: Custom user attributes for targeting
        ip_address: User's IP address
        user_agent: Browser/client user agent
        country: User's country code
        locale: User's locale/language
        app_version: Application version
        platform: Platform (web, ios, android, etc.)
        timestamp: Evaluation timestamp
    
    Example:
        >>> context = EvaluationContext(
        ...     user_id="user-123",
        ...     email="user@example.com",
        ...     groups=["beta-testers", "premium"],
        ...     attributes={"plan": "enterprise", "signup_date": "2024-01-01"}
        ... )
    """
    user_id: Optional[str] = None
    anonymous_id: Optional[str] = None
    email: Optional[str] = None
    groups: List[str] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    country: Optional[str] = None
    locale: Optional[str] = None
    app_version: Optional[str] = None
    platform: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def key(self) -> str:
        """Get unique key for this context (user_id or anonymous_id)."""
        return self.user_id or self.anonymous_id or str(uuid.uuid4())
    
    def get_attribute(self, name: str, default: Any = None) -> Any:
        """Get an attribute value with optional default."""
        return self.attributes.get(name, default)
    
    def has_group(self, group: str) -> bool:
        """Check if context belongs to a group."""
        return group in self.groups
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert context to dictionary."""
        return {
            "user_id": self.user_id,
            "anonymous_id": self.anonymous_id,
            "email": self.email,
            "groups": self.groups,
            "attributes": self.attributes,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "country": self.country,
            "locale": self.locale,
            "app_version": self.app_version,
            "platform": self.platform,
            "timestamp": self.timestamp.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EvaluationContext':
        """Create context from dictionary."""
        data = data.copy()
        if "timestamp" in data and isinstance(data["timestamp"], str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)


@dataclass
class EvaluationResult(Generic[FlagValueT]):
    """
    Result of a feature flag evaluation.
    
    Contains the evaluated value along with metadata about why
    that value was returned.
    
    Attributes:
        value: The evaluated flag value
        reason: Why this value was returned
        flag_key: The flag that was evaluated
        variation_id: ID of the variation returned
        is_default: Whether default value was used
        metadata: Additional evaluation metadata
    """
    value: FlagValueT
    reason: EvaluationReason
    flag_key: str
    variation_id: Optional[str] = None
    is_default: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    evaluation_time_ms: float = 0.0
    
    @property
    def is_enabled(self) -> bool:
        """Check if a boolean flag is enabled."""
        return bool(self.value)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary."""
        return {
            "value": self.value,
            "reason": self.reason.value,
            "flag_key": self.flag_key,
            "variation_id": self.variation_id,
            "is_default": self.is_default,
            "metadata": self.metadata,
            "evaluation_time_ms": self.evaluation_time_ms
        }


class Operator(Enum):
    """Operators for targeting rule conditions."""
    EQUALS = "eq"
    NOT_EQUALS = "neq"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    MATCHES_REGEX = "matches_regex"
    GREATER_THAN = "gt"
    GREATER_THAN_OR_EQUAL = "gte"
    LESS_THAN = "lt"
    LESS_THAN_OR_EQUAL = "lte"
    IN_LIST = "in"
    NOT_IN_LIST = "not_in"
    SEMVER_EQUALS = "semver_eq"
    SEMVER_GREATER = "semver_gt"
    SEMVER_LESS = "semver_lt"
    IS_SET = "is_set"
    IS_NOT_SET = "is_not_set"


@dataclass
class Condition:
    """
    A single condition in a targeting rule.
    
    Conditions compare an attribute value against a target value
    using a specified operator.
    
    Attributes:
        attribute: The attribute to evaluate (e.g., "country", "plan")
        operator: The comparison operator
        value: The value to compare against
        negate: Whether to negate the condition result
    
    Example:
        >>> condition = Condition(
        ...     attribute="country",
        ...     operator=Operator.IN_LIST,
        ...     value=["US", "CA", "UK"]
        ... )
    """
    attribute: str
    operator: Operator
    value: Any
    negate: bool = False
    
    def evaluate(self, context: EvaluationContext) -> bool:
        """
        Evaluate this condition against a context.
        
        Args:
            context: The evaluation context
            
        Returns:
            True if condition matches, False otherwise
        """
        # Get attribute value from context
        if self.attribute == "user_id":
            actual = context.user_id
        elif self.attribute == "email":
            actual = context.email
        elif self.attribute == "country":
            actual = context.country
        elif self.attribute == "platform":
            actual = context.platform
        elif self.attribute == "app_version":
            actual = context.app_version
        elif self.attribute == "groups":
            actual = context.groups
        else:
            actual = context.get_attribute(self.attribute)
        
        result = self._compare(actual, self.value)
        return not result if self.negate else result
    
    def _compare(self, actual: Any, expected: Any) -> bool:
        """Perform the comparison operation."""
        if self.operator == Operator.IS_SET:
            return actual is not None
        if self.operator == Operator.IS_NOT_SET:
            return actual is None
        
        if actual is None:
            return False
        
        if self.operator == Operator.EQUALS:
            return actual == expected
        elif self.operator == Operator.NOT_EQUALS:
            return actual != expected
        elif self.operator == Operator.CONTAINS:
            return expected in str(actual)
        elif self.operator == Operator.NOT_CONTAINS:
            return expected not in str(actual)
        elif self.operator == Operator.STARTS_WITH:
            return str(actual).startswith(expected)
        elif self.operator == Operator.ENDS_WITH:
            return str(actual).endswith(expected)
        elif self.operator == Operator.MATCHES_REGEX:
            return bool(re.match(expected, str(actual)))
        elif self.operator == Operator.GREATER_THAN:
            return actual > expected
        elif self.operator == Operator.GREATER_THAN_OR_EQUAL:
            return actual >= expected
        elif self.operator == Operator.LESS_THAN:
            return actual < expected
        elif self.operator == Operator.LESS_THAN_OR_EQUAL:
            return actual <= expected
        elif self.operator == Operator.IN_LIST:
            if isinstance(actual, list):
                return bool(set(actual) & set(expected))
            return actual in expected
        elif self.operator == Operator.NOT_IN_LIST:
            if isinstance(actual, list):
                return not bool(set(actual) & set(expected))
            return actual not in expected
        elif self.operator == Operator.SEMVER_EQUALS:
            return self._compare_semver(actual, expected) == 0
        elif self.operator == Operator.SEMVER_GREATER:
            return self._compare_semver(actual, expected) > 0
        elif self.operator == Operator.SEMVER_LESS:
            return self._compare_semver(actual, expected) < 0
        
        return False
    
    def _compare_semver(self, v1: str, v2: str) -> int:
        """Compare semantic versions. Returns -1, 0, or 1."""
        def parse_version(v: str) -> Tuple[int, ...]:
            parts = re.sub(r'[^0-9.]', '', v).split('.')
            return tuple(int(p) for p in parts if p)
        
        p1, p2 = parse_version(v1), parse_version(v2)
        
        for a, b in zip(p1, p2):
            if a < b:
                return -1
            if a > b:
                return 1
        
        return len(p1) - len(p2)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "attribute": self.attribute,
            "operator": self.operator.value,
            "value": self.value,
            "negate": self.negate
        }


@dataclass
class TargetingRule:
    """
    A rule for targeting specific users/segments.
    
    Rules contain multiple conditions that must all match (AND logic)
    and specify what value to return when the rule matches.
    
    Attributes:
        id: Unique rule identifier
        name: Human-readable rule name
        conditions: List of conditions (all must match)
        variation_id: Which variation to serve if rule matches
        percentage: Optional percentage of matching users to include
        enabled: Whether rule is active
        priority: Rule evaluation priority (lower = higher priority)
    
    Example:
        >>> rule = TargetingRule(
        ...     name="Beta Users",
        ...     conditions=[
        ...         Condition("groups", Operator.IN_LIST, ["beta"]),
        ...         Condition("country", Operator.IN_LIST, ["US", "CA"])
        ...     ],
        ...     variation_id="variation-beta"
        ... )
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    conditions: List[Condition] = field(default_factory=list)
    variation_id: str = ""
    percentage: Optional[float] = None  # 0-100
    enabled: bool = True
    priority: int = 0
    
    def evaluate(self, context: EvaluationContext) -> bool:
        """
        Evaluate if this rule matches the context.
        
        Args:
            context: The evaluation context
            
        Returns:
            True if all conditions match, False otherwise
        """
        if not self.enabled:
            return False
        
        if not self.conditions:
            return True
        
        # All conditions must match (AND logic)
        for condition in self.conditions:
            if not condition.evaluate(context):
                return False
        
        # Check percentage rollout
        if self.percentage is not None and self.percentage < 100:
            hash_value = self._get_hash_percentage(context.key, self.id)
            if hash_value >= self.percentage:
                return False
        
        return True
    
    def _get_hash_percentage(self, key: str, salt: str) -> float:
        """Get consistent hash percentage for a key."""
        hash_input = f"{key}:{salt}"
        hash_value = int(hashlib.sha256(hash_input.encode()).hexdigest()[:8], 16)
        return (hash_value % 10000) / 100  # 0-100 with 2 decimal precision
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "conditions": [c.to_dict() for c in self.conditions],
            "variation_id": self.variation_id,
            "percentage": self.percentage,
            "enabled": self.enabled,
            "priority": self.priority
        }


@dataclass
class Variation:
    """
    A variation of a feature flag value.
    
    Variations represent different values a flag can return,
    used for A/B testing and multivariate experiments.
    
    Attributes:
        id: Unique variation identifier
        name: Human-readable variation name
        value: The variation value
        weight: Weight for percentage-based distribution (0-100)
        description: Description of this variation
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    value: Any = None
    weight: float = 0  # 0-100
    description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "value": self.value,
            "weight": self.weight,
            "description": self.description
        }


@dataclass
class Schedule:
    """
    Schedule for automatic flag activation/deactivation.
    
    Attributes:
        start_time: When to activate the flag
        end_time: When to deactivate the flag (optional)
        timezone: Timezone for schedule times
        recurrence: Recurrence pattern (optional)
    """
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    timezone: str = "UTC"
    recurrence: Optional[str] = None  # cron expression
    
    def is_active(self, at_time: Optional[datetime] = None) -> bool:
        """Check if schedule is currently active."""
        now = at_time or datetime.utcnow()
        
        if self.start_time and now < self.start_time:
            return False
        if self.end_time and now > self.end_time:
            return False
        
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "timezone": self.timezone,
            "recurrence": self.recurrence
        }


@dataclass
class FeatureFlag:
    """
    Represents a feature flag with all its configuration.
    
    Feature flags are the core entity of the system, containing
    targeting rules, variations, and rollout configuration.
    
    Attributes:
        key: Unique identifier for the flag
        name: Human-readable name
        description: Detailed description
        flag_type: Type of flag value
        enabled: Whether flag is globally enabled
        default_variation_id: Default variation when no rules match
        variations: List of possible variations
        targeting_rules: List of targeting rules
        prerequisites: Flags that must be enabled for this flag
        tags: Tags for organization
        schedule: Optional activation schedule
        metadata: Additional metadata
    
    Example:
        >>> flag = FeatureFlag(
        ...     key="new-checkout-flow",
        ...     name="New Checkout Flow",
        ...     description="Redesigned checkout experience",
        ...     flag_type=FlagType.BOOLEAN,
        ...     variations=[
        ...         Variation(id="on", name="Enabled", value=True, weight=50),
        ...         Variation(id="off", name="Disabled", value=False, weight=50)
        ...     ],
        ...     default_variation_id="off"
        ... )
    """
    key: str
    name: str = ""
    description: str = ""
    flag_type: FlagType = FlagType.BOOLEAN
    enabled: bool = True
    status: FlagStatus = FlagStatus.ACTIVE
    default_variation_id: str = ""
    variations: List[Variation] = field(default_factory=list)
    targeting_rules: List[TargetingRule] = field(default_factory=list)
    fallthrough_variation_id: Optional[str] = None
    fallthrough_percentage_rollout: Optional[List[Tuple[str, float]]] = None
    prerequisites: List[str] = field(default_factory=list)
    tags: Set[str] = field(default_factory=set)
    schedule: Optional[Schedule] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    created_by: str = ""
    version: int = 1
    
    def __post_init__(self):
        # Create default boolean variations if none provided
        if not self.variations and self.flag_type == FlagType.BOOLEAN:
            self.variations = [
                Variation(id="true", name="Enabled", value=True, weight=0),
                Variation(id="false", name="Disabled", value=False, weight=100)
            ]
            self.default_variation_id = "false"
        
        # Sort rules by priority
        self.targeting_rules.sort(key=lambda r: r.priority)
    
    def get_variation(self, variation_id: str) -> Optional[Variation]:
        """Get a variation by ID."""
        for variation in self.variations:
            if variation.id == variation_id:
                return variation
        return None
    
    def get_default_variation(self) -> Optional[Variation]:
        """Get the default variation."""
        return self.get_variation(self.default_variation_id)
    
    def add_rule(self, rule: TargetingRule) -> None:
        """Add a targeting rule."""
        self.targeting_rules.append(rule)
        self.targeting_rules.sort(key=lambda r: r.priority)
        self.updated_at = datetime.utcnow()
        self.version += 1
    
    def remove_rule(self, rule_id: str) -> bool:
        """Remove a targeting rule by ID."""
        for i, rule in enumerate(self.targeting_rules):
            if rule.id == rule_id:
                self.targeting_rules.pop(i)
                self.updated_at = datetime.utcnow()
                self.version += 1
                return True
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert flag to dictionary."""
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "flag_type": self.flag_type.value,
            "enabled": self.enabled,
            "status": self.status.name,
            "default_variation_id": self.default_variation_id,
            "variations": [v.to_dict() for v in self.variations],
            "targeting_rules": [r.to_dict() for r in self.targeting_rules],
            "prerequisites": self.prerequisites,
            "tags": list(self.tags),
            "schedule": self.schedule.to_dict() if self.schedule else None,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FeatureFlag':
        """Create flag from dictionary."""
        data = data.copy()
        data["flag_type"] = FlagType(data.get("flag_type", "boolean"))
        data["status"] = FlagStatus[data.get("status", "ACTIVE")]
        data["variations"] = [
            Variation(**v) for v in data.get("variations", [])
        ]
        data["targeting_rules"] = [
            TargetingRule(
                **{**r, "conditions": [
                    Condition(**{**c, "operator": Operator(c["operator"])})
                    for c in r.get("conditions", [])
                ]}
            ) for r in data.get("targeting_rules", [])
        ]
        data["tags"] = set(data.get("tags", []))
        if data.get("schedule"):
            data["schedule"] = Schedule(**data["schedule"])
        if "created_at" in data and isinstance(data["created_at"], str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if "updated_at" in data and isinstance(data["updated_at"], str):
            data["updated_at"] = datetime.fromisoformat(data["updated_at"])
        return cls(**data)


class FlagStore(ABC):
    """
    Abstract base class for feature flag storage.
    
    Implement this to store flags in different backends like
    databases, Redis, or remote configuration services.
    """
    
    @abstractmethod
    async def get(self, key: str) -> Optional[FeatureFlag]:
        """Retrieve a flag by key."""
        pass
    
    @abstractmethod
    async def get_all(self) -> List[FeatureFlag]:
        """Retrieve all flags."""
        pass
    
    @abstractmethod
    async def save(self, flag: FeatureFlag) -> None:
        """Save a flag."""
        pass
    
    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete a flag by key."""
        pass
    
    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if a flag exists."""
        pass


class InMemoryFlagStore(FlagStore):
    """In-memory flag store for testing and development."""
    
    def __init__(self):
        self._flags: Dict[str, FeatureFlag] = {}
        self._lock = asyncio.Lock()
    
    async def get(self, key: str) -> Optional[FeatureFlag]:
        return self._flags.get(key)
    
    async def get_all(self) -> List[FeatureFlag]:
        return list(self._flags.values())
    
    async def save(self, flag: FeatureFlag) -> None:
        async with self._lock:
            self._flags[flag.key] = flag
    
    async def delete(self, key: str) -> bool:
        async with self._lock:
            if key in self._flags:
                del self._flags[key]
                return True
            return False
    
    async def exists(self, key: str) -> bool:
        return key in self._flags


class EvaluationListener(ABC):
    """
    Listener for flag evaluation events.
    
    Implement this to track flag evaluations for analytics,
    debugging, or auditing purposes.
    """
    
    @abstractmethod
    async def on_evaluation(
        self,
        flag_key: str,
        context: EvaluationContext,
        result: EvaluationResult
    ) -> None:
        """Called after each flag evaluation."""
        pass


class AnalyticsListener(EvaluationListener):
    """Listener that collects evaluation analytics."""
    
    def __init__(self):
        self.evaluations: Dict[str, List[Dict]] = defaultdict(list)
        self.counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._lock = asyncio.Lock()
    
    async def on_evaluation(
        self,
        flag_key: str,
        context: EvaluationContext,
        result: EvaluationResult
    ) -> None:
        async with self._lock:
            self.counts[flag_key][str(result.value)] += 1
            self.evaluations[flag_key].append({
                "timestamp": datetime.utcnow().isoformat(),
                "user_id": context.user_id,
                "value": result.value,
                "reason": result.reason.value
            })
    
    def get_stats(self, flag_key: str) -> Dict[str, Any]:
        """Get statistics for a flag."""
        counts = self.counts.get(flag_key, {})
        total = sum(counts.values())
        return {
            "total_evaluations": total,
            "value_distribution": {
                k: {"count": v, "percentage": (v / total * 100) if total > 0 else 0}
                for k, v in counts.items()
            }
        }


class FlagEvaluator:
    """
    Core engine for evaluating feature flags.
    
    Handles the complex logic of evaluating targeting rules,
    percentage rollouts, and prerequisites.
    """
    
    def __init__(self, store: FlagStore):
        self._store = store
        self._cache: Dict[str, Tuple[FeatureFlag, float]] = {}
        self._cache_ttl = 60.0  # seconds
        self._lock = asyncio.Lock()
        self._logger = logging.getLogger(__name__)
    
    async def evaluate(
        self,
        flag_key: str,
        context: EvaluationContext,
        default_value: FlagValueT
    ) -> EvaluationResult[FlagValueT]:
        """
        Evaluate a feature flag for a given context.
        
        Args:
            flag_key: The flag key to evaluate
            context: Evaluation context with user info
            default_value: Value to return if flag not found
            
        Returns:
            EvaluationResult with value and metadata
        """
        start_time = time.time()
        
        try:
            flag = await self._get_flag(flag_key)
            
            if flag is None:
                return EvaluationResult(
                    value=default_value,
                    reason=EvaluationReason.FLAG_NOT_FOUND,
                    flag_key=flag_key,
                    is_default=True,
                    evaluation_time_ms=(time.time() - start_time) * 1000
                )
            
            # Check if flag is enabled
            if not flag.enabled:
                default_var = flag.get_default_variation()
                return EvaluationResult(
                    value=default_var.value if default_var else default_value,
                    reason=EvaluationReason.FLAG_DISABLED,
                    flag_key=flag_key,
                    variation_id=flag.default_variation_id,
                    evaluation_time_ms=(time.time() - start_time) * 1000
                )
            
            # Check schedule
            if flag.schedule and not flag.schedule.is_active(context.timestamp):
                default_var = flag.get_default_variation()
                return EvaluationResult(
                    value=default_var.value if default_var else default_value,
                    reason=EvaluationReason.FLAG_DISABLED,
                    flag_key=flag_key,
                    variation_id=flag.default_variation_id,
                    metadata={"schedule_inactive": True},
                    evaluation_time_ms=(time.time() - start_time) * 1000
                )
            
            # Check prerequisites
            for prereq_key in flag.prerequisites:
                prereq_result = await self.evaluate(prereq_key, context, False)
                if not prereq_result.is_enabled:
                    default_var = flag.get_default_variation()
                    return EvaluationResult(
                        value=default