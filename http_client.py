# src/http_client/__init__.py
"""
HTTP Client - A powerful async HTTP client framework for Python.

This module provides a feature-rich HTTP client with support for middleware,
automatic retries, circuit breakers, request/response interceptors, caching,
and comprehensive observability.

Version: 1.0.0
Author: Development Team
"""

from __future__ import annotations
import asyncio
import time
import json
import hashlib
import logging
import ssl
import urllib.parse
from typing import (
    Any, Callable, Dict, List, Optional, Type, Union,
    Awaitable, Generic, TypeVar, Set, Tuple, AsyncIterator,
    Mapping, IO, BinaryIO
)
from dataclasses import dataclass, field
from enum import Enum, auto
from abc import ABC, abstractmethod
from functools import wraps
from collections import defaultdict
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
import base64
import gzip
import zlib
from io import BytesIO
import re
import uuid


T = TypeVar('T')
ResponseT = TypeVar('ResponseT')


class HttpMethod(Enum):
    """HTTP methods supported by the client."""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"
    TRACE = "TRACE"
    CONNECT = "CONNECT"


class ContentType(Enum):
    """Common content types."""
    JSON = "application/json"
    FORM = "application/x-www-form-urlencoded"
    MULTIPART = "multipart/form-data"
    XML = "application/xml"
    TEXT = "text/plain"
    HTML = "text/html"
    BINARY = "application/octet-stream"


class AuthType(Enum):
    """Authentication types."""
    NONE = auto()
    BASIC = auto()
    BEARER = auto()
    API_KEY = auto()
    OAUTH2 = auto()
    DIGEST = auto()
    CUSTOM = auto()


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = auto()      # Normal operation
    OPEN = auto()        # Failing, rejecting requests
    HALF_OPEN = auto()   # Testing if service recovered


@dataclass
class HttpHeaders:
    """
    HTTP headers container with case-insensitive access.
    
    Provides a dictionary-like interface for HTTP headers with
    case-insensitive key lookup and multi-value support.
    
    Example:
        >>> headers = HttpHeaders({"Content-Type": "application/json"})
        >>> headers["content-type"]  # Case-insensitive
        'application/json'
    """
    _headers: Dict[str, List[str]] = field(default_factory=dict)
    
    def __post_init__(self):
        if isinstance(self._headers, dict):
            normalized = {}
            for key, value in self._headers.items():
                norm_key = key.lower()
                if isinstance(value, list):
                    normalized[norm_key] = value
                else:
                    normalized[norm_key] = [str(value)]
            self._headers = normalized
    
    def __getitem__(self, key: str) -> str:
        values = self._headers.get(key.lower(), [])
        return values[0] if values else ""
    
    def __setitem__(self, key: str, value: str) -> None:
        self._headers[key.lower()] = [str(value)]
    
    def __contains__(self, key: str) -> bool:
        return key.lower() in self._headers
    
    def __iter__(self):
        return iter(self._headers)
    
    def get(self, key: str, default: str = "") -> str:
        """Get header value with default."""
        values = self._headers.get(key.lower(), [])
        return values[0] if values else default
    
    def get_all(self, key: str) -> List[str]:
        """Get all values for a header."""
        return self._headers.get(key.lower(), [])
    
    def add(self, key: str, value: str) -> None:
        """Add a value to a header (supports multiple values)."""
        norm_key = key.lower()
        if norm_key not in self._headers:
            self._headers[norm_key] = []
        self._headers[norm_key].append(str(value))
    
    def remove(self, key: str) -> None:
        """Remove a header."""
        self._headers.pop(key.lower(), None)
    
    def update(self, headers: Union[Dict[str, str], 'HttpHeaders']) -> None:
        """Update headers from another dict or HttpHeaders."""
        if isinstance(headers, HttpHeaders):
            for key in headers:
                self._headers[key] = headers.get_all(key)
        else:
            for key, value in headers.items():
                self[key] = value
    
    def to_dict(self) -> Dict[str, str]:
        """Convert to regular dict (first value only)."""
        return {k: v[0] for k, v in self._headers.items() if v}
    
    def to_list(self) -> List[Tuple[str, str]]:
        """Convert to list of tuples (all values)."""
        result = []
        for key, values in self._headers.items():
            for value in values:
                result.append((key, value))
        return result


