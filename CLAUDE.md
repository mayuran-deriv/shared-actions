# Claude Documentation

## Doc Sync Agent

The Doc Sync Agent is a GitHub Action that automatically updates documentation based on code changes. It uses Claude to analyze code diffs and determine if documentation updates are needed.

### Key Features

- Analyzes code changes to identify when documentation updates are needed
- Makes minimal, targeted updates to documentation without changing existing content
- Validates changes to ensure original documentation is preserved
- Supports both README.md and CLAUDE.md files

### Usage Guidelines

The Doc Sync Agent follows strict rules to ensure documentation integrity:

1. **Preserves existing content** - Never removes or rephrases existing documentation
2. **Makes minimal changes** - Only adds new content where necessary
3. **Matches existing style** - New content follows the same formatting patterns

### When Updates Are Made

The agent will update documentation for:
- New features/applications that users need to know about
- New APIs, commands, or usage instructions
- Breaking changes that affect existing documented features
- New installation/setup requirements

It will NOT update documentation for:
- Internal refactoring
- Bug fixes (unless they change documented behavior)
- Code style/formatting changes
- Dependency updates (unless they affect setup instructions)
- Test changes
- Performance optimizations
- Internal variable/function renames
