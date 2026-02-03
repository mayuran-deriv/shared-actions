# Claude AI Integration Documentation

## doc_sync_agent

### Overview
The `doc_sync_agent` is a GitHub Action that leverages Claude AI to automatically analyze code changes and update documentation when necessary. It determines if documentation updates are needed based on the nature of code changes and generates appropriate documentation content.

### How It Works

1. **Change Detection**: The action analyzes the differences between commits to identify what has changed.

2. **Repository Context Collection**: Gathers information about the repository structure including:
   - Directory structure (up to 3 levels deep)
   - Key files (markdown, package.json, config files)
   - Package information from package.json files
   - List of GitHub Actions

3. **Documentation Analysis**: Uses Claude AI to determine if the README.md or CLAUDE.md files need updates based on the changes.

4. **Documentation Generation**: If updates are needed, Claude generates comprehensive documentation content.

### When Documentation Updates Occur

The agent is proactive about documenting:
- New applications, projects, or major features
- New directories containing standalone applications
- Complete rewrites or replacements of existing functionality
- New public APIs, tools, or utilities

It is conservative about minor changes and will not update documentation for:
- Minor bug fixes that don't change functionality
- Small UI tweaks
- Internal code refactoring
- Dependency version bumps
- Code formatting changes
- Internal variable/function renames
- Performance optimizations that don't affect usage

### Implementation Details

The action uses a sophisticated prompt engineering approach to guide Claude in making appropriate decisions about documentation updates. It provides Claude with:

- Repository context (structure, key files, package information)
- Code changes (diff between commits)
- Current documentation content
- Clear guidelines on when to update documentation

When creating new documentation files, Claude uses the full repository context to create comprehensive documentation covering the entire project, not just recent changes.
