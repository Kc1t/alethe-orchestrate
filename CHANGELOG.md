# Changelog

The version is the integer in `skills/alethe-orchestrate/SKILL.md` under `metadata.version`.
Alethe installs and updates the skill by that number.

## 13 (2026-10-19)

Added:

- `/alethe` in Claude Code, and short commands after the skill's name elsewhere: `report`,
  `status`, `list`, `stop`, `skip`, `switch`, `freeform`, `budget`, `mark`, `setup` and `help`.
- `new "<title>"` starts an orchestration folder and makes it current, and `run --in current`
  adds the next wave. `report`, `status`, `budget`, `note`, `stop` and `mark` then need no folder,
  and `mark` needs no run.
- `list` shows recent orchestrations with their waves and spend, and `use` makes one current again.
- `stop` ends the running workers of an orchestration and skips the queued ones.
- `note` records a change to the plan. The report lists them under "Changes to the plan" and
  `status` shows the latest.
- `mode on` keeps orchestration on for a project with a goal (`save`, `balanced`, `max`), an
  optional `careful` level and the user's standing rules, until `mode off` or 12 idle hours. The
  Claude Code plugin's prompt hook reminds the agent while it is on, so the user calls the skill
  once.
- The skill joins mid-task and inside other workflows such as spec-driven development, taking the
  work so far as its plan, and runs with the CLIs it finds when nothing is configured yet.

Changed:

- Playbooks are where the lead starts, not a contract. Between waves it can skip, repeat or add a
  phase, do a step itself, switch playbooks or go freeform, and the user can ask for any of these.

## 12 (2026-10-19)

Fixed:

- On Windows, npm installs CLIs as `.cmd` shims, and cmd.exe cut a prompt passed as an argument at
  its first newline. Kimi workers lost everything after the first line of their task, including
  the worker contract, and a quote in a task could run another command. The runner now launches
  the shim's real target directly, and refuses risky arguments for a batch file it cannot read.
- Kimi write workers failed at startup: Kimi refuses `--yolo` with `--prompt`. Kimi's prompt mode
  always approves every tool, so `auto` no longer sends read-only work to Kimi.
- Codex resumed sessions without the worker's sandbox or effort.
- A Claude worker that timed out left no session id to resume; Claude now streams its events.
- A large prompt sent through stdin could block the runner before any deadline applied.
- On macOS and Linux, a child process that ignored the stop signal survived a timeout.
- A writer in a repository with no commits lost its result; it now succeeds with no diff.
- A stray non-JSON line made a worker's whole output unreadable.
- Workers whose CLI prints plain text now get a `result.md` too.
- The saved-policy note said Alethe erased budgets and model tiers, which it no longer does.

Added:

- `budget <folder>` sets limits on calls, reported cost and reported tokens for every wave of an
  orchestration, enforced by each run.
- Plan budgets take `maxReportedTokens`, the limit that covers CLIs that report no cost. Claude
  workers also get their share of the cost limit as `--max-budget-usd`.
- Codex and Claude workers cannot start subagents, and start without MCP servers unless a worker
  sets `mcp: true`. Every worker runs with `ALETHE_ORCHESTRATE_WORKER=1`, and `run` refuses to start
  inside one.
- Workers end with a `STATUS:` and a `SUMMARY:` line, and validators with a `VERDICT:` line. The
  runner reads them, and the report lists blocked, doubtful and failed work with what to do next.
- A read-only tripwire compares the checkout before and after each read-only worker, and a writer
  in the main checkout records which files already had changes.
- Each outcome has a `failureKind`, such as `rate_limited` or `auth_required`, read from the logs,
  plus the tools Claude denied and the models it billed.
- `mark` records whether a result was used, partly used or discarded; the report then splits the
  spend between them.
- `status <folder>` prints where an orchestration stands, for picking it up after compaction.
- `idleTimeoutSeconds` stops a worker that prints nothing for that long; `state.json` shows each
  running worker's output size and idle time.
- `validate` and `dry-run` warn about blind cost limits, unpinned models, briefs too small to
  delegate, Kimi read-only work, MCP mentions and writers in a checkout with uncommitted changes.
- `doctor` says whether each CLI is logged in.
- `references/briefs.md` covers writing a brief, reviews, adversarial reviews, validator verdicts
  and panels. Playbooks gain a `risky` condition, and review-gate asks for a verdict.
- The repository is also a Codex plugin marketplace.

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
