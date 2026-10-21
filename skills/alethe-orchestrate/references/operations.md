# Batch operations

Read this reference when creating a plan, setting a budget, inspecting outcomes, reporting on a
run, carrying dirty state into a worktree, or cleaning up.

## Run the helper

Use Python 3.9 or newer. On Windows, prefer `py -3` when `python` is not on `PATH`.

```text
python scripts/orchestrate.py probe
python scripts/orchestrate.py doctor
python scripts/orchestrate.py strategies
python scripts/orchestrate.py policy show
python scripts/orchestrate.py scaffold research --workers 3 --cwd .
python scripts/orchestrate.py validate <plan.json>
python scripts/orchestrate.py dry-run <plan.json>
python scripts/orchestrate.py dry-run <plan.json> --write <preview.json>
python scripts/orchestrate.py run <plan.json>
python scripts/orchestrate.py run <plan.json> --strategy economy
python scripts/orchestrate.py new "Rename the login helper" --playbook scout-then-build --why "..."
python scripts/orchestrate.py run <plan.json> --in current
python scripts/orchestrate.py run <plan.json> --run-dir <folder>/01-explore
python scripts/orchestrate.py budget --max-calls 8 --max-reported-cost-usd 2
python scripts/orchestrate.py note "review: the diff was three lines" --kind skip
python scripts/orchestrate.py status
python scripts/orchestrate.py stop
python scripts/orchestrate.py mark <worker> used --why "merged as is"
python scripts/orchestrate.py report
python scripts/orchestrate.py report <folder> --format json --write <report.json>
python scripts/orchestrate.py list
python scripts/orchestrate.py use <folder>
```

`doctor` checks the environment before you promise anything: Python version, installed provider
executables and versions, whether each CLI is logged in (`loggedIn`, or `null` when it cannot
tell), and whether the saved policy exists, parses, and carries a budget. Its `hints` list says
what is missing in plain language.

`scaffold` prints a starter plan for a strategy so a plan never has to be written from memory.
Worker tasks come back as TODO placeholders to replace, `parallel` workers already carry
`isolate: true`, and `rescue` requires `--provider` because a resumed session belongs to one
CLI. Pass `--write <path>` to save it instead of printing.

`dry-run` validates the plan and explains what a run would do — resolved strategy and why,
effective provider per worker, concurrency, estimated prompt tokens, and the effective budget —
without starting a worker or creating a worktree. Run it before any strategy you did not pick
yourself.

`validate` and `dry-run` also print `warnings` about money and safety before anything is spent: a
cost limit that some providers cannot see, a worker on its CLI's default model, several writers
with briefs so short that each worker's startup costs more than the work, Kimi read-only work, a
brief that mentions MCP while servers are off, and a writer in a checkout that already has
uncommitted changes. Fix them or say why they do not apply.

## The current orchestration

`new "<title>"` creates an orchestration folder under `orchestrations/` next to the saved policy
(`ALETHE_ORCHESTRATE_HOME` overrides it), saves the title, playbook and why in
`orchestration.json`, and makes it current. `run <plan> --in current` adds the next wave as
`<NN>-<phase>`, so `report` reads every wave together.

`report`, `status`, `budget`, `note`, `stop` and `mark` act on the current orchestration when no
folder is given. The current one is the folder `new` created, the one `use <folder>` picked, or
the last folder a `run` wrote to: the parent of `--run-dir`, or the run itself when the runner
picked a temporary directory. `list` shows recent orchestrations with their waves and spend, and
marks the current one with `*`.

`--run-dir <empty-directory>` still works when a fixed location is useful; give each wave its own
folder inside one parent, such as `<folder>/01-explore` and `<folder>/02-build`. Without either
flag the runner creates a unique directory under the operating system's temporary directory.

## Staying on

