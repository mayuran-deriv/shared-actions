# Claude Integration Documentation

## Overview
This document describes the Claude AI integration within this repository, particularly focusing on the documentation synchronization workflow.

## doc_sync_agent

The `doc_sync_agent` is a GitHub Action that leverages Claude to automatically update documentation based on code changes. It analyzes code diffs and determines if documentation updates are needed.

### Workflow Behavior

The doc_sync_agent is configured to run only in specific circumstances:

1. When triggered by a merge commit (commits with multiple parents)
2. When manually triggered via workflow dispatch

This selective execution ensures documentation is only updated when meaningful changes are integrated into the codebase, typically through pull request merges.

### Implementation Details

The workflow:
1. Checks out the repository code
2. Determines if the current commit is a merge commit by checking for multiple parent commits
3. Only proceeds with documentation synchronization if the commit is a merge commit or if the workflow was manually triggered

### Usage

The doc_sync_agent is typically used in a GitHub Actions workflow file. It requires a GitHub token for authentication and repository access.

```yaml
- name: Run Doc Sync Agent
  if: steps.check-merge.outputs.is_merge == 'true' || github.event_name == 'workflow_dispatch'
  uses: ./.github/actions/doc_sync_agent
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
```

## Best Practices

When working with the Claude-powered documentation sync:

1. Make meaningful commit messages that clearly describe your changes
2. Group related changes in a single PR to help Claude understand the context
3. For significant feature additions or API changes, consider adding inline comments that explain the purpose
4. Review Claude's documentation updates to ensure accuracy

## Troubleshooting

If the doc_sync_agent isn't running as expected:

1. Verify the commit is a merge commit (from a merged PR)
2. Check the GitHub Actions logs for any error messages
3. You can always manually trigger the workflow using the "workflow_dispatch" event
