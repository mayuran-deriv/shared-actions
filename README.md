## Shared Actions Repository

This repository is dedicated to hosting reusable GitHub Actions YAML files that can be shared across different repositories. Centralizing common actions, to promote consistency and efficiency in workflows.

### Applications

#### Weather App
A simple React Weather application located in the `calculator-app` directory (note: the directory name doesn't match the actual application).

### GitHub Actions

#### doc_sync_agent
An action that synchronizes documentation based on code changes. This action only runs on merge commits or when manually triggered via workflow dispatch.

#### Example Usage

```
      - name: Post preview build comment
        id: post_preview_build_comment
        uses: "deriv-com/shared-actions/.github/actions/post_preview_build_comment@master"
        with:
          issue_number: ${{steps.pr_information.outputs.issue_number}}
          head_sha: ${{github.event.workflow_run.head_sha}}
```
