---
description: Always run commands and make changes automatically without pausing for human permission
globs: *
---

# Autonomous Execution Rule

- Always execute required terminal commands, scripts, and tests directly using `run_command`.
- Do NOT call `ask_question` or pause execution to ask for confirmation when running builds, linters, tests, or file edits.
- Proceed automatically to complete the user's objective without requiring manual sign-offs.
