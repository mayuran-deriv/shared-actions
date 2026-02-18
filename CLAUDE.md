# Claude Integration Documentation

## Doc Sync Agent

The Doc Sync Agent is a GitHub Action that uses Claude to analyze code changes and automatically update documentation when necessary.

### Purpose

This action helps maintain up-to-date documentation by:
- Analyzing code changes in pull requests
- Determining if documentation updates are needed
- Generating appropriate documentation updates
- Creating pull requests with documentation changes

### Prompt Strategy

The Doc Sync Agent uses a carefully designed prompt that instructs Claude to:

1. Be proactive about documenting significant new additions:
   - New applications, projects, or major features
   - New directories containing standalone applications
   - Complete rewrites or replacements of existing functionality
   - New public APIs, tools, or utilities

2. Be conservative about minor changes, avoiding documentation updates for:
   - Minor bug fixes that don't change functionality
   - Small UI tweaks (styling, colors, spacing)
   - Internal code refactoring
   - Dependency version bumps
   - Code formatting or linting changes
   - Internal variable/function renames
   - Performance optimizations that don't affect usage

### Usage

The Doc Sync Agent is typically integrated into CI/CD workflows that run on pull request events. See the action.yml file for detailed configuration options.
