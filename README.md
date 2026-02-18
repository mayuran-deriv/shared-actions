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

### Schema Validator

A comprehensive data validation library for Python with support for nested objects, custom validators, and detailed error reporting.

#### Features
- Type validation (strings, integers, emails, etc.)
- Nested object validation
- Custom validation rules
- Detailed error reporting
