# Claude Integration Documentation

## Doc Sync Agent

The Doc Sync Agent is a GitHub Action that automatically updates documentation based on code changes. It uses Claude AI to analyze code diffs and make minimal, targeted updates to documentation files.

### Key Features

- Preserves existing documentation content
- Makes only minimal necessary changes
- Validates changes to ensure original content is preserved
- Supports README.md and CLAUDE.md updates

### Usage Guidelines

The Doc Sync Agent follows strict rules when updating documentation:

- It preserves 100% of existing documentation content
- It only adds new content where necessary
- It matches the existing documentation style
- It only updates documentation for new features, APIs, or breaking changes
