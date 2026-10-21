---
name: alethe
description: Shortcut for the alethe-orchestrate skill. Use only when the user types /alethe or "alethe" followed by a task or a short command such as on, off, report, status, list, stop or setup.
argument-hint: "[task or standing instruction] | on | off | save | max | careful | report | status | list | stop | skip <phase> | switch <playbook> | freeform | budget <limit> | mark <worker> <used|partial|discarded> | setup | help"
disable-model-invocation: true
---

Use the alethe-orchestrate skill and follow its "Short commands" section for the words the user
typed after `/alethe`:

$ARGUMENTS

Without Python, follow its `references/manual.md` for those words instead.
