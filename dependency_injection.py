# src/dependency_injection/__init__.py
"""
Dependency Injection - A powerful IoC container and dependency injection framework.

This module provides a complete dependency injection system with support for
constructor injection, property injection, scoped lifetimes, interceptors,
auto-wiring, and modular configuration.

Version: 1.0.0
Author: Development Team
"""

from __future__ import annotations
import asyncio
import inspect
import threading
import weakref
from typing import (
    Any, Callable, Dict, List, Optional, Type, Union,
    Awaitable, Generic, TypeVar, Set, Tuple, get_type_hints,
    ForwardRef, Protocol, runtime_checkable, overload
)
from dataclasses import dataclass, field
from enum import Enum, auto
from abc import ABC, abstractmethod
from functools import wraps, partial
from collections import defaultdict
from datetime import datetime, timedelta
from contextlib import contextmanager, asynccontextmanager
import logging
import uuid
import copy


T = TypeVar('T')
TInterface = TypeVar('TInterface')
TImplementation = TypeVar('TImplementation')


class Lifetime(Enum):
    """
    Defines the lifetime/scope of a registered service.
    
    Attributes:
        TRANSIENT: New instance created for each request
        SCOPED: Single instance per scope (e.g., per request)
        SINGLETON: Single instance for entire application
        THREAD_LOCAL: Single instance per thread
    """
    TRANSIENT = auto()
    SCOPED = auto()
    SINGLETON = auto()
    THREAD_LOCAL = auto()


class InjectionMethod(Enum):
    """Methods for injecting dependencies."""
    CONSTRUCTOR = auto()
    PROPERTY = auto()
    METHOD = auto()


class ResolutionError(Exception):
    """Raised when a dependency cannot be resolved."""
    
    def __init__(self, service_type: Type, message: str, inner: Exception = None):
        self.service_type = service_type
        self.inner = inner
        super().__init__(f"Cannot resolve {service_type.__name__}: {message}")


class CircularDependencyError(ResolutionError):
    """Raised when a circular dependency is detected."""
    
    def __init__(self, chain: List[Type]):
        self.chain = chain
        chain_str = " -> ".join(t.__name__ for t in chain)
        super().__init__(
            chain[-1] if chain else type(None),
            f"Circular dependency detected: {chain_str}"
        )


class RegistrationError(Exception):
    """Raised when service registration fails."""
    pass


class ScopeDisposedError(Exception):
    """Raised when attempting to use a disposed scope."""
    pass


@dataclass
class ServiceDescriptor:
    """
    Describes a registered service and how to create it.
    
    Attributes:
        service_type: The interface/type being registered
        implementation_type: The concrete implementation type
        lifetime: Service lifetime scope
        factory: Optional factory function
        instance: Pre-created instance (for singletons)
        tags: Tags for filtering services
        metadata: Additional metadata
    """
    service_type: Type
    implementation_type: Optional[Type] = None
    lifetime: Lifetime = Lifetime.TRANSIENT
    factory: Optional[Callable[..., Any]] = None
    instance: Optional[Any] = None
    tags: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)
    name: Optional[str] = None  # Named registration
    
    def __post_init__(self):
        if self.instance is not None:
            self.lifetime = Lifetime.SINGLETON
        if self.implementation_type is None and self.factory is None and self.instance is None:
            self.implementation_type = self.service_type
    
    @property
    def is_factory(self) -> bool:
        """Check if this descriptor uses a factory."""
        return self.factory is not None
    
    @property
    def is_instance(self) -> bool:
        """Check if this descriptor has a pre-created instance."""
        return self.instance is not None


@dataclass
class InjectionPoint:
    """
    Represents a point where a dependency should be injected.
    
    Attributes:
        name: Parameter or property name
        service_type: Type to inject
        required: Whether injection is required
        default: Default value if not required
        qualifier: Named qualifier for specific registration
    """
    name: str
    service_type: Type
    required: bool = True
    default: Any = None
    qualifier: Optional[str] = None
    
    def __hash__(self):
        return hash((self.name, self.service_type, self.qualifier))