`mode on [--goal save|balanced|max] [--care careful] [--rule TEXT]... [--cwd DIR]` keeps
orchestration on for the repository that holds `--cwd` (or that folder outside git), saved in
`modes.json` next to the orchestrations. Calling it again changes only the flags given; rules add
up to 8, and `--clear-rules` drops them. `mode show` prints the mode, and `mode off` removes it. A
mode with no prompt for 12 hours is dropped.

`hook` reads an agent hook's JSON from stdin and prints a one-paragraph reminder of the goal, care
level and rules when the hook's `cwd` is inside a project with a mode on, and nothing otherwise.
It never fails. The Claude Code plugin runs it on every prompt (`hooks/hooks.json`).

## Changing course

`note "<text>" [--kind change|skip|add|switch|lead]` appends a line to `journal.jsonl` in the
orchestration folder. The report lists them under "Changes to the plan" with the time, and
`status` shows the count and the latest one. Record a skipped or added phase, a switched playbook,
a move to freeform waves, or a step the lead did itself, with the reason.

`stop` writes a `stop` file into every running wave of the orchestration. Each running worker's
process tree ends within a few seconds with status `stopped`, workers still queued are skipped
with `failureKind: stopped`, and the wave ends as `stopped`. Results that finished before stay.

If Python is unavailable, do not install it without permission. Use the command shapes in
`references/providers.md` with the host's native background-process facility and reproduce the
same deadlines and result checks.

## Minimal plan

```json
{
  "version": 1,
  "title": "Add the export API",
  "playbook": "plan-big-execute-small",
  "phase": "build",
  "why": "Two independent units: one writer for the API and one read-only UI review.",
  "strategy": "balanced",
  "workers": [
    {
      "id": "api",
      "why": "writer for src/api on the standard tier",
      "provider": "auto",
      "mode": "write",
      "cwd": "C:\\work\\project",
      "isolate": true,
      "task": "Implement the API unit. Own src/api and tests/api only."
    },
    {
      "id": "ui-review",
      "provider": "agy",
      "mode": "read-only",
      "cwd": "C:\\work\\project",
      "task": "Review the UI state flow. Return findings with file and line evidence."
    }
  ]
}
```

Use `taskFile` instead of `task` for a long instruction. Relative `cwd` and `taskFile` values are
resolved from the plan file's directory.

`title`, `why`, `playbook`, `phase` and each worker's `why` are optional notes for the report and
never reach the workers. Keep them to one line: `title` up to 120 characters, the plan's `why` up
to 500, and a worker's `why` up to 300.

A worker may declare `tier: cheap` or `tier: strong` to use the policy-mapped model for its
provider instead of pinning `model` or `effort` (see `references/routing.md`). Tiers compose
with `provider: auto`; explicit models do not.

Codex and Claude workers start without MCP servers; set `mcp: true` on a worker whose brief needs
one. `idleTimeoutSeconds` (5 to 86400) stops a worker that prints nothing for that long, which
catches a CLI waiting on a prompt nobody will answer; leave it unset for checks that run quietly.

`provider: auto` uses the saved provider order and conservation preferences. Name a provider when
the user requested it, a model or effort belongs to it, or a session is being resumed. The legacy
`preset` field is still accepted, but new plans use `strategy`.

`--strategy` is a one-run override. Its precedence is command line, plan, saved policy, then
`auto`; it never changes the saved default.

## Execution budget

A plan may carry an optional `budget` object; every field is optional and absent means unlimited:

```json
{
  "version": 1,
  "budget": {
    "maxCalls": 4,
    "maxWallSeconds": 1800,
    "maxEstimatedPromptTokens": 60000,
    "maxReportedCostUsd": 2.5,
    "maxReportedTokens": 400000
  },
  "workers": []
}
```

- `maxCalls` caps how many worker processes the run may start. A worker refused by a budget gate
  finishes with status `skipped` and counts as unsuccessful.
- `maxWallSeconds` caps the whole batch clock; each worker's effective timeout is the smaller of
  its own `timeoutSeconds` and the remaining wall time.