@dataclass
class Cookie:
    """
    Represents an HTTP cookie.
    
    Attributes:
        name: Cookie name
        value: Cookie value
        domain: Cookie domain
        path: Cookie path
        expires: Expiration time
        secure: Secure flag
        http_only: HttpOnly flag
        same_site: SameSite attribute
    """
    name: str
    value: str
    domain: str = ""
    path: str = "/"
    expires: Optional[datetime] = None
    max_age: Optional[int] = None
    secure: bool = False
    http_only: bool = False
    same_site: Optional[str] = None
    
    def is_expired(self) -> bool:
        """Check if cookie has expired."""
        if self.expires is None:
            return False
        return datetime.utcnow() > self.expires
    
    def to_header_value(self) -> str:
        """Convert to Set-Cookie header value."""
        parts = [f"{self.name}={self.value}"]
        if self.domain:
            parts.append(f"Domain={self.domain}")
        if self.path:
            parts.append(f"Path={self.path}")
        if self.expires:
            parts.append(f"Expires={self.expires.strftime('%a, %d %b %Y %H:%M:%S GMT')}")
        if self.max_age is not None:
            parts.append(f"Max-Age={self.max_age}")
        if self.secure:
            parts.append("Secure")
        if self.http_only:
            parts.append("HttpOnly")
        if self.same_site:
            parts.append(f"SameSite={self.same_site}")
        return "; ".join(parts)


class CookieJar:
    """
    Container for managing cookies across requests.
    
    Handles cookie storage, expiration, and domain/path matching
    for automatic cookie sending.
    """
    
    def __init__(self):
        self._cookies: Dict[str, Dict[str, Cookie]] = defaultdict(dict)
        self._lock = asyncio.Lock()
    
    async def add(self, cookie: Cookie) -> None:
        """Add a cookie to the jar."""
        async with self._lock:
            domain = cookie.domain or ""
            self._cookies[domain][cookie.name] = cookie
    
    async def get(self, name: str, domain: str = "") -> Optional[Cookie]:
        """Get a cookie by name and domain."""
        async with self._lock:
            domain_cookies = self._cookies.get(domain, {})
            return domain_cookies.get(name)
    
    async def get_cookies_for_url(self, url: str) -> List[Cookie]:
        """Get all cookies applicable to a URL."""
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc
        path = parsed.path or "/"
        
        matching = []
        async with self._lock:
            for cookie_domain, cookies in self._cookies.items():
                if self._domain_matches(domain, cookie_domain):
                    for cookie in cookies.values():
                        if not cookie.is_expired() and path.startswith(cookie.path):
                            matching.append(cookie)
        
        return matching
    
    def _domain_matches(self, request_domain: str, cookie_domain: str) -> bool:
        """Check if request domain matches cookie domain."""
        if not cookie_domain:
            return True
        if request_domain == cookie_domain:
            return True
        if cookie_domain.startswith("."):
            return request_domain.endswith(cookie_domain)
        return False
    
    async def clear(self, domain: Optional[str] = None) -> None:
        """Clear cookies, optionally for a specific domain."""
        async with self._lock:
            if domain:
                self._cookies.pop(domain, None)
            else:
                self._cookies.clear()
    
    async def remove_expired(self) -> int:
        """Remove expired cookies. Returns count removed."""
        count = 0
        async with self._lock:
            for domain in list(self._cookies.keys()):
                for name in list(self._cookies[domain].keys()):
                    if self._cookies[domain][name].is_expired():
                        del self._cookies[domain][name]
                        count += 1
        return count