class Interceptor(ABC):
    """
    Abstract base class for service interceptors.
    
    Interceptors allow cross-cutting concerns to be applied
    to service method calls (AOP-style).
    """
    
    @abstractmethod
    async def intercept(
        self,
        context: 'InterceptionContext',
        next_call: Callable[[], Awaitable[Any]]
    ) -> Any:
        """
        Intercept a method call.
        
        Args:
            context: Context information about the call
            next_call: Function to call the next interceptor or target
            
        Returns:
            The result of the method call
        """
        pass


@dataclass
class InterceptionContext:
    """
    Context information for an intercepted method call.
    
    Attributes:
        service_type: Type of service being called
        method_name: Name of the method being called
        args: Positional arguments
        kwargs: Keyword arguments
        metadata: Additional context data
    """
    service_type: Type
    method_name: str
    args: tuple
    kwargs: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def method_signature(self) -> str:
        """Get human-readable method signature."""
        return f"{self.service_type.__name__}.{self.method_name}"


class LoggingInterceptor(Interceptor):
    """Interceptor that logs method calls."""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
    
    async def intercept(
        self,
        context: InterceptionContext,
        next_call: Callable[[], Awaitable[Any]]
    ) -> Any:
        self.logger.debug(f"Calling {context.method_signature}")
        start_time = datetime.utcnow()
        
        try:
            result = await next_call()
            elapsed = (datetime.utcnow() - start_time).total_seconds()
            self.logger.debug(
                f"Completed {context.method_signature} in {elapsed:.3f}s"
            )
            return result
        except Exception as e:
            self.logger.error(
                f"Error in {context.method_signature}: {e}"
            )
            raise


class CachingInterceptor(Interceptor):
    """
    Interceptor that caches method results.
    
    Caches results based on method arguments for configurable duration.
    """
    
    def __init__(self, ttl_seconds: int = 300, max_size: int = 1000):
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._lock = asyncio.Lock()
    
    def _cache_key(self, context: InterceptionContext) -> str:
        """Generate cache key from context."""
        import hashlib
        import json
        key_data = json.dumps({
            "method": context.method_signature,
            "args": str(context.args),
            "kwargs": str(sorted(context.kwargs.items()))
        }, sort_keys=True)
        return hashlib.sha256(key_data.encode()).hexdigest()
    
    async def intercept(
        self,
        context: InterceptionContext,
        next_call: Callable[[], Awaitable[Any]]
    ) -> Any:
        cache_key = self._cache_key(context)
        
        async with self._lock:
            if cache_key in self._cache:
                result, expires_at = self._cache[cache_key]
                if datetime.utcnow().timestamp() < expires_at:
                    return result
                del self._cache[cache_key]
        
        result = await next_call()
        
        async with self._lock:
            if len(self._cache) >= self.max_size:
                # Remove oldest entry
                oldest = min(self._cache.items(), key=lambda x: x[1][1])
                del self._cache[oldest[0]]
            
            expires_at = datetime.utcnow().timestamp() + self.ttl_seconds
            self._cache[cache_key] = (result, expires_at)
        
        return result


class RetryInterceptor(Interceptor):
    """
    Interceptor that retries failed method calls.
    
    Implements exponential backoff for transient failures.
    """
    
    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 0.1,
        max_delay: float = 10.0,
        exponential_base: float = 2.0,
        retry_exceptions: Set[Type[Exception]] = None
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.retry_exceptions = retry_exceptions or {Exception}
    
    async def intercept(
        self,
        context: InterceptionContext,
        next_call: Callable[[], Awaitable[Any]]
    ) -> Any:
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return await next_call()
            except Exception as e:
                if not any(isinstance(e, exc) for exc in self.retry_exceptions):
                    raise
                
                last_exception = e
                
                if attempt < self.max_retries:
                    delay = min(
                        self.initial_delay * (self.exponential_base ** attempt),
                        self.max_delay
                    )
                    await asyncio.sleep(delay)
        
        raise last_exception


