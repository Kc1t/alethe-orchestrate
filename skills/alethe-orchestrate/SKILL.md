---
name: alethe-orchestrate
description: Orchestrate bounded Codex, Claude Code, Agy, Kimi, or custom CLI workers to finish work with the least lead context and provider usage, following strategy playbooks such as plan big, execute small. Use when the user asks to orchestrate, delegate, compare agents, conserve agent tokens or quota, recover a worker, report what an orchestration did and cost, or work without MCP. Do not use for a small mechanical task unless explicitly requested.
metadata:
  version: "12"
---

# Orchestrate CLI workers

The goal is to orchestrate and save: finish the work with the least lead context and the cheapest
capable workers. Act as planner and integrator. Give each worker one bounded unit, keep detailed
transcripts outside your context, and integrate only results supported by evidence or diffs.

## Choose the backend

Honor an explicit request for the local skill or no MCP. It always wins. Otherwise run
`scripts/orchestrate.py policy show` and use its `backend`: `skill` selects this runner, `mcp`
selects `alethe_*` tools when present, and `auto` prefers those tools when available.

The skill path is self-contained and never requires MCP. Its runner provides strategies, provider
switching preferences, concurrent processes, deadlines, structured outcomes, selective worktree
isolation, and resumable session IDs. It does not add workers to Alethe's board or invent quota
readings that a CLI does not report.

## First run and configuration

Run `scripts/orchestrate.py doctor` when the environment may be unprepared or the user asks what
is set up. It reports the Python version, installed providers, and whether a saved policy exists
and is valid, plus actionable hints.

When `doctor` reports no configured policy, or the user asks to set up orchestration, follow
[references/onboarding.md](references/onboarding.md): take inventory of the CLIs, models and
routes the user really has, build base, savings and aggressive profiles from it, and ask for
approval before saving them to the playbooks copy. Never persist a preference the user did not
confirm. Do not assume an unfamiliar tool is a worker: a
proxy such as 9router belongs on the model traffic path, not in the worker list.

Translate loose configuration requests into actions:

| The user says | Do |
| --- | --- |
| "save provider X" as an ongoing preference | confirm, then `policy set --conserve-providers X` |
| "use cheap models for the small stuff" | ask which provider and model, confirm, then `policy set --cheap-model provider=model` |
| "at most N workers / T minutes / C dollars" as an ongoing preference | confirm, then `policy set --max-calls N --max-wall-seconds T --max-reported-cost-usd C` |
| any of the above "for this run only" | put it in the plan's `budget` or use `--strategy`; never touch the policy |
| "at most N calls / C dollars / T tokens for this whole task" | `budget <folder>` with those limits before the first wave |
| "where were we", or after the conversation was compacted | `status <folder>` before anything else |
| "back to defaults" | confirm, then `policy reset` |
| "change the playbooks" or roles per phase | `playbook --init`, then edit the copy it prints; the UI exports the same file |
| "use savings" or "go aggressive" as an ongoing preference | confirm, then set `profile` in the playbooks copy |
| "what did it do", "how much did it cost" | `report` on the orchestration folder; no confirmation needed |

## Pick a playbook

Before planning, run `scripts/orchestrate.py playbook` and read the whole output. It prints the
effective playbooks file: the user's copy when one exists, otherwise the bundled defaults. It holds
the saving principles, the user's providers and their adapters, the `cheap`/`standard`/`strong`
tiers, the quota and budget rules, the profiles, and the playbooks. [references/playbooks.md](references/playbooks.md) explains every field and condition.

1. Pick a playbook with `pickOrder`. A playbook the user names wins; so does a runner strategy
   name, which keeps the single-wave behavior described below. `complete` adapts per unit when
   nothing else fits.
2. Run the phases in order. `who: lead` is you, in this session. Every other phase is one wave of
   workers: its `runner` is the plan `strategy`, `workers` the unit count, `readOnly` means
   `mode: read`, and `isolate` gives each writer its own worktree.
3. Skip a phase whose `if` does not hold; among paths joined by `with`, the first true one runs.
   Check a phase's `gate` yourself; on fail, run its `after` chain once per unit, then check again.
4. Pick each worker's model and effort as the reference describes: the tier in the active
   profile, then the first matching rule, then the next provider in the order at the same tier
   when the chosen one is low on tokens, then `quota.whenSpare` when a provider would lose unused
   quota. Pass that model and effort explicitly; never move read-only work to a writable worker.
5. Say which playbook you picked and why in one line before the first wave.

## Orchestrate

1. Delegate only when the playbook makes the worker overhead worthwhile. `economy` and `rescue`
   intentionally allow one worker; keep an ordinary small task with the lead.
2. Read [references/routing.md](references/routing.md) for the runner strategies each wave can use:
   `auto`, `economy`, `balanced`, `quality`, `research`, `parallel`, or `rescue`. An explicit
   strategy in the current request wins over saved preferences. Treat the word immediately after an
   explicit skill invocation as the playbook or strategy when it matches one of those names.
