# Changelog

The version is the integer in `skills/alethe-orchestrate/SKILL.md` under `metadata.version`.
Alethe installs and updates the skill by that number.

## 11 (2026-10-18)

First version published from its own repository. Earlier versions shipped inside Alethe.

- `report` explains what an orchestration did and why: each worker's role, where it ran, how long
  it took, the tokens and cost its CLI reported, what it changed, and what is left to review. It
  reads one run or a folder with one run per wave, as Markdown or JSON, and never estimates a
  number a CLI did not report.
- Plans take optional `title`, `why`, `playbook` and `phase` notes, plus a `why` per worker, for
  the report. They never reach the workers.
- Every run saves its resolved plan as `plan.json`, without the task text.
- Worktrees under `.alethe/worktrees/` are added to the local `.git/info/exclude`, so they no
  longer show in `git status` or get staged by `git add -A`.
- Runs in folders with custom names get their own run id, so two orchestrations that reuse a wave
  name no longer collide on worktree paths.
- Output with non-ASCII text no longer fails when it goes through a pipe on Windows.
- `--version` and `doctor` show the skill version.

## 8 to 10 (inside Alethe)

- Setup takes inventory of the CLIs, models and routes you have, proposes base, savings and
  aggressive profiles, and saves them only after you approve.
- Strategy playbooks with conditions, spare-quota rules, `dry-run --write` and an SVG
  architecture preview.
- Flags that approve every tool in a custom CLI, such as `--trust-all-tools`, `--allow-all-tools`
  and `--yolo`, need `allowUnsafe`.