class ServiceScope:
    """
    Represents a dependency injection scope.
    
    Scopes manage the lifetime of scoped services and ensure
    proper disposal of resources.
    
    Example:
        >>> async with container.create_scope() as scope:
        ...     service = await scope.resolve(MyService)
        ...     await service.do_work()
    """
    
    def __init__(
        self,
        container: 'Container',
        parent: Optional['ServiceScope'] = None
    ):
        self._container = container
        self._parent = parent
        self._instances: Dict[Type, Any] = {}
        self._disposables: List[Any] = []
        self._disposed = False
        self._lock = asyncio.Lock()
        self._scope_id = str(uuid.uuid4())
    
    @property
    def scope_id(self) -> str:
        """Get unique scope identifier."""
        return self._scope_id
    
    @property
    def is_disposed(self) -> bool:
        """Check if scope has been disposed."""
        return self._disposed
    
    def _check_disposed(self) -> None:
        """Raise error if scope is disposed."""
        if self._disposed:
            raise ScopeDisposedError("Cannot use a disposed scope")
    
    async def resolve(
        self,
        service_type: Type[T],
        name: Optional[str] = None
    ) -> T:
        """
        Resolve a service from this scope.
        
        Args:
            service_type: The type to resolve
            name: Optional named registration
            
        Returns:
            Instance of the requested service
        """
        self._check_disposed()
        return await self._container._resolve_internal(
            service_type,
            name,
            self,
            set()
        )
    
    async def resolve_all(self, service_type: Type[T]) -> List[T]:
        """Resolve all registrations of a service type."""
        self._check_disposed()
        return await self._container._resolve_all_internal(
            service_type,
            self,
            set()
        )
    
    def get_scoped_instance(self, service_type: Type) -> Optional[Any]:
        """Get an existing scoped instance."""
        return self._instances.get(service_type)
    
    def set_scoped_instance(self, service_type: Type, instance: Any) -> None:
        """Store a scoped instance."""
        self._instances[service_type] = instance
        
        # Track disposables
        if hasattr(instance, 'dispose') or hasattr(instance, 'close'):
            self._disposables.append(instance)
    
    def create_child_scope(self) -> 'ServiceScope':
        """Create a child scope."""
        return ServiceScope(self._container, parent=self)
    
    async def dispose(self) -> None:
        """Dispose the scope and all scoped instances."""
        if self._disposed:
            return
        
        async with self._lock:
            self._disposed = True
            
            # Dispose in reverse order
            for disposable in reversed(self._disposables):
                try:
                    if hasattr(disposable, 'dispose'):
                        result = disposable.dispose()
                        if asyncio.iscoroutine(result):
                            await result
                    elif hasattr(disposable, 'close'):
                        result = disposable.close()
                        if asyncio.iscoroutine(result):
                            await result
                except Exception:
                    pass  # Log but don't fail disposal
            
            self._instances.clear()
            self._disposables.clear()
    
    async def __aenter__(self) -> 'ServiceScope':
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.dispose()


