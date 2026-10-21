# Orchestrating without Python

Use this path when Python 3.9+ is not installed or the user asked not to depend on it. You do what
`scripts/orchestrate.py` would do with your own shell and file tools. The playbooks, tiers, worker
contract and token discipline in SKILL.md stay the same; only the mechanics change.

## 1. Detect

Run these yourself, in one batch, and keep only the answers:

| What | How |
| --- | --- |
| Python | `python --version`, `python3 --version`, `py --version`; any 3.9+ means the runner is an option |
| Worker CLIs | `<cli> --version` for `claude`, `codex`, `agy`, `kimi`, plus any other agent CLI on PATH |
| Logged in | a one-word prompt on the cheap tier, only for a CLI you plan to use; an auth error means "log in first" |
| Git | `git rev-parse --show-toplevel` and `git status --porcelain`; worktrees need a repository |
| Saved setup | the playbooks copy, `alethe-playbooks.yaml` in `%APPDATA%\Alethe\` on Windows or `~/.config/alethe/` elsewhere; otherwise `playbooks.yaml` in this skill |
| Routes | for 9router or another gateway, read its config or environment; never start or change it |

Read the playbooks file directly. With no saved copy, follow [onboarding.md](onboarding.md) using
this table instead of `doctor`, and save the approved copy by copying the bundled file to the path
above and editing it.

## 2. Offer options

Before the first wave, show the user what you found and two to four concrete options, recommended
first, each in one line with who does what and why it saves. Ask them to pick when the choice
changes cost or touches their files. Build the options from `pickOrder` and the inventory, for
example:

- **Do it myself:** the task is small enough that briefing workers costs more.
- **Plan big, execute small:** N cheap read-only workers on CLI X, I write the answer.
- **Parallel writers:** N writers in their own worktrees on CLI X and Y, I integrate and test.
- **Use the runner:** Python is installed, so `scripts/orchestrate.py` can add budgets, dry-run
  estimates and the report.

When the user already named a playbook, strategy or provider, skip the question and say in one
line what you will run.

## 3. Prepare the run folder

Create `<folder>/<NN>-<phase>/<worker-id>/` outside the repository, for example under the system
temp folder. For each worker write `task.md`: the brief from [briefs.md](briefs.md), followed by the
worker contract invariants from SKILL.md word for word. For each concurrent writer create a
worktree first: `git worktree add .alethe/worktrees/<run>-<id> -b alethe/<run>-<id>` and add
`.alethe/worktrees/` to `.git/info/exclude` when it is not ignored yet.

## 4. Launch the workers

Start each worker as a background process with `ALETHE_ORCHESTRATE_WORKER=1`, the prompt from
`task.md`, stdout to `out.jsonl` and stderr to `err.log`, and the tier's model and effort pinned.
Launch every worker of a wave in one go, at most four at a time.

```text
codex --disable multi_agent exec --sandbox read-only|workspace-write --json --output-last-message result.md --cd <cwd> --model <m> --config model_reasoning_effort=<e> --config mcp_servers={} -  < task.md
claude --print --output-format stream-json --verbose --permission-mode plan|acceptEdits --disallowedTools Agent,Workflow --strict-mcp-config --model <m> --effort <e>  < task.md
agy --output-format json --mode plan|accept-edits --print-timeout <s>s --add-dir <cwd> --model <m> "--print=<task>"
kimi --output-format stream-json --model <m> "--prompt=<task>"
```

- Drop `--model` or `--effort` only when the tier leaves it empty. Check `--help` once for flags you
  are unsure about; if `codex features list` has no `multi_agent`, drop that `--disable`.
- Add `--skip-git-repo-check` to Codex outside a git repository.
- Give each process a deadline: `timeout <s>` in bash, or a `Start-Process` handle you stop after
  `<s>` seconds in PowerShell. In Claude Code, launch with `run_in_background` and wait for the
  completion notice instead of polling.
- Agy and Kimi take the task as an argument; keep it short and point to files instead.
- Never use bypass flags such as `--dangerously-skip-permissions` or `--yolo` unless the user asked.

## 5. Read results

Read only what the report needs, never the full stream:

| CLI | Final answer | Tokens and cost | Session id |
| --- | --- | --- | --- |
| Claude | last line with `"type":"result"`, its `result` | `usage`, `total_cost_usd`, `modelUsage` | `session_id` |
| Codex | `result.md` | `usage` on the `turn.completed` events | `thread_id` on `thread.started` |
| Agy | `result` in the JSON | when present | `conversation` id when present |
| Kimi | last assistant message | when present | `session` id when present |

Check the `STATUS:` line, then the diff with `git -C <worktree> diff`. A status is a claim; the diff
and your checks decide. A read-only worker that changed files counts as a failure. A `429`, "rate
limit" or "usage limit" in `err.log` means the unit moves to the next provider in the order at the
same tier, as `quota.whenLow` says.

## 6. Integrate and report

Merge or apply the diffs you accept, run the project's checks in the combined checkout, then remove
the worktrees and branches whose changes you handled. Write `<folder>/report.md` and show it:

| Worker | CLI and model | Why | Status | Time | Tokens | Cost | Used |
| --- | --- | --- | --- | --- | --- | --- | --- |

Add the totals, what the spend bought, and what is left to review. Show cost only where the CLI
reported it; never estimate dollars for a CLI that does not report them.

## What you lose without the runner

- No hard budget: count calls and reported tokens yourself after each wave and stop at the limit.
- No `dry-run` estimate: estimate prompt tokens as task characters divided by four, and say so.
- No `diagram.py`: draw the plan as a Mermaid flowchart when the user wants to see it.
- No Windows `.cmd` shim handling: run the commands through your own shell, which handles the shim,
  and keep newlines and quotes inside `task.md` rather than in arguments.
- No `status` or `mark`: keep `<folder>/state.md` with one line per worker (id, phase, status,
  used, partial or discarded) so a compacted session can pick up from it.

## Short commands without the runner

| Words | Do |
| --- | --- |
| `report`, `status` | show `report.md`, or the latest lines of `state.md` |
| `list`, `use <folder>` | list the run folders under the temp folder, newest first; remember the one picked |
| `stop` | stop the background worker processes of the current folder |
| `budget <limit>` | write the limit at the top of `state.md` and check it after every wave |
| `note <text>`, `mark <worker> <mark>` | append it to `state.md`; the report lists notes under "Changes to the plan" |
| `on`, `off`, `save`, `balanced`, `max`, `careful` | keep the mode, goal, care level and rules in this conversation; after a compaction, ask the user whether it is still on |
| `setup` | section 1, then [onboarding.md](onboarding.md) |
