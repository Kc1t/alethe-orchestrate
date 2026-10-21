---
description: Orchestrate a task with Alethe, keep it on for this project, or report on, check, stop or steer the current orchestration
argument-hint: "[task or standing instruction] | on | off | save | max | careful | report | status | list | stop | skip <phase> | switch <playbook> | freeform | budget <limit> | mark <worker> <used|partial|discarded> | setup | help"
---

Use the alethe-orchestrate skill and follow its "Short commands" section for these arguments:

$ARGUMENTS

The runner is `python "${CLAUDE_PLUGIN_ROOT}/skills/alethe-orchestrate/scripts/orchestrate.py"`.
