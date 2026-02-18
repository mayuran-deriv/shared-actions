# Claude AI Integration

This document provides information about Claude AI integration within this repository, including GitHub Actions that leverage Claude for automated tasks.

## Repository Overview

This repository contains:

1. A Weather App (React-based application)
2. GitHub Actions for automation

## GitHub Actions

### doc_sync_agent

The `doc_sync_agent` is a GitHub Action that uses Claude AI to automatically analyze code changes and update documentation when necessary. It intelligently determines when documentation updates are needed based on the significance of code changes.

#### Features

- Analyzes code diffs to identify significant changes
- Makes intelligent decisions about what warrants documentation updates
- Generates high-quality documentation content when needed
- Handles both new documentation files and updates to existing ones
- Preserves existing documentation style and structure

#### Behavior

- For new documentation files: Creates comprehensive documentation covering the entire repository
- For existing documentation files: Updates only relevant sections affected by code changes
- Proactively documents significant new additions (new applications, features, APIs)
- Conservative about documenting minor changes (bug fixes, styling, internal refactoring)

## Weather App

The repository includes a simple React-based Weather App. This application is defined in the `calculator-app` directory (note: the directory name appears to be inconsistent with the package name).

## Development Guidelines for AI-Assisted Documentation

When working with the Claude-powered documentation sync:

1. Make meaningful commit messages that clearly describe your changes
2. For significant new features or components, consider adding initial documentation manually
3. The AI will help maintain documentation, but human review is still important
4. The absence of prior documentation is not a reason to skip documenting important new additions