@dataclass
class RequestConfig:
    """
    Configuration for individual requests.
    
    Attributes:
        timeout: Request timeout in seconds
        follow_redirects: Whether to follow redirects
        max_redirects: Maximum number of redirects
        verify_ssl: Whether to verify SSL certificates
        proxy: Proxy URL
        auth: Authentication configuration
        retry_enabled: Whether retries are enabled
        cache_enabled: Whether caching is enabled
    """
    timeout: float = 30.0
    connect_timeout: float = 10.0
    read_timeout: float = 30.0
    follow_redirects: bool = True
    max_redirects: int = 10
    verify_ssl: bool = True
    proxy: Optional[str] = None
    auth: Optional['Authentication'] = None
    retry_enabled: bool = True
    cache_enabled: bool = True
    decompress: bool = True
    raise_for_status: bool = False
    
    def merge(self, other: 'RequestConfig') -> 'RequestConfig':
        """Merge with another config, other takes precedence."""
        return RequestConfig(
            timeout=other.timeout if other.timeout != 30.0 else self.timeout,
            connect_timeout=other.connect_timeout if other.connect_timeout != 10.0 else self.connect_timeout,
            read_timeout=other.read_timeout if other.read_timeout != 30.0 else self.read_timeout,
            follow_redirects=other.follow_redirects,
            max_redirects=other.max_redirects if other.max_redirects != 10 else self.max_redirects,
            verify_ssl=other.verify_ssl,
            proxy=other.proxy or self.proxy,
            auth=other.auth or self.auth,
            retry_enabled=other.retry_enabled,
            cache_enabled=other.cache_enabled,
            decompress=other.decompress,
            raise_for_status=other.raise_for_status
        )


@dataclass
class Request:
    """
    Represents an HTTP request.
    
    Contains all information needed to make an HTTP request,
    including URL, method, headers, body, and configuration.
    
    Example:
        >>> request = Request(
        ...     method=HttpMethod.POST,
        ...     url="https://api.example.com/users",
        ...     headers=HttpHeaders({"Content-Type": "application/json"}),
        ...     body=json.dumps({"name": "John"})
        ... )
    """
    method: HttpMethod
    url: str
    headers: HttpHeaders = field(default_factory=HttpHeaders)
    body: Optional[Union[str, bytes, Dict, BinaryIO]] = None
    params: Optional[Dict[str, Any]] = None
    config: RequestConfig = field(default_factory=RequestConfig)
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if not isinstance(self.headers, HttpHeaders):
            self.headers = HttpHeaders(self.headers)
    
    @property
    def full_url(self) -> str:
        """Get URL with query parameters."""
        if not self.params:
            return self.url
        
        parsed = urllib.parse.urlparse(self.url)
        existing_params = urllib.parse.parse_qs(parsed.query)
        
        # Merge params
        all_params = {**existing_params, **{k: [str(v)] for k, v in self.params.items()}}
        query_string = urllib.parse.urlencode(all_params, doseq=True)
        
        return urllib.parse.urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            parsed.params, query_string, parsed.fragment
        ))
    
    def get_body_bytes(self) -> Optional[bytes]:
        """Get request body as bytes."""
        if self.body is None:
            return None
        if isinstance(self.body, bytes):
            return self.body
        if isinstance(self.body, str):
            return self.body.encode('utf-8')
        if isinstance(self.body, dict):
            return json.dumps(self.body).encode('utf-8')
        if hasattr(self.body, 'read'):
            return self.body.read()
        return str(self.body).encode('utf-8')
    
    def clone(self, **overrides) -> 'Request':
        """Create a copy of the request with optional overrides."""
        data = {
            "method": self.method,
            "url": self.url,
            "headers": HttpHeaders(self.headers.to_dict()),
            "body": self.body,
            "params": self.params.copy() if self.params else None,
            "config": self.config,
            "metadata": self.metadata.copy()
        }
        data.update(overrides)
        return Request(**data)


