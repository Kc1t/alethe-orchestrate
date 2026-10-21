---
name: alethe-orchestrate
description: Orchestrate bounded Codex, Claude Code, Agy, Kimi, or custom CLI workers to finish work with the least lead context and provider usage, following strategy playbooks such as plan big, execute small. Use when the user asks to orchestrate, delegate, compare agents, conserve agent tokens or quota, recover a worker, report what an orchestration did and cost, or work without MCP or Python, when the user types /alethe or a short command such as "alethe report" or "alethe stop", and when they want it on from now on, at any point of a task and alongside other skills. Also use it proactively, without being asked, when a request is large enough to split into bounded independent units, such as a multi-file refactor, a migration, an audit or research across many files. Do not use for a small mechanical task unless explicitly requested.
metadata:
  version: "15"
---

# Orchestrate CLI workers

The goal is to get more out of the user's AI: finish the work with the least lead context and the
cheapest capable workers, or, when they ask for the most, with the strongest mix they have. Act as planner and integrator. Give each worker one bounded unit, keep detailed
transcripts outside your context, and integrate only results supported by evidence or diffs.

## Choose the backend

Honor an explicit request for the local skill or no MCP. It always wins. Otherwise run
`scripts/orchestrate.py policy show` and use its `backend`: `skill` selects this runner, `mcp`
selects `alethe_*` tools when present, and `auto` prefers those tools when available.

Python is optional. When `python --version`, `python3 --version` and `py --version` all fail or
report below 3.9, or the user asks not to depend on Python, follow
[references/manual.md](references/manual.md): you detect the CLIs yourself, offer the user two to
four options, launch the workers from your own shell and write the report. Every other section of
this file still applies; read each `scripts/orchestrate.py` step as its manual equivalent there.

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

Setup never blocks the work. When the user calls the skill mid-task with nothing configured, run
`doctor`, use the logged-in CLIs it found with the bundled playbooks for this task, say so in one
line, and keep going. Offer the full onboarding once the current step is done; save nothing
until they agree.

Translate loose configuration requests into actions:

| The user says | Do |
| --- | --- |
| "save provider X" as an ongoing preference | confirm, then `policy set --conserve-providers X` |
| "use cheap models for the small stuff" | ask which provider and model, confirm, then `policy set --cheap-model provider=model` |
| "at most N workers / T minutes / C dollars" as an ongoing preference | confirm, then `policy set --max-calls N --max-wall-seconds T --max-reported-cost-usd C` |
| any of the above "for this run only" | put it in the plan's `budget` or use `--strategy`; never touch the policy |
| "at most N calls / C dollars / T tokens for this whole task" | `budget` with those limits before the first wave |
| "where were we", or after the conversation was compacted | `status` before anything else |
| "back to defaults" | confirm, then `policy reset` |
| "change the playbooks" or roles per phase | `playbook --init`, then edit the copy it prints; the UI exports the same file |
| "use savings" or "go aggressive" as an ongoing preference | confirm, then set `profile` in the playbooks copy |
| "what did it do", "how much did it cost" | `report`; no confirmation needed |

## Short commands

`/alethe <args>` in Claude Code, or the same words after this skill's name anywhere else, map to
one action. Commands without a folder act on the current orchestration: the one `new` started,
`use` picked, or the last `run` wrote to.

| Words | Do |
| --- | --- |
| a task, in plain words | orchestrate it as the rest of this skill describes |
| nothing | `status`; with no current orchestration, list these commands in a few lines |
| `on`, or a standing instruction ("from now on...", "a partir de agora...") | stay on, as below |
| `always`, or "always on", "in every project" | `mode on --everywhere` |
| `off` | `mode off`; with the default on, this turns it off in this project only |
| `off everywhere` | `mode off --everywhere` |
| `save`, `balanced`, `max` | `mode on --goal <it>` |
| `careful` | `mode on --care careful` |
| `report [folder]` | `report`, and show its output as is, without a summary of your own |
| `status` | `status`, and show its output as is |
| `list` | `list`; `use <folder>` makes one of them current again |
| `stop` | `stop`, then `status` once the waves have ended |
| `budget <limit>` | `budget --max-calls N`, `--max-reported-cost-usd C` or `--max-reported-tokens T` |
| `skip <phase>`, `switch <playbook>`, `freeform`, `add <phase>` | change course as below |
| `note <text>` | `note "<text>"` |
| `mark <worker> used\|partial\|discarded` | `mark <worker> <mark>` |
| `setup` | `doctor`, then onboarding when no policy is saved |
| `help` | list these commands in a few lines |