3. Run `scripts/orchestrate.py probe` and use only available providers. Read
   [references/providers.md](references/providers.md) when using Agy, Kimi, resuming a worker, or
   adding a custom CLI.
4. Give writers disjoint ownership. Use an isolated worktree for concurrent writers; a single
   writer may use the main checkout when existing user changes are preserved.
5. Create a version-1 plan JSON outside the repository. `scripts/orchestrate.py scaffold
   <strategy> --workers N` prints a valid skeleton to fill in. Use `strategy`, and use
   `provider: auto` only when saved provider switching preferences may decide the provider. Set
   `budget` when the run needs hard limits, and `budget <folder>` when a limit covers every wave.
   Give the plan a `title`, the `playbook` and `phase` it runs, and a one-line `why`; give each
   worker a short `why` naming its role and the reason for its model. The report shows them.
   Write each task as [references/briefs.md](references/briefs.md) describes. Codex and Claude
   workers start without MCP servers; set `mcp: true` only for a brief that needs one. Validate
   the plan against [schemas/plan.schema.json](schemas/plan.schema.json) or with
   `scripts/orchestrate.py validate`.
6. Preview with `scripts/orchestrate.py dry-run`. It explains the resolved strategy, the effective
   provider per worker, the concurrency, the estimated prompt tokens, and the budget that would
   apply, without starting anything. Fix its `warnings` or say why they do not apply.
   When the user wants to see the architecture, save the preview with `dry-run --write`, then
   render it with `scripts/diagram.py` as described in [references/diagram.md](references/diagram.md).
   Show the SVG before running workers and use only confirmed proxy routes.
7. Run the plan with `scripts/orchestrate.py run`, passing `--run-dir <folder>/<NN>-<phase>` so
   every wave of one orchestration lands in the same folder. The runner never invokes a shell, caps
   concurrency, enforces the plan budget, terminates timed-out process trees, writes state
   atomically, and leaves worktrees for review.
8. Read `state.json`, each `outcome.json` (its `workerStatus`, `failureKind` and
   `readOnlyViolation` first), the concise `result.md`, and writer `diff.patch` files. Do not load
   raw logs unless diagnosing a failure.
9. Integrate reviewed changes, run validation in the combined checkout, `mark` each worker's result
   `used`, `partial` or `discarded`, then remove only temporary data and worktrees whose useful
   changes were handled.
10. Close with `scripts/orchestrate.py report <folder>` and show the user its output: what each
    worker did and why, the time, tokens and cost the CLIs reported, what the spend bought, and
    what is left to review. Run it whenever the user asks what an orchestration did or cost;
    without a folder it reads the latest run.

For plan examples, result semantics, selective dirty-state seeding, and cleanup, read
[references/operations.md](references/operations.md).

## Worker contract

Each task must state its goal, definition of done, owned paths, relevant repository rules, checks,
forbidden changes, and desired handoff. The runner automatically appends these invariants:

- do not delegate, spawn subagents, or launch another agent CLI
- do not commit, push, tag, release, or open a pull request
- return a concise outcome, evidence, changed files, checks, failures, and risks
- finish with a `STATUS:` line (`DONE`, `DONE_WITH_CONCERNS`, `BLOCKED` or `NEEDS_CONTEXT`) and a
  `SUMMARY:` line

Codex and Claude workers cannot start subagents: the runner turns that off in the CLI. Every
worker runs with `ALETHE_ORCHESTRATE_WORKER=1`, so it cannot start an orchestration of its own. A
worker's status and summary are claims; check its diff. For review, validation, judge and panel
briefs, follow [references/briefs.md](references/briefs.md).

Do not put secrets in plans, tasks, arguments, or logs. Do not use bypass flags unless the user
explicitly requested that loss of isolation; custom workers require `allowUnsafe: true` for known
unsafe flags.

## Token discipline

- Treat statements such as "low on tokens", "save quota", or "economize" as `economy` for the
  current run. Persist it with `policy set economy` only when the user asks for an ongoing default.
- A plan `budget` turns saving into a hard limit: cap worker calls, wall time, estimated prompt
  tokens, reported tokens and reported cost. Use `dry-run` to see the estimate before anything
  runs. Only Claude reports cost, so `maxReportedTokens` is what caps the other CLIs.
- More workers increase total provider usage. `auto` must choose no orchestration when the task is
  cheaper to finish directly; if orchestration was explicitly requested, it chooses the smallest
  valid strategy.
- Send only the context each unit needs. Point to repository files instead of copying their full
  contents into every task.
- Read concise results and diffs, not full transcripts.
- Reuse a returned `sessionId` for a focused follow-up instead of spawning a worker that must read
  the same area again.
- Use cheap workers for bounded discovery and mechanical work; keep ambiguity and final integration
  with the lead or a capable reviewer.
- A failed worker may be retried once only when the error has a specific correctable cause.

The runner reduces the lead agent's context load. It does not make worker tokens free.

Do not commit, push, tag, release, or open a pull request unless the user explicitly asked for it.
