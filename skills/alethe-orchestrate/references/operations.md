# Batch operations

Read this reference when creating a plan, inspecting outcomes, reporting on a run, carrying dirty
state into a worktree, or cleaning up.

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
python scripts/orchestrate.py run <plan.json> --run-dir <folder>/01-explore
python scripts/orchestrate.py report <folder>
python scripts/orchestrate.py report <folder> --format json --write <report.json>
```

`doctor` checks the environment before you promise anything: Python version, installed provider
executables and versions, and whether the saved policy exists, parses, and carries a budget. Its
`hints` list says what is missing in plain language.

`scaffold` prints a starter plan for a strategy so a plan never has to be written from memory.
Worker tasks come back as TODO placeholders to replace, `parallel` workers already carry
`isolate: true`, and `rescue` requires `--provider` because a resumed session belongs to one
CLI. Pass `--write <path>` to save it instead of printing.

`dry-run` validates the plan and explains what a run would do — resolved strategy and why,
effective provider per worker, concurrency, estimated prompt tokens, and the effective budget —
without starting a worker or creating a worktree. Run it before any strategy you did not pick
yourself.

Pass `--run-dir <empty-directory>` when a stable output location is useful. Otherwise the runner
creates a unique directory under the operating system's temporary directory. For an orchestration
with several waves, give each wave its own folder inside one parent, such as
`<folder>/01-explore` and `<folder>/02-build`, so `report` can read them together.

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
    "maxReportedCostUsd": 2.5
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
  providers that emit usage report cost at all, so this limit can never fire for `kimi` or
  `custom` workers.

Budget gates are checked when a worker is submitted. With `maxConcurrent` above one, workers
already running are not retroactively cancelled — the gates stop new work, they do not recall
in-flight work.

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
<run>/
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
        `-- diff.patch
```

`state.json` is the compact batch view. A worker succeeds only when it exits before its deadline,
its declared structured output parses, and a non-empty final result can be extracted. Raw stdout
and stderr are diagnostic artifacts, not final answers.

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
as failure. Read `error`, then the tail of `stderr.log`. Retry once only when a narrower task or
corrected invocation addresses a specific cause. A partial writer diff is untrusted until reviewed.

Do not erase main-checkout changes after a failed non-isolated writer; inspect ownership first.