@dataclass
class Response:
    """
    Represents an HTTP response.
    
    Contains response data including status, headers, body,
    and timing information.
    
    Example:
        >>> response = await client.get("https://api.example.com/users")
        >>> if response.is_success:
        ...     users = response.json()
    """
    status_code: int
    headers: HttpHeaders
    body: bytes
    request: Request
    elapsed: float  # Request duration in seconds
    url: str  # Final URL after redirects
    redirect_history: List['Response'] = field(default_factory=list)
    http_version: str = "1.1"
    reason: str = ""
    
    @property
    def is_success(self) -> bool:
        """Check if response indicates success (2xx)."""
        return 200 <= self.status_code < 300
    
    @property
    def is_redirect(self) -> bool:
        """Check if response is a redirect (3xx)."""
        return 300 <= self.status_code < 400
    
    @property
    def is_client_error(self) -> bool:
        """Check if response indicates client error (4xx)."""
        return 400 <= self.status_code < 500
    
    @property
    def is_server_error(self) -> bool:
        """Check if response indicates server error (5xx)."""
        return 500 <= self.status_code < 600
    
    @property
    def ok(self) -> bool:
        """Alias for is_success."""
        return self.is_success
    
    @property
    def content_type(self) -> str:
        """Get content type from headers."""
        ct = self.headers.get("content-type", "")
        return ct.split(";")[0].strip()
    
    @property
    def encoding(self) -> str:
        """Detect response encoding."""
        ct = self.headers.get("content-type", "")
        match = re.search(r'charset=([^\s;]+)', ct)
        if match:
            return match.group(1)
        return "utf-8"
    
    @property
    def content_length(self) -> int:
        """Get content length."""
        try:
            return int(self.headers.get("content-length", "0"))
        except ValueError:
            return len(self.body)
    
    def text(self) -> str:
        """Get response body as text."""
        return self.body.decode(self.encoding, errors='replace')
    
    def json(self, **kwargs) -> Any:
        """Parse response body as JSON."""
        return json.loads(self.text(), **kwargs)
    
    def xml(self):
        """Parse response body as XML (requires xml.etree)."""
        import xml.etree.ElementTree as ET
        return ET.fromstring(self.text())
    
    def raise_for_status(self) -> None:
        """Raise an exception if response indicates an error."""
        if self.is_client_error or self.is_server_error:
            raise HttpError(
                f"HTTP {self.status_code}: {self.reason}",
                response=self
            )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert response to dictionary."""
        return {
            "status_code": self.status_code,
            "headers": self.headers.to_dict(),
            "body_length": len(self.body),
            "url": self.url,
            "elapsed": self.elapsed,
            "content_type": self.content_type
        }


class HttpError(Exception):
    """Base exception for HTTP errors."""
    
    def __init__(self, message: str, response: Optional[Response] = None):
        self.message = message
        self.response = response
        super().__init__(message)


class TimeoutError(HttpError):
    """Raised when a request times out."""
    pass


class ConnectionError(HttpError):
    """Raised when a connection cannot be established."""
    pass


class TooManyRedirectsError(HttpError):
    """Raised when too many redirects are encountered."""
    pass


class CircuitBreakerOpenError(HttpError):
    """Raised when circuit breaker is open."""
    pass


class Authentication(ABC):
    """
    Abstract base class for authentication handlers.
    
    Implement this to create custom authentication mechanisms.
    """
    
    @abstractmethod
    async def authenticate(self, request: Request) -> Request:
        """Apply authentication to a request."""
        pass
    
    @abstractmethod
    async def handle_401(self, response: Response) -> Optional[Request]:
        """Handle 401 response, return new request if retry needed."""
        pass


class BasicAuth(Authentication):
    """HTTP Basic Authentication."""
    
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
    
    async def authenticate(self, request: Request) -> Request:
        credentials = base64.b64encode(
            f"{self.username}:{self.password}".encode()
        ).decode('ascii')
        request.headers["Authorization"] = f"Basic {credentials}"
        return request
    
    async def handle_401(self, response: Response) -> Optional[Request]:
        return None  # Basic auth doesn't retry


class BearerAuth(Authentication):
    """Bearer token authentication."""
    
    def __init__(
        self,
        token: str,
        token_refresher: Optional[Callable[[], Awaitable[str]]] = None
    ):
        self.token = token
        self.token_refresher = token_refresher
    
    async def authenticate(self, request: Request) -> Request:
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request
    
    async def handle_401(self, response: Response) -> Optional[Request]:
        if self.token_refresher:
            self.token = await self.token_refresher()
            return response.request.clone()
        return None


class ApiKeyAuth(Authentication):
    """API Key authentication."""
    
    def __init__(
        self,
        api_key: str,
        header_name: str = "X-API-Key",
        in_query: bool = False,
        query_param_name: str = "api_key"
    ):
        self.api_key = api_key
        self.header_name = header_name
        self.in_query = in_query
        self.query_param_name = query_param_name
    
    async def authenticate(self, request: Request) -> Request:
        if self.in_query:
            if request.params is None:
                request.params = {}
            request.params[self.query_param_name] = self.api_key
        else:
            request.headers[self.header_name] = self.api_key
        return request
    
    async def handle_401(self, response: Response) -> Optional[Request]:
        return None


class OAuth2Auth(Authentication):
    """
    OAuth2 authentication with automatic token refresh.
    
    Supports client credentials and refresh token flows.
    """
    
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_url: str,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        scope: Optional[str] = None
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = token_url
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.scope = scope
        self.token_expires_at: Optional[datetime] = None
        self._lock = asyncio.Lock()
    
    async def authenticate(self, request: Request) -> Request:
        async with self._lock:
            if self._token_expired():
                await self._refresh_access_token()
        
        request.headers["Authorization"] = f"Bearer {self.access_token}"
        return request
    
    def _token_expired(self) -> bool:
        if self.access_token is None:
            return True
        if self.token_expires_at is None:
            return False
        return datetime.utcnow() >= self.token_expires_at - timedelta(seconds=30)
    
    async def _refresh_access_token(self) -> None:
        # This would make an actual HTTP request in real implementation
        pass
    
    async def handle_401(self, response: Response) -> Optional[Request]:
        async with self._lock:
            await self._refresh_access_token()
        return response.request.clone()


class Middleware(ABC):
    """
    Abstract base class for HTTP client middleware.
    
    Middleware can intercept requests and responses for cross-cutting
    concerns like logging, metrics, caching, and transformations.
    """
    
    @abstractmethod
    async def process_request(self, request: Request) -> Request:
        """Process request before sending."""
        pass
    
    @abstractmethod
    async def process_response(
        self,
        response: Response,
        request: Request
    ) -> Response:
        """Process response after receiving."""
        pass
    
    async def process_error(
        self,
        error: Exception,
        request: Request
    ) -> None:
        """Handle errors during request processing."""
        pass


class LoggingMiddleware(Middleware):
    """Middleware for logging requests and responses."""
    
    def __init__(
        self,
        logger: Optional[logging.Logger] = None,
        log_body: bool = False,
        max_body_length: int = 1000
    ):
        self.logger = logger or logging.getLogger(__name__)
        self.log_body = log_body
        self.max_body_length = max_body_length
    
    async def process_request(self, request: Request) -> Request:
        self.logger.info(
            f"Request: {request.method.value} {request.url} "
            f"[{request.request_id}]"
        )
        if self.log_body and request.body:
            body_preview = str(request.body)[:self.max_body_length]
            self.logger.debug(f"Request body: {body_preview}")
        return request
    
    async def process_response(
        self,
        response: Response,
        request: Request
    ) -> Response:
        self.logger.info(
            f"Response: {response.status_code} {request.url} "
            f"[{request.request_id}] ({response.elapsed:.3f}s)"
        )
        if self.log_body:
            body_preview = response.text()[:self.max_body_length]
            self.logger.debug(f"Response body: {body_preview}")
        return response
    
    async def process_error(
        self,
        error: Exception,
        request: Request
    ) -> None:
        self.logger.error(
            f"Error: {type(error).__name__}: {error} "
            f"[{request.request_id}]"
        )


class MetricsMiddleware(Middleware):
    """Middleware for collecting HTTP metrics."""
    
    def __init__(self):
        self.request_count: Dict[str, int] = defaultdict(int)
        self.response_times: Dict[str, List[float]] = defaultdict(list)
        self.status_codes: Dict[int, int] = defaultdict(int)
        self.error_count: Dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()
    
    async def process_request(self, request: Request) -> Request:
        async with self._lock:
            self.request_count[request.url] += 1
        return request
    
    async def process_response(
        self,
        response: Response,
        request: Request
    ) -> Response:
        async with self._lock:
            self.response_times[request.url].append(response.elapsed)
            self.status_codes[response.status_code] += 1
        return response
    
    async def process_error(
        self,
        error: Exception,
        request: Request
    ) -> None:
        async with self._lock:
            self.error_count[type(error).__name__] += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get collected metrics."""
        return {
            "total_requests": sum(self.request_count.values()),
            "requests_by_url": dict(self.request_count),
            "status_codes": dict(self.status_codes),
            "errors": dict(self.error_count),
            "avg_response_time": self._avg_response_time()
        }
    
    def _avg_response_time(self) -> float:
        all_times = []
        for times in self.response_times.values():
            all_times.extend(times)
        return sum(all_times) / len(all_times) if all_times else 0