class ServiceCollection:
    """
    Builder for configuring services before creating a container.
    
    Provides a fluent API for registering services with various
    lifetimes and configurations.
    
    Example:
        >>> services = ServiceCollection()
        >>> services.add_singleton(ILogger, ConsoleLogger)
        >>> services.add_scoped(IUserRepository, SqlUserRepository)
        >>> services.add_transient(IEmailService, SmtpEmailService)
        >>> container = services.build()
    """
    
    def __init__(self):
        self._descriptors: List[ServiceDescriptor] = []
        self._modules: List['Module'] = []
        self._interceptors: Dict[Type, List[Type[Interceptor]]] = defaultdict(list)
    
    def add(
        self,
        service_type: Type[TInterface],
        implementation_type: Optional[Type[TImplementation]] = None,
        lifetime: Lifetime = Lifetime.TRANSIENT,
        name: Optional[str] = None,
        tags: Optional[Set[str]] = None
    ) -> 'ServiceCollection':
        """
        Add a service registration.
        
        Args:
            service_type: Interface or base type
            implementation_type: Concrete implementation
            lifetime: Service lifetime
            name: Optional named registration
            tags: Optional tags for filtering
            
        Returns:
            Self for method chaining
        """
        descriptor = ServiceDescriptor(
            service_type=service_type,
            implementation_type=implementation_type or service_type,
            lifetime=lifetime,
            name=name,
            tags=tags or set()
        )
        self._descriptors.append(descriptor)
        return self
    
    def add_transient(
        self,
        service_type: Type[TInterface],
        implementation_type: Optional[Type[TImplementation]] = None,
        name: Optional[str] = None
    ) -> 'ServiceCollection':
        """Add a transient service (new instance per request)."""
        return self.add(service_type, implementation_type, Lifetime.TRANSIENT, name)
    
    def add_scoped(
        self,
        service_type: Type[TInterface],
        implementation_type: Optional[Type[TImplementation]] = None,
        name: Optional[str] = None
    ) -> 'ServiceCollection':
        """Add a scoped service (one instance per scope)."""
        return self.add(service_type, implementation_type, Lifetime.SCOPED, name)
    
    def add_singleton(
        self,
        service_type: Type[TInterface],
        implementation_type: Optional[Type[TImplementation]] = None,
        name: Optional[str] = None
    ) -> 'ServiceCollection':
        """Add a singleton service (one instance for application)."""
        return self.add(service_type, implementation_type, Lifetime.SINGLETON, name)
    
    def add_instance(
        self,
        service_type: Type[T],
        instance: T,
        name: Optional[str] = None
    ) -> 'ServiceCollection':
        """
        Add a pre-created instance as a singleton.
        
        Args:
            service_type: The type to register
            instance: The instance to use
            name: Optional named registration
            
        Returns:
            Self for method chaining
        """
        descriptor = ServiceDescriptor(
            service_type=service_type,
            instance=instance,
            name=name
        )
        self._descriptors.append(descriptor)
        return self
    
    def add_factory(
        self,
        service_type: Type[T],
        factory: Callable[['Container'], T],
        lifetime: Lifetime = Lifetime.TRANSIENT,
        name: Optional[str] = None
    ) -> 'ServiceCollection':
        """
        Add a factory function for creating service instances.
        
        Args:
            service_type: The type to register
            factory: Factory function that receives the container
            lifetime: Service lifetime
            name: Optional named registration
            
        Returns:
            Self for method chaining
        """
        descriptor = ServiceDescriptor(
            service_type=service_type,
            factory=factory,
            lifetime=lifetime,
            name=name
        )
        self._descriptors.append(descriptor)
        return self
    
    def add_interceptor(
        self,
        service_type: Type,
        interceptor_type: Type[Interceptor]
    ) -> 'ServiceCollection':
        """
        Add an interceptor for a service type.
        
        Args:
            service_type: The type to intercept
            interceptor_type: The interceptor class
            
        Returns:
            Self for method chaining
        """
        self._interceptors[service_type].append(interceptor_type)
        return self
    
    def add_module(self, module: 'Module') -> 'ServiceCollection':
        """
        Add a module containing service registrations.
        
        Args:
            module: The module to add
            
        Returns:
            Self for method chaining
        """
        self._modules.append(module)
        return self
    
    def try_add(
        self,
        service_type: Type[TInterface],
        implementation_type: Optional[Type[TImplementation]] = None,
        lifetime: Lifetime = Lifetime.TRANSIENT
    ) -> 'ServiceCollection':
        """Add service only if not already registered."""
        if not any(d.service_type == service_type for d in self._descriptors):
            self.add(service_type, implementation_type, lifetime)
        return self
    
    def replace(
        self,
        service_type: Type[TInterface],
        implementation_type: Optional[Type[TImplementation]] = None,
        lifetime: Lifetime = Lifetime.TRANSIENT
    ) -> 'ServiceCollection':
        """Replace an existing registration."""
        self._descriptors = [
            d for d in self._descriptors if d.service_type != service_type
        ]
        return self.add(service_type, implementation_type, lifetime)
    
    def build(self) -> 'Container':
        """
        Build the dependency injection container.
        
        Returns:
            Configured Container instance
        """
        # Apply modules
        for module in self._modules:
            module.configure(self)
        
        return Container(
            list(self._descriptors),
            dict(self._interceptors)
        )


class Module(ABC):
    """
    Abstract base class for modular service registration.
    
    Modules group related service registrations for better organization
    and reusability.
    
    Example:
        >>> class DatabaseModule(Module):
        ...     def configure(self, services: ServiceCollection) -> None:
        ...         services.add_singleton(IDatabase, PostgresDatabase)
        ...         services.add_scoped(ITransaction, DbTransaction)
    """
    
    @abstractmethod
    def configure(self, services: ServiceCollection) -> None:
        """Configure services in this module."""
        pass


