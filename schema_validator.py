# src/schema_validator/__init__.py
"""
Schema Validator - A comprehensive data validation library for Python.

This module provides a robust schema validation system with support for
nested objects, custom validators, and detailed error reporting.

Version: 1.0.0
Author: Development Team
"""

from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional, Type, Union
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
import re
from datetime import datetime


class ValidationError(Exception):
    """Raised when validation fails with detailed error information."""
    
    def __init__(self, message: str, field_path: str = "", errors: List[Dict] = None):
        self.message = message
        self.field_path = field_path
        self.errors = errors or []
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary representation."""
        return {
            "message": self.message,
            "field_path": self.field_path,
            "errors": self.errors
        }


class ValidatorType(Enum):
    """Enumeration of built-in validator types."""
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    EMAIL = "email"
    URL = "url"
    UUID = "uuid"
    DATE = "date"
    DATETIME = "datetime"
    LIST = "list"
    DICT = "dict"
    ANY = "any"


@dataclass
class ValidationResult:
    """
    Represents the result of a validation operation.
    
    Attributes:
        is_valid: Whether the validation passed
        errors: List of validation errors encountered
        validated_data: The cleaned/coerced data after validation
        metadata: Additional metadata about the validation process
    """
    is_valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    validated_data: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def raise_on_error(self) -> None:
        """Raise ValidationError if validation failed."""
        if not self.is_valid and self.errors:
            raise ValidationError(
                message="Validation failed",
                errors=[e.to_dict() for e in self.errors]
            )


class BaseValidator(ABC):
    """
    Abstract base class for all validators.
    
    Implement this class to create custom validators with specific
    validation logic for your use cases.
    """
    
    def __init__(
        self,
        required: bool = True,
        nullable: bool = False,
        default: Any = None,
        description: str = ""
    ):
        self.required = required
        self.nullable = nullable
        self.default = default
        self.description = description
        self._custom_validators: List[Callable] = []
    
    @abstractmethod
    def _validate_type(self, value: Any) -> bool:
        """Validate that the value is of the correct type."""
        pass
    
    @abstractmethod
    def _coerce(self, value: Any) -> Any:
        """Attempt to coerce the value to the correct type."""
        pass
    
    def add_validator(self, func: Callable[[Any], bool], error_message: str = "") -> BaseValidator:
        """
        Add a custom validation function.
        
        Args:
            func: A callable that takes a value and returns True if valid
            error_message: Custom error message if validation fails
            
        Returns:
            Self for method chaining
        """
        self._custom_validators.append((func, error_message))
        return self
    
    def validate(self, value: Any, field_name: str = "field") -> ValidationResult:
        """
        Validate a value against this validator's rules.
        
        Args:
            value: The value to validate
            field_name: Name of the field for error messages
            
        Returns:
            ValidationResult with validation outcome
        """
        errors = []
        
        # Handle None values
        if value is None:
            if self.nullable:
                return ValidationResult(is_valid=True, validated_data=None)
            if not self.required:
                return ValidationResult(is_valid=True, validated_data=self.default)
            errors.append(ValidationError(f"{field_name} is required", field_name))
            return ValidationResult(is_valid=False, errors=errors)
        
        # Type validation
        if not self._validate_type(value):
            try:
                value = self._coerce(value)
            except (ValueError, TypeError):
                errors.append(ValidationError(
                    f"{field_name} has invalid type, expected {self.__class__.__name__}",
                    field_name
                ))
                return ValidationResult(is_valid=False, errors=errors)
        
        # Custom validators
        for validator_func, error_msg in self._custom_validators:
            if not validator_func(value):
                errors.append(ValidationError(
                    error_msg or f"{field_name} failed custom validation",
                    field_name
                ))
        
        if errors:
            return ValidationResult(is_valid=False, errors=errors)
        
        return ValidationResult(is_valid=True, validated_data=value)


class StringValidator(BaseValidator):
    """
    Validator for string values with support for length constraints and patterns.
    
    Features:
        - Minimum and maximum length validation
        - Regex pattern matching
        - Whitespace trimming options
        - Case transformation
    """
    
    def __init__(
        self,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        pattern: Optional[str] = None,
        trim: bool = True,
        lowercase: bool = False,
        uppercase: bool = False,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.min_length = min_length
        self.max_length = max_length
        self.pattern = re.compile(pattern) if pattern else None
        self.trim = trim
        self.lowercase = lowercase
        self.uppercase = uppercase
    
    def _validate_type(self, value: Any) -> bool:
        return isinstance(value, str)
    
    def _coerce(self, value: Any) -> str:
        return str(value)
    
    def validate(self, value: Any, field_name: str = "field") -> ValidationResult:
        result = super().validate(value, field_name)
        if not result.is_valid or result.validated_data is None:
            return result
        
        data = result.validated_data
        errors = []
        
        # Apply transformations
        if self.trim:
            data = data.strip()
        if self.lowercase:
            data = data.lower()
        if self.uppercase:
            data = data.upper()
        
        # Length validation
        if self.min_length is not None and len(data) < self.min_length:
            errors.append(ValidationError(
                f"{field_name} must be at least {self.min_length} characters",
                field_name
            ))
        
        if self.max_length is not None and len(data) > self.max_length:
            errors.append(ValidationError(
                f"{field_name} must be at most {self.max_length} characters",
                field_name
            ))
        
        # Pattern validation
        if self.pattern and not self.pattern.match(data):
            errors.append(ValidationError(
                f"{field_name} does not match required pattern",
                field_name
            ))
        
        if errors:
            return ValidationResult(is_valid=False, errors=errors)
        
        return ValidationResult(is_valid=True, validated_data=data)


class IntegerValidator(BaseValidator):
    """
    Validator for integer values with range constraints.
    
    Features:
        - Minimum and maximum value validation
        - Multiple-of validation
        - Automatic type coercion from strings
    """
    
    def __init__(
        self,
        minimum: Optional[int] = None,
        maximum: Optional[int] = None,
        multiple_of: Optional[int] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.minimum = minimum
        self.maximum = maximum
        self.multiple_of = multiple_of
    
    def _validate_type(self, value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)
    
    def _coerce(self, value: Any) -> int:
        return int(value)
    
    def validate(self, value: Any, field_name: str = "field") -> ValidationResult:
        result = super().validate(value, field_name)
        if not result.is_valid or result.validated_data is None:
            return result
        
        data = result.validated_data
        errors = []
        
        if self.minimum is not None and data < self.minimum:
            errors.append(ValidationError(
                f"{field_name} must be at least {self.minimum}",
                field_name
            ))
        
        if self.maximum is not None and data > self.maximum:
            errors.append(ValidationError(
                f"{field_name} must be at most {self.maximum}",
                field_name
            ))
        
        if self.multiple_of is not None and data % self.multiple_of != 0:
            errors.append(ValidationError(
                f"{field_name} must be a multiple of {self.multiple_of}",
                field_name
            ))
        
        if errors:
            return ValidationResult(is_valid=False, errors=errors)
        
        return ValidationResult(is_valid=True, validated_data=data)


class EmailValidator(StringValidator):
    """
    Specialized validator for email addresses.
    
    Validates email format and optionally checks for allowed domains.
    """
    
    EMAIL_PATTERN = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    def __init__(self, allowed_domains: Optional[List[str]] = None, **kwargs):
        super().__init__(pattern=self.EMAIL_PATTERN, lowercase=True, **kwargs)
        self.allowed_domains = allowed_domains
    
    def validate(self, value: Any, field_name: str = "field") -> ValidationResult:
        result = super().validate(value, field_name)
        if not result.is_valid or result.validated_data is None:
            return result
        
        if self.allowed_domains:
            domain = result.validated_data.split('@')[1]
            if domain not in self.allowed_domains:
                return ValidationResult(
                    is_valid=False,
                    errors=[ValidationError(
                        f"{field_name} must be from allowed domains: {self.allowed_domains}",
                        field_name
                    )]
                )
        
        return result


class ListValidator(BaseValidator):
    """
    Validator for list/array values.
    
    Features:
        - Item type validation using nested validators
        - Minimum and maximum item count
        - Unique item enforcement
    """
    
    def __init__(
        self,
        item_validator: Optional[BaseValidator] = None,
        min_items: Optional[int] = None,
        max_items: Optional[int] = None,
        unique_items: bool = False,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.item_validator = item_validator
        self.min_items = min_items
        self.max_items = max_items
        self.unique_items = unique_items
    
    def _validate_type(self, value: Any) -> bool:
        return isinstance(value, list)
    
    def _coerce(self, value: Any) -> list:
        return list(value)
    
    def validate(self, value: Any, field_name: str = "field") -> ValidationResult:
        result = super().validate(value, field_name)
        if not result.is_valid or result.validated_data is None:
            return result
        
        data = result.validated_data
        errors = []
        validated_items = []
        
        # Length validation
        if self.min_items is not None and len(data) < self.min_items:
            errors.append(ValidationError(
                f"{field_name} must have at least {self.min_items} items",
                field_name
            ))
        
        if self.max_items is not None and len(data) > self.max_items:
            errors.append(ValidationError(
                f"{field_name} must have at most {self.max_items} items",
                field_name
            ))
        
        # Unique items check
        if self.unique_items:
            seen = set()
            for item in data:
                item_hash = str(item)
                if item_hash in seen:
                    errors.append(ValidationError(
                        f"{field_name} contains duplicate items",
                        field_name
                    ))
                    break
                seen.add(item_hash)
        
        # Item validation
        if self.item_validator:
            for i, item in enumerate(data):
                item_result = self.item_validator.validate(item, f"{field_name}[{i}]")
                if item_result.is_valid:
                    validated_items.append(item_result.validated_data)
                else:
                    errors.extend(item_result.errors)
        else:
            validated_items = data
        
        if errors:
            return ValidationResult(is_valid=False, errors=errors)
        
        return ValidationResult(is_valid=True, validated_data=validated_items)


class Schema:
    """
    Main schema class for defining and validating complex data structures.
    
    A Schema represents a structured data format with multiple fields,
    each with its own validation rules.
    
    Example:
        >>> user_schema = Schema({
        ...     "name": StringValidator(min_length=1, max_length=100),
        ...     "email": EmailValidator(),
        ...     "age": IntegerValidator(minimum=0, maximum=150)
        ... })
        >>> result = user_schema.validate({"name": "John", "email": "john@example.com", "age": 30})
        >>> print(result.is_valid)
        True
    """
    
    def __init__(
        self,
        fields: Dict[str, BaseValidator],
        strict: bool = False,
        allow_extra: bool = True
    ):
        """
        Initialize a new Schema.
        
        Args:
            fields: Dictionary mapping field names to validators
            strict: If True, fail on any extra fields not in schema
            allow_extra: If True, include extra fields in output (when not strict)
        """
        self.fields = fields
        self.strict = strict
        self.allow_extra = allow_extra
    
    def validate(self, data: Dict[str, Any]) -> ValidationResult:
        """
        Validate a dictionary against this schema.
        
        Args:
            data: The dictionary to validate
            
        Returns:
            ValidationResult with validation outcome and cleaned data
        """
        if not isinstance(data, dict):
            return ValidationResult(
                is_valid=False,
                errors=[ValidationError("Input must be a dictionary", "root")]
            )
        
        errors = []
        validated_data = {}
        
        # Check for extra fields in strict mode
        if self.strict:
            extra_fields = set(data.keys()) - set(self.fields.keys())
            if extra_fields:
                errors.append(ValidationError(
                    f"Unexpected fields: {extra_fields}",
                    "root"
                ))
        
        # Validate each field
        for field_name, validator in self.fields.items():
            value = data.get(field_name)
            result = validator.validate(value, field_name)
            
            if result.is_valid:
                validated_data[field_name] = result.validated_data
            else:
                errors.extend(result.errors)
        
        # Include extra fields if allowed
        if self.allow_extra and not self.strict:
            for key, value in data.items():
                if key not in self.fields:
                    validated_data[key] = value
        
        if errors:
            return ValidationResult(is_valid=False, errors=errors)
        
        return ValidationResult(is_valid=True, validated_data=validated_data)
    
    def extend(self, additional_fields: Dict[str, BaseValidator]) -> Schema:
        """
        Create a new schema by extending this one with additional fields.
        
        Args:
            additional_fields: New fields to add to the schema
            
        Returns:
            A new Schema instance with combined fields
        """
        combined_fields = {**self.fields, **additional_fields}
        return Schema(combined_fields, self.strict, self.allow_extra)


class SchemaRegistry:
    """
    Registry for managing multiple schemas with versioning support.
    
    Useful for API versioning and maintaining backward compatibility.
    """
    
    def __init__(self):
        self._schemas: Dict[str, Dict[str, Schema]] = {}
    
    def register(self, name: str, schema: Schema, version: str = "1.0") -> None:
        """
        Register a schema with a name and version.
        
        Args:
            name: Unique name for the schema
            schema: The Schema instance to register
            version: Version string for the schema
        """
        if name not in self._schemas:
            self._schemas[name] = {}
        self._schemas[name][version] = schema
    
    def get(self, name: str, version: str = "1.0") -> Optional[Schema]:
        """
        Retrieve a schema by name and version.
        
        Args:
            name: Name of the schema
            version: Version to retrieve
            
        Returns:
            The Schema if found, None otherwise
        """
        return self._schemas.get(name, {}).get(version)
    
    def get_latest(self, name: str) -> Optional[Schema]:
        """
        Get the latest version of a schema.
        
        Args:
            name: Name of the schema
            
        Returns:
            The latest version of the Schema if found
        """
        versions = self._schemas.get(name, {})
        if not versions:
            return None
        latest_version = sorted(versions.keys())[-1]
        return versions[latest_version]
    
    def list_schemas(self) -> Dict[str, List[str]]:
        """
        List all registered schemas and their versions.
        
        Returns:
            Dictionary mapping schema names to lists of versions
        """
        return {name: list(versions.keys()) for name, versions in self._schemas.items()}


# Convenience function for quick validation
def validate(data: Any, schema: Union[Schema, Dict[str, BaseValidator]]) -> ValidationResult:
    """
    Convenience function to validate data against a schema.
    
    Args:
        data: The data to validate
        schema: Either a Schema instance or a dict of validators
        
    Returns:
        ValidationResult with validation outcome
    """
    if isinstance(schema, dict):
        schema = Schema(schema)
    return schema.validate(data)


# Pre-built common schemas
COMMON_SCHEMAS = {
    "user": Schema({
        "id": IntegerValidator(minimum=1, required=False),
        "username": StringValidator(min_length=3, max_length=50),
        "email": EmailValidator(),
        "age": IntegerValidator(minimum=0, maximum=150, required=False),
    }),
    "address": Schema({
        "street": StringValidator(max_length=200),
        "city": StringValidator(max_length=100),
        "country": StringValidator(min_length=2, max_length=100),
        "postal_code": StringValidator(pattern=r'^[A-Za-z0-9\s-]{3,10}$'),
    }),
}


__all__ = [
    "ValidationError",
    "ValidationResult", 
    "ValidatorType",
    "BaseValidator",
    "StringValidator",
    "IntegerValidator",
    "EmailValidator",
    "ListValidator",
    "Schema",
    "SchemaRegistry",
    "validate",
    "COMMON_SCHEMAS",
]