- `maxEstimatedPromptTokens` is checked at validation time against the summed prompt-only
  estimate (chars/4), so `validate`, `dry-run`, and `run` all reject an over-budget plan before
  anything starts. Provider-side context such as repository reads is additional and not included.
- `maxReportedCostUsd` gates later workers on the cost earlier workers actually reported. Only
  Claude reports cost, so this limit cannot see Codex, Agy, Kimi or custom workers. Each Claude
  worker also gets the part of it that is left as `--max-budget-usd`, split across the workers
  that may run at the same time, so Claude stops a worker that spends its share. The runner does
  not start a Claude worker when less than $0.01 is left for it.
- `maxReportedTokens` gates later workers on the tokens earlier workers reported. Codex, Claude
  and Agy report tokens, so this is the limit that covers the workers that report no cost.

Budget gates are checked when a worker is submitted. With `maxConcurrent` above one, workers
already running are not retroactively cancelled — the gates stop new work, they do not recall
in-flight work.

## Orchestration budget

A plan's budget covers one wave. `budget [folder]` sets limits for every wave of an
orchestration: `--max-calls`, `--max-reported-cost-usd` and
`--max-reported-tokens`. It saves them in `<folder>/budget.json`. Each run adds up what the earlier
waves in that folder used and refuses to start once a limit is spent; a wave that reaches a limit
part way stops starting workers. `budget` without limits shows them with the usage so far
and what remains, and `--clear` removes them. Waves are counted after they finish, so run one wave
at a time in a folder.

The saved policy can hold the same fields as defaults (`policy set --max-calls 4`); a plan
overrides them field by field. When Alethe is installed, its Orchestration preferences own the
backend, default strategy, provider switching, conserved provider and concurrency, and put the
preferred provider first in the saved order; budgets, model tiers and the rest of the order stay
as `policy set` left them.

`state.json` records the effective `budget` and a `budgetUsage` block with `calls`,
`wallSeconds`, `reportedCostUsd`, and `reportedTokens`; the `reported*` fields are `null` when no
worker reported the corresponding metric.

## Output layout

```text
<folder>/
|-- budget.json           from budget, optional
`-- <NN>-<phase>/         one run
    |-- state.json
    |-- plan.json
    `-- workers/
        `-- <id>/
            |-- prompt.txt
            |-- stdout.log
            |-- stderr.log
            |-- result.md
            |-- outcome.json
            |-- status.txt
            |-- diff.patch
            `-- mark.json  from mark, optional
```

`state.json` is the compact batch view. While a worker runs, its entry shows `outputBytes` and
`idleSeconds`, so a watcher can tell a busy worker from a stuck one. A worker succeeds only when it
exits before its deadline, its declared structured output parses, and a non-empty final result can
be extracted. Raw stdout and stderr are diagnostic artifacts, not final answers.

## What a worker reports

Besides its status, error, session, metrics and diff, `outcome.json` carries:

- `workerStatus` and `workerSummary`: the `STATUS:` and `SUMMARY:` lines the contract asks for.
  `DONE_WITH_CONCERNS`, `BLOCKED` and `NEEDS_CONTEXT` reach the report's "Left to do" even when the
  process succeeded.
- `verdict`: a `VERDICT:` line of `PASS`, `FAIL` or `NOT_PROVEN`, which validator briefs ask for
  (see [briefs.md](briefs.md)).
- `failureKind`: `rate_limited`, `auth_required`, `not_installed`, `timed_out`, `stalled`, `budget`,
  `budget_exceeded`, `invalid_output`, `no_result` or `error`, read from the error and the end of
  the logs. `resetHint` keeps a reset time the CLI printed.
- `permissionDenials` and `billedModels`: the tools Claude refused and the models it billed.
- `readOnlyViolation` and `touchedFiles`: whether a read-only worker in a checkout changed it,
  compared with git before and after. `null` means it could not be told, for example because a
  writer shared the checkout at the same time.