## Stay on

The user should not have to call this skill on every message, or at all. Three things keep it
in play without a command:

1. Use it proactively whenever a request splits into bounded independent units, even when nobody
   mentions orchestration, as the description says. Small or tightly coupled work stays with you.
2. `mode on --everywhere` makes it the default in every project, with no expiry. `mode off` in a
   project turns it off there only, and `mode off --everywhere` removes the default.
3. `mode on` keeps it on for the current project (the repository root, or the folder) until
   `mode off`, or after 12 hours without a prompt. A project mode wins over the default.

Both modes take the same options:

- `--goal save` spends as little as possible, `max` gets the most out of the available agents, and
  `balanced` (the default) delegates only when the playbook says it pays.
- `--care careful` reads before writing, isolates every writer, reviews every diff before
  integrating it, and asks before anything hard to undo.
- `--rule "<the user's words>"` keeps a standing instruction, up to 8; `--clear-rules` drops them.

Turn it on when the user says `/alethe on`, gives a standing instruction, or asks for orchestration
"from now on". Map the instruction to a goal or care level when one fits, and keep the user's own
words as a rule. Confirm in one line what is now on, then go back to what they were doing.

While a mode is on, the Claude Code plugin's hook reminds you on every prompt; without the plugin,
run `mode show` at the start of a session and after the conversation is compacted. Treat each request on its own: answer or do small
work yourself, and orchestrate only the parts where delegation pays for its overhead under the
goal. Nothing has to be orchestrated just because the mode is on.

## Join mid-task

The skill may be called at any point: at the start, halfway through a task, or inside another
skill's workflow such as spec-driven development. Do not start over:

1. Take what already exists as the plan: the conversation, a spec, a task list, a design doc, the
   diff so far. Point workers at those files instead of copying them.
2. Leave the other workflow in charge of its own steps and gates. Orchestrate inside it: its
   pending tasks become units, and its checks become this skill's gates. Never rewrite its files
   unless one of its own steps says to.
3. Start an orchestration with `new` only when there is delegated work; a step the lead keeps does
   not need one.
4. Work that is too small, too coupled or too ambiguous to hand off stays with the lead. Say so in
   one line rather than forcing a wave.

## Pick a playbook, then adapt

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

## Change course

A playbook is where you start, not a contract. Between waves, change the plan whenever the
results or the user give a reason: skip or repeat a phase, add one the playbook lacks, do a step
yourself, swap a worker's provider or model, change the budget, switch to another playbook, or drop
playbooks and plan each wave yourself (freeform). The user can ask for any of these at any time,
in plain words or with a short command; their request wins over the playbook.

Record each change in one line before the next wave, so the report can explain it:

| Change | Command |
| --- | --- |
| skip a phase | `note "<phase>: <why>" --kind skip` |
| add a phase or a worker | `note "<what>: <why>" --kind add` |
| switch playbook, or go freeform | `note "to <playbook or freeform>: <why>" --kind switch` |
| do a step yourself | `note "<what you did>" --kind lead` |
| anything else | `note "<what changed and why>"` |

A freeform wave is an ordinary plan: leave `playbook` out and name the `phase` after what the wave
does. Stop a wave that is no longer useful with `stop`; workers that already ran keep their results.

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
   the plan's `budget` when one wave needs hard limits, and run `budget` when a limit covers every
   wave of the orchestration.
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
7. Start the orchestration once with `scripts/orchestrate.py new "<title>" --playbook <name>
   --why "<one line>"`; it creates the folder and makes it current. Run each wave with `run <plan>
   --in current`, which numbers it after the plan's `phase`. The runner never invokes a shell, caps
   concurrency, enforces the plan budget, terminates timed-out process trees, writes state
   atomically, and leaves worktrees for review.
8. Read `state.json`, each `outcome.json` (its `workerStatus`, `failureKind` and
   `readOnlyViolation` first), the concise `result.md`, and writer `diff.patch` files. Do not load
   raw logs unless diagnosing a failure.
9. Integrate reviewed changes, run validation in the combined checkout, `mark` each worker's result
   `used`, `partial` or `discarded`, then remove only temporary data and worktrees whose useful
   changes were handled. `mark <worker> used` finds the worker in the current orchestration.
10. Close with `scripts/orchestrate.py report` and show the user its output: what each worker did
    and why, the changes to the plan, the time, tokens and cost the CLIs reported, what the spend
    bought, and what is left to review. Run it whenever the user asks what an orchestration did or
    cost; without a folder it reads the current orchestration.

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