class Container:
    """
    Main dependency injection container.
    
    The Container resolves dependencies, manages service lifetimes,
    and provides scoping capabilities.
    
    Example:
        >>> container = ServiceCollection() \\
        ...     .add_singleton(IConfig, AppConfig) \\
        ...     .add_transient(IUserService, UserService) \\
        ...     .build()
        >>> 
        >>> user_service = await container.resolve(IUserService)
    
    Features:
        - Constructor injection with auto-wiring
        - Property injection via decorators
        - Multiple lifetime scopes
        - Named registrations
        - Interceptors (AOP)
        - Circular dependency detection
        - Factory functions
        - Modules for organization
    """
    
    def __init__(
        self,
        descriptors: List[ServiceDescriptor],
        interceptors: Dict[Type, List[Type[Interceptor]]] = None
    ):
        """
        Initialize the container.
        
        Args:
            descriptors: List of service descriptors
            interceptors: Map of service types to interceptor types
        """
        self._descriptors = descriptors
        self._interceptors = interceptors or {}
        self._singletons: Dict[Tuple[Type, Optional[str]], Any] = {}
        self._thread_locals: Dict[Type, threading.local] = {}
        self._lock = asyncio.Lock()
        self._sync_lock = threading.RLock()
        self._logger = logging.getLogger(__name__)
        
        # Build lookup maps
        self._by_type: Dict[Type, List[ServiceDescriptor]] = defaultdict(list)
        self._by_name: Dict[Tuple[Type, str], ServiceDescriptor] = {}
        
        for descriptor in descriptors:
            self._by_type[descriptor.service_type].append(descriptor)
            if descriptor.name:
                self._by_name[(descriptor.service_type, descriptor.name)] = descriptor
    
    async def resolve(
        self,
        service_type: Type[T],
        name: Optional[str] = None
    ) -> T:
        """
        Resolve a service instance.
        
        Args:
            service_type: The type to resolve
            name: Optional named registration
            
        Returns:
            Instance of the requested service
            
        Raises:
            ResolutionError: If service cannot be resolved
        """
        return await self._resolve_internal(service_type, name, None, set())
    
    async def resolve_all(self, service_type: Type[T]) -> List[T]:
        """
        Resolve all registrations of a service type.
        
        Args:
            service_type: The type to resolve
            
        Returns:
            List of all registered instances
        """
        return await self._resolve_all_internal(service_type, None, set())
    
    def resolve_sync(
        self,
        service_type: Type[T],
        name: Optional[str] = None
    ) -> T:
        """
        Synchronously resolve a service.
        
        Use this for simple cases without async dependencies.
        """
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.resolve(service_type, name))
        finally:
            loop.close()
    
    def create_scope(self) -> ServiceScope:
        """
        Create a new dependency injection scope.
        
        Returns:
            New ServiceScope instance
        """
        return ServiceScope(self)
    
    @asynccontextmanager
    async def scope(self):
        """
        Context manager for creating a scope.
        
        Example:
            >>> async with container.scope() as scope:
            ...     service = await scope.resolve(MyService)
        """
        scope = self.create_scope()
        try:
            yield scope
        finally:
            await scope.dispose()
    
    async def _resolve_internal(
        self,
        service_type: Type[T],
        name: Optional[str],
        scope: Optional[ServiceScope],
        resolution_chain: Set[Type]
    ) -> T:
        """Internal resolution logic."""
        # Check for circular dependencies
        if service_type in resolution_chain:
            raise CircularDependencyError(list(resolution_chain) + [service_type])
        
        resolution_chain = resolution_chain | {service_type}
        
        # Find descriptor
        descriptor = self._get_descriptor(service_type, name)
        if descriptor is None:
            raise ResolutionError(
                service_type,
                f"No registration found for {service_type.__name__}"
            )
        
        # Get or create instance based on lifetime
        instance = await self._get_or_create_instance(
            descriptor, scope, resolution_chain
        )
        
        # Apply interceptors
        if service_type in self._interceptors:
            instance = await self._create_proxy(instance, service_type)
        
        return instance
    
    async def _resolve_all_internal(
        self,
        service_type: Type[T],
        scope: Optional[ServiceScope],
        resolution_chain: Set[Type]
    ) -> List[T]:
        """Resolve all registrations of a type."""
        descriptors = self._by_type.get(service_type, [])
        instances = []
        
        for descriptor in descriptors:
            instance = await self._get_or_create_instance(
                descriptor, scope, resolution_chain
            )
            instances.append(instance)
        
        return instances
    
    def _get_descriptor(
        self,
        service_type: Type,
        name: Optional[str]
    ) -> Optional[ServiceDescriptor]:
        """Find descriptor for service type and name."""
        if name:
            return self._by_name.get((service_type, name))
        
        descriptors = self._by_type.get(service_type, [])
        return descriptors[-1] if descriptors else None
    
    async def _get_or_create_instance(
        self,
        descriptor: ServiceDescriptor,
        scope: Optional[ServiceScope],
        resolution_chain: Set[Type]
    ) -> Any:
        """Get existing or create new instance based on lifetime."""
        key = (descriptor.service_type, descriptor.name)
        
        # Handle pre-created instance
        if descriptor.instance is not None:
            return descriptor.instance
        
        # Handle singletons
        if descriptor.lifetime == Lifetime.SINGLETON:
            if key not in self._singletons:
                async with self._lock:
                    if key not in self._singletons:
                        self._singletons[key] = await self._create_instance(
                            descriptor, scope, resolution_chain
                        )
            return self._singletons[key]
        
        # Handle thread-local
        if descriptor.lifetime == Lifetime.THREAD_LOCAL:
            if descriptor.service_type not in self._thread_locals:
                self._thread_locals[descriptor.service_type] = threading.local()
            
            local = self._thread_locals[descriptor.service_type]
            if not hasattr(local, 'instance'):
                local.instance = await self._create_instance(
                    descriptor, scope, resolution_chain
                )
            return local.instance
        
        # Handle scoped
        if descriptor.lifetime == Lifetime.SCOPED:
            if scope is None:
                raise ResolutionError(
                    descriptor.service_type,
                    "Scoped service requested without a scope"
                )
            
            existing = scope.get_scoped_instance(descriptor.service_type)
            if existing is not None:
                return existing
            
            instance = await self._create_instance(
                descriptor, scope, resolution_chain
            )
            scope.set_scoped_instance(descriptor.service_type, instance)
            return instance
        
        # Transient - always create new
        return await self._create_instance(descriptor, scope, resolution_chain)
    
    async def _create_instance(
        self,
        descriptor: ServiceDescriptor,
        scope: Optional[ServiceScope],
        resolution_chain: Set[Type]
    ) -> Any:
        """Create a new instance of a service."""
        # Use factory if provided
        if descriptor.factory is not None:
            if asyncio.iscoroutinefunction(descriptor.factory):
                return await descriptor.factory(self)
            return descriptor.factory(self)
        
        impl_type = descriptor.implementation_type
        
        # Get constructor parameters
        injection_points = self._get_injection_points(impl_type)
        
        # Resolve dependencies
        kwargs = {}
        for point in injection_points:
            try:
                dependency = await self._resolve_internal(
                    point.service_type,
                    point.qualifier,
                    scope,
                    resolution_chain
                )
                kwargs[point.name] = dependency
            except ResolutionError:
                if point.required:
                    raise
                kwargs[point.name] = point.default
        
        # Create instance
        instance = impl_type(**kwargs)
        
        # Property injection
        await self._inject_properties(instance, scope, resolution_chain)
        
        # Call post-construct if exists
        if hasattr(instance, '__post_construct__'):
            result = instance.__post_construct__()
            if asyncio.iscoroutine(result):
                await result
        
        return instance
    
    def _get_injection_points(self, impl_type: Type) -> List[InjectionPoint]:
        """Get injection points from constructor."""
        try:
            hints = get_type_hints(impl_type.__init__)
        except Exception:
            hints = {}
        
        sig = inspect.signature(impl_type.__init__)
        points = []
        
        for name, param in sig.parameters.items():
            if name == 'self':
                continue
            
            service_type = hints.get(name, param.annotation)
            if service_type == inspect.Parameter.empty:
                continue
            
            required = param.default == inspect.Parameter.empty
            default = None if required else param.default
            
            # Check for Inject annotation
            qualifier = None
            if hasattr(param, 'annotation') and hasattr(param.annotation, '__metadata__'):
                for meta in param.annotation.__metadata__:
                    if isinstance(meta, Inject):
                        qualifier = meta.name
            
            points.append(InjectionPoint(
                name=name,
                service_type=service_type,
                required=required,
                default=default,
                qualifier=qualifier
            ))
        
        return points
    
    async def _inject_properties(