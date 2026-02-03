## Shared Actions Repository

This repository is dedicated to hosting reusable GitHub Actions YAML files that can be shared across different repositories. Centralizing common actions, to promote consistency and efficiency in workflows.

#### Example Usage

```
      - name: Post preview build comment
        id: post_preview_build_comment
        uses: "deriv-com/shared-actions/.github/actions/post_preview_build_comment@master"
        with:
          issue_number: ${{steps.pr_information.outputs.issue_number}}
          head_sha: ${{github.event.workflow_run.head_sha}}
```

#### Available Actions

##### Schema Validator

A comprehensive data validation library for Python with support for nested objects, custom validators, and detailed error reporting.

```python
from schema_validator import Schema, StringValidator, IntegerValidator, EmailValidator

user_schema = Schema({
    "username": StringValidator(min_length=3, max_length=50),
    "email": EmailValidator(),
    "age": IntegerValidator(minimum=0, maximum=150, required=False)
})

result = user_schema.validate({"username": "john_doe", "email": "john@example.com", "age": 30})
if result.is_valid:
    print("Valid data:", result.validated_data)
else:
    print("Validation errors:", result.errors)
```
