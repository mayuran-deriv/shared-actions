# Claude Documentation

## Overview

This document provides information about the Claude AI integration in this repository, specifically focusing on the doc_sync_agent GitHub Action that uses Claude to automate documentation updates.

## Doc Sync Agent

The doc_sync_agent is a GitHub Action that automatically analyzes code changes and updates documentation when necessary. It leverages Claude AI to intelligently determine when documentation updates are needed and to generate appropriate content.

### Workflow Configuration

The doc_sync_agent is configured in the `.github/workflows/test-doc-sync.yml` file with the following triggers:

- Push events to the `master` branch
- Pull request events when merged to the `master` branch
- Manual triggering via workflow_dispatch

### Usage

To use the doc_sync_agent in your repository:

1. Reference the action in your workflow file:
   ```yaml
   - name: Run Doc Sync Agent
     uses: mayuran-deriv/shared-actions/.github/actions/doc_sync_agent@master
     with:
       openai_api_key: ${{ secrets.OPENAI_API_KEY }}
       github_token: ${{ secrets.GITHUB_TOKEN }}
       slack_webhook_url: ${{ secrets.SLACK_WEBHOOK_URL }}  # Optional
       slack_users_to_tag: ${{ secrets.SLACK_USERS_TO_TAG }}  # Optional
       repository: ${{ github.repository }}
       commit_sha: ${{ github.sha }}
       base_branch: master  # Documentation PRs will target master branch
   ```

2. Ensure you have the necessary secrets configured in your repository settings.

### Parameters

- `openai_api_key`: API key for OpenAI (Claude) integration
- `github_token`: GitHub token for repository access
- `slack_webhook_url`: (Optional) Webhook URL for Slack notifications
- `slack_users_to_tag`: (Optional) Slack user IDs to tag in notifications
- `repository`: Repository name in format `owner/repo`
- `commit_sha`: SHA of the commit to analyze
- `base_branch`: Target branch for documentation PRs (typically master)

### Behavior

The doc_sync_agent:

1. Analyzes code changes in commits or merged PRs
2. Determines if documentation updates are needed
3. Generates appropriate documentation content when necessary
4. Creates a PR with the documentation changes
5. Sends Slack notifications if configured

## Repository Projects

### Calculator App

The repository contains a calculator application located in the `calculator-app` directory. Based on the package.json, it appears this may actually be a Weather App built with React and Vite.

#### Features
- Simple React-based application
- Built using Vite for fast development

#### Development
The application uses standard npm commands for development:
```bash
npm install
npm run dev
```

## Contributing to Claude Integration

When modifying the doc_sync_agent or other Claude-related functionality:

1. Test changes thoroughly using the test workflow
2. Ensure prompts are clear and provide sufficient context
3. Consider edge cases in documentation analysis
4. Update this documentation with any changes to parameters or behavior
