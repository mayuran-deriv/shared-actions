## Shared Actions Repository

This repository is dedicated to hosting reusable GitHub Actions YAML files that can be shared across different repositories. Centralizing common actions, to promote consistency and efficiency in workflows.

### Available Actions

#### doc_sync_agent
An action that analyzes code changes and automatically updates documentation when necessary. It uses Claude AI to determine if documentation updates are needed based on code changes and generates appropriate documentation content.

#### Example Usage

```
      - name: Post preview build comment
        id: post_preview_build_comment
        uses: "deriv-com/shared-actions/.github/actions/post_preview_build_comment@master"
        with:
          issue_number: ${{steps.pr_information.outputs.issue_number}}
          head_sha: ${{github.event.workflow_run.head_sha}}
```

### Repository Structure

This repository contains:
- GitHub Actions in the `.github/actions` directory
- A calculator application in the `calculator-app` directory (though package.json suggests it may be a weather app)
