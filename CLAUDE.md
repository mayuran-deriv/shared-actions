# Claude Documentation

## Overview

This document provides information about the Claude AI integration within this repository, specifically focusing on the doc_sync_agent GitHub Action.

## Doc Sync Agent

The doc_sync_agent is a GitHub Action that automatically analyzes code changes and suggests documentation updates. It leverages Claude AI to intelligently determine when documentation needs to be updated based on code changes.

### Workflow Configuration

The doc_sync_agent is configured in `.github/workflows/test-doc-sync.yml` with the following trigger conditions:

- Push events to the `master` branch
- Pull request events when merged to the `master` branch
- Manual triggering via workflow_dispatch

### Usage

The action is used internally and runs automatically when code is pushed or PRs are merged to master. It can also be triggered manually through the GitHub Actions interface.

### Configuration Parameters

The doc_sync_agent accepts the following parameters:

- `github_token`: GitHub token for authentication
- `anthropic_api_key`: API key for Claude AI service
- `slack_webhook_url`: Optional webhook for Slack notifications
- `slack_users_to_tag`: Optional Slack user IDs to notify
- `repository`: Repository name
- `commit_sha`: Commit SHA to analyze
- `base_branch`: Target branch for documentation PRs (defaults to master)

### Behavior

When triggered, the doc_sync_agent:

1. Analyzes recent code changes
2. Determines if documentation updates are needed
3. Generates appropriate documentation updates
4. Creates a pull request with the suggested changes
5. Optionally notifies specified users via Slack

## Repository Structure

This repository contains:

- A calculator application (in `./calculator-app`)
- GitHub Actions for documentation synchronization

## Weather App

Despite the folder name suggesting a calculator app, the package.json indicates this is actually a Simple React Weather App. This application is located in the `./calculator-app` directory.