- `dirtyBefore`: for a writer in the main checkout, the paths that already had changes when it
  started; its `diff.patch` includes them.
- `costCapUsd`, `diffError` and `sharedCheckoutWith`.

The state records both `strategy` and `requestedStrategy`; they differ when `auto` resolves to a
concrete strategy. Validation also reports `requestedProvider` next to the effective provider when
automatic switching occurred.

An overall status is:

- `done`: every worker succeeded
- `partial`: at least one succeeded and at least one failed or timed out
- `failed`: none succeeded

`plan.json` is the resolved plan, saved when the run starts: the notes, the strategy and why it
was chosen, and each worker's provider, model, effort and routing reasons. It never holds task
text; each worker's `prompt.txt` does.

## Report

`report` reads a run directory, or a folder holding one run directory per wave, and explains the
orchestration: what each worker did and why, where it ran, how long it took, the tokens and cost
its CLI reported, and what is left to review. Without a path it reads the latest run in the
temporary directory. Markdown is the default; `--format json` returns the same data for tools, and
`--write <file>` also saves it.

The report never estimates. Claude Code reports tokens and a cost at API prices, Codex reports
tokens only, and other CLIs report whatever their output carries, often nothing; the report says
which ones reported nothing instead of guessing. On a subscription, Claude's figure is what the
work would have cost through the API, while the work itself counted against plan limits. "Lead
context" compares the transcripts that stayed on disk with the results the lead reads.

"Left to do" also lists workers that succeeded but said they were blocked or had concerns, got a
FAIL or NOT_PROVEN verdict, wrote while read-only, or had tool calls denied, each with what to do
next. With a folder budget, the report adds what every wave used against it.

`mark [folder] <worker> used|partial|discarded [--why TEXT]` records whether you kept a worker's
result. Once any result is marked, the report adds a **Value** line that splits the reported cost
and tokens between results used, partly used and discarded, and lists the ones still unmarked.
That is how an orchestration shows what its spend bought.

`status [folder]` prints a few lines: the waves and how they ended, what was spent, the changes
to the plan, the folder budget, what needs attention, open worktrees and unmarked results. Run it first after the
conversation is compacted or in a new session, instead of reading the runs again.

## Worktrees and dirty state

`isolate: true` creates a detached worktree under `.alethe/worktrees/`. It is allowed only for a
writer and is never removed automatically. Unless the repository already ignores that folder, the
runner adds `/.alethe/worktrees/` to the local `.git/info/exclude`, which is never committed, so
worktrees stay out of `git status`.

Worktrees start from `HEAD`. To carry necessary uncommitted state, list only repository-relative
paths in `seedPaths`. The runner applies tracked diffs and copies explicitly listed untracked files.
Symlinked seed paths are rejected so an isolated worker cannot reach back into the main checkout.
The runner never stashes or commits the main checkout and never copies the whole dirty repository.

After completion, inspect `status.txt` and `diff.patch`. Apply or reproduce reviewed changes in the
main checkout, run combined validation there, and remove the worktree only after every useful
change has been handled.

## Failure and retry

Treat non-zero exit, timeout, invalid structured output, an error result, or an empty final answer
as failure. Read `error` and `failureKind`, then the tail of `stderr.log`. Retry once only when a
narrower task or corrected invocation addresses a specific cause:

- `rate_limited`: that provider is low for the rest of the orchestration; run the unit on the next
  provider in the order, or after the reset in `resetHint`.
- `auth_required` and `not_installed`: tell the user; another attempt will fail the same way.
- `timed_out` and `stalled`: resume the session with the rescue strategy, or narrow the task.
- `budget` and `budget_exceeded`: raise the budget only when the user agrees.

A partial writer diff is untrusted until reviewed.

Do not erase main-checkout changes after a failed non-isolated writer; inspect ownership first.
