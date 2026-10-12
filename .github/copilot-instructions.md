# Project Guidelines

## Project
- This is a Python Django application.
- Use Poetry for dependency management and running project commands.
- Follow the existing project structure and conventions.
- Do not introduce new dependencies unless they are clearly necessary.

## Dependencies
- Manage dependencies through Poetry.
- Do not manually modify dependency versions without a clear reason.
- Do not use pip to modify the project's dependency state.

## Django
- Follow existing Django conventions and patterns.
- Keep changes focused and avoid unnecessary architectural changes.
- Do not modify database schemas or migrations unless required by the task.
- When changing models, ensure the corresponding migrations are handled appropriately.

## Testing and validation
- Inspect the repository to identify the existing test, lint, formatting, and type-checking commands.
- Run the relevant validation commands before considering a change complete.
- Do not invent new tooling unless explicitly requested.

## Git
- Keep changes small and focused.
- Do not modify unrelated files.
- Do not commit directly to the main/master branch.
- Create a dedicated branch for changes.
- Do not merge pull requests.

## Technical debt
When working in an area of the codebase, look for small, concrete technical-debt issues as part of normal implementation and review. If you discover an issue that is:
- Clearly scoped and independently actionable;
- Low-risk enough for a focused PR;
- Described with an affected area, concrete problem, and desired outcome;
add it to TECH-DEBT.md unless it is fixed in the current PR.

Do not add broad refactors, speculative concerns, product ideas, or items that require significant investigation. Create a ticket instead for cross-cutting, risky, or large work, then link to that ticket from TECH-DEBT.md if useful.

Check if there are already open PRs that address the issue before picking it up.
