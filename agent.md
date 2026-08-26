# Agent Rules

## Scope Boundary

- The active project folder is the directory containing this `agent.md` file.
- All implementation work, generated files, temporary files, documentation, tests, and outputs for this project must stay inside this directory.
- Do not create, modify, move, delete, rename, or overwrite any file outside this directory unless the user gives a new explicit written instruction for that exact path and action.
- The three user-named reference projects are read-only sources for this work. They may be inspected or copied from only when the user asks, but must not be changed.

## Required Before Work

- Before starting any task in this project, read this `agent.md` file first.
- Treat the latest user request as the authorization boundary.
- If an action could affect files outside this directory, stop and ask the user before doing anything.

## Safety

- Do not run destructive commands outside this directory.
- Do not copy implementation changes back into the reference projects.
- Do not start external project services, collectors, browser automation, database-writing jobs, or upload jobs unless the user explicitly asks for that exact run.
