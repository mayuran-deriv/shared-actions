# Claude AI Integration

This document describes the Claude AI integration components in this repository, including GitHub Actions that leverage Claude for automated tasks.

## Overview

This repository contains a calculator application and GitHub Actions that utilize Claude AI for automated documentation synchronization.

## Applications

### Weather App

A simple React Weather application located in the `calculator-app` directory. Despite the directory name, the package.json identifies this as a weather application.

## GitHub Actions

### doc_sync_agent

The `doc_sync_agent` GitHub Action automates documentation updates by analyzing code changes and determining if documentation needs to be updated.

#### Features

- Analyzes code changes to determine documentation impact
- Makes intelligent decisions about what warrants documentation updates
- Generates high-quality documentation content when needed
- Handles both new documentation files and updates to existing ones

#### Behavior

- For new documentation files: Documents the entire repository comprehensively
- For existing documentation files: Updates only relevant sections affected by changes
- Proactively documents significant new additions (new applications, features, etc.)
- Conservative about documenting minor changes (bug fixes, styling changes, etc.)

#### Usage

This action is typically used in documentation workflows to keep documentation in sync with code changes.
