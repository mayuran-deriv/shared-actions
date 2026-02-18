# Doc Sync Agent

The Doc Sync Agent is a GitHub Action workflow that automatically synchronizes documentation based on code changes. This document explains how the agent works and how to use it in your projects.

## Overview

The Doc Sync Agent is designed to keep documentation up-to-date by analyzing code changes and determining if documentation updates are needed. It can be triggered automatically on pull request merges or manually through workflow dispatch.

## Repository Structure

This repository contains:

- **GitHub Actions**: Reusable workflows that can be shared across repositories
  - `doc_sync_agent`: Analyzes code changes and updates documentation
- **Applications**:
  - `calculator-app`: A simple calculator application (appears to be named "weather-app" in package.json)

## How Doc Sync Agent Works

The Doc Sync Agent:

1. Analyzes code changes in pull requests
2. Determines if documentation updates are needed
3. Generates or updates documentation files as necessary

## Usage

To use the Doc Sync Agent in your workflow:

```yaml
- name: Run Doc Sync Agent
  uses: mayuran-deriv/shared-actions/.github/actions/doc_sync_agent@master
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
```

## Configuration

The Doc Sync Agent can be configured with the following inputs:

- `github_token`: GitHub token for API access (required)

## Workflow Example

The repository includes a test workflow (`test-doc-sync.yml`) that demonstrates how to use the Doc Sync Agent. This workflow runs on pull request merges to the master branch or can be triggered manually.

## Applications

### Weather App (calculator-app)

A simple React Weather application. Despite the folder name being "calculator-app", the package.json indicates this is a weather application.

## Contributing

When making changes to the Doc Sync Agent or other shared actions, ensure that you test your changes thoroughly before merging to master, as these actions may be used by multiple repositories.