class RetryMiddleware(Middleware):
    """
    Middleware for automatic request retries.
    
    Implements exponential backoff and configurable retry conditions.
    """
    
    def __init__(
        self,
        max_retries: int = 3,
        retry_statuses: Set[int] = None,
        backoff_factor: float = 0.5,
        max_backoff: float = 30.0
    ):
        self.max_retries = max_retries
        self.retry_statuses = retry_statuses or {500, 502, 503, 504}
        self.backoff_factor = backoff_factor
        self.max_backoff = max_backoff
    
    async def process_request(self, request: Request) -> Request:
        request.metadata['retry_count'] = 0
        return request
    
    async def process_response(
        self,
        response: Response,
        request: Request
    ) -> Response:
        return response
    
    def should_retry(self, response: Response, attempt: int) -> bool:
        """Determine if request should be retried."""
        if attempt >= self.max_retries:
            return False
        return response.status_code in self.retry_statuses
    
    def get_backoff_time(self, attempt: int) -> float:
        """Calculate backoff time for attempt."""
        backoff = self.backoff_factor * (2 ** attempt)
        return min(backoff, self.max_backoff)


class CacheMiddleware(Middleware):
    """
    Middleware for response caching.
    
    Caches GET requests based on URL and headers, respecting
    cache-control directives.
    """
    
    def __init__(
        self,
        max_size: int = 1000,
        default_ttl: int = 300,
        cacheable_methods: Set[HttpMethod] = None,
        cacheable_statuses: Set[int] = None
    ):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.cacheable_methods = cacheable_methods or {HttpMethod.GET}
        self.cacheable_statuses = cacheable_statuses or {200, 301, 308}
        self._cache: Dict[str, Tuple[Response, float]] = {}
        self._lock = asyncio.Lock()
    
    def _cache_key(self, request: Request) -> str:
        """Generate cache key for request."""
        key_parts = [request.method.value, request.full_url]
        # Include Vary headers in key
        return hashlib.sha256(":".join(key_parts).encode()).hexdigest()
    
    async def process_request(self, request: Request) -> Request:
        if request.method not in self.cacheable_methods:
            return request
        
        cache_key = self._cache_key(request)
        async with self._lock:
            if cache_key in self._cache:
                response, expires_at = self._cache[cache_key]
                if time.time() < expires_at:
                    request.metadata['cache_hit'] = True
                    request.metadata['cached_response'] = response
                else:
                    del self._cache[cache_key]
        
        return request
    
    async def process_response(
        self,
        response: Response,
        request: Request
    ) -> Response:
        if request.method not in self.cacheable_methods:
            return response
        
        if response.status_code not in self.cacheable_statuses:
            return response
        
        # Check cache-control
        cache_control = response.headers.get("cache-control", "")
        if "no-store" in cache_control or "no-cache" in cache_control:
            return response
        
        # Calculate TTL
        ttl = self.default_ttl
        max_age_match = re.search(r'max-age=(\d+)', cache_control)
        if max_age_match:
            ttl = int(max_age_match.group(1))
        
        # Store in cache
        cache_key = self._cache_key(request)
        async with self._lock:
            self._cache[cache_key] = (response, time.time()