# alethe-orchestrate

An agent skill that turns your coding agent into a planner. It splits work into bounded units,
hands them to Codex, Claude Code, Antigravity, Kimi or any CLI agent you have, and follows
playbooks that keep the lead's context and your quota small. When the work is done, it reports
what each worker did, why, and what it cost.

It needs Python 3.9 or newer and at least one agent CLI. It works on its own; inside
[Alethe](https://github.com/Kc1t/alethe-agents) it can also put workers on Alethe's board.

## Install

**Any agent** (Claude Code, Codex, Cursor, Gemini CLI, Antigravity and others):

```sh
npx skills add Kc1t/alethe-orchestrate
```

**Claude Code plugin:**

```text
/plugin marketplace add Kc1t/alethe-orchestrate
/plugin install alethe-orchestrate@alethe
```

**By hand:** copy `skills/alethe-orchestrate` into your agent's skills folder, such as
`~/.claude/skills/`, `~/.codex/skills/` or `~/.agents/skills/`.

While this repository is private, installing needs access to it and git credentials on your
machine. On GitHub, `gh auth login` followed by `gh auth setup-git` stores them.

## First run

Ask your agent to set up orchestration. It checks the environment, takes inventory of the CLIs,
models and routes you really have, and proposes three profiles over the same playbooks:

| Profile | Models | Provider order | Switches provider at |
| --- | --- | --- | --- |
| Base | Each CLI's usual model per tier | Your main CLIs first | 80% of a usage window |
| Savings | One step cheaper per tier | Cheapest capable CLI first, scarcest subscription last | 70% |
| Aggressive | One step stronger per tier | Strongest CLIs first | 95% |

Nothing is saved until you approve. After that, ask in plain words: "orchestrate this refactor",
"use savings for now", "what did that run cost?".

## How it works

1. **Plan.** The lead, your agent, picks one of eleven playbooks, such as *plan big, execute
   small*, *scout, then build*, *best of N* or *review gate*, and chooses a model and effort per
   worker from the active profile. When a provider is low on quota, as Alethe reports or you tell
   it, the work moves to the next one in your order; when quota would reset unused, it can go to
   the stronger tier. On its own, the skill never guesses usage it cannot read.
2. **Run.** Each wave runs as one batch: no shell, capped concurrency, deadlines, hard budgets, and
   an isolated git worktree for every concurrent writer.
3. **Integrate.** The lead reads short results and diffs, not transcripts, and merges what holds up.
4. **Report.** `report` explains the whole orchestration.

## Report

```text
python scripts/orchestrate.py report <orchestration-folder>
```

Real output from a two-worker run:

```markdown
# Orchestration report

**Check the report on real CLIs**, playbook `research`, 1 wave, 2026-10-18 21:20 to 21:20

- **Result:** 2 of 2 workers succeeded
- **Time:** 16s running, 29s of worker time
- **Tokens:** 108,820 reported, 65,836 of them from cache
- **Cost:** $0.16 reported by claude; codex reports no cost
- **Lead context:** 5.0 KB of worker transcripts stayed on disk, 595 B of results to read

| Worker | Role | Ran on | Mode | Status | Time | Tokens | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `claude-haiku` | cheapest Claude model for a one-line answer | claude, haiku | read | succeeded | 12s | 76,160 | $0.16 |
| `codex-low` | default Codex model at low effort | codex, default model, low | read | succeeded | 16s | 32,660 | - |
```

The report never estimates. Tokens and cost are what each CLI reported; Claude Code reports cost at
API prices, so on a subscription that work counted against your plan's limits instead. It also
lists failures with their last error line, budget stops, changed files, worktrees to review and
sessions you can resume. `--format json` returns the same data.

## Commands

All commands live in `skills/alethe-orchestrate/scripts/orchestrate.py`.

| Command | What it does |
| --- | --- |
| `doctor` | Checks Python, the installed CLIs and the saved policy, with plain hints |
| `playbook` | Prints the playbooks the planner follows; `--init` copies them for editing |
| `scaffold <strategy>` | Prints a starter plan |
| `validate <plan>` | Checks a plan without running it |
| `dry-run <plan>` | Explains the strategy, providers, models and budget a plan would use |
| `run <plan>` | Runs one wave and writes its results to a run folder |
| `report [folder]` | Explains what the runs did, why, and what they reported spending |
| `policy show\|set\|reset` | Shows or changes saved preferences |
| `probe`, `strategies` | Lists the installed CLIs and the runner strategies |

`scripts/diagram.py` renders a dry-run as an SVG architecture preview.

## Files it keeps

| What | Where |
| --- | --- |
| Policy | `%APPDATA%\Alethe\alethe-orchestrate.json` on Windows, `~/.config/alethe/orchestrate.json` elsewhere. `ALETHE_ORCHESTRATE_POLICY` overrides it |
| Your playbooks and profiles | `alethe-playbooks.yaml` next to the policy. `ALETHE_ORCHESTRATE_PLAYBOOKS` overrides it |
| Runs | The temporary directory, or the folder given with `--run-dir` |
| Worktrees | `<repo>/.alethe/worktrees/`, kept until you remove them and excluded from `git status` |

## Safety

- Workers start from argument arrays; nothing runs through a shell.
- Every task carries a contract: no delegation, no commits, pushes, tags or pull requests.
- Flags that remove isolation, such as `--dangerously-skip-permissions` or `--trust-all-tools`,
  are refused unless the plan sets `allowUnsafe` after you agree to it.
- The parallel strategy gives every writer its own worktree, and the runner never stashes or
  commits your checkout.

## With Alethe

Alethe bundles this skill and installs it for Claude Code and Codex. When Alethe is running, the
skill can use its `alethe_*` MCP tools instead of plain CLI workers, which adds the orchestration
board, live steering, approval dialogs and quota readings. Without Alethe, everything above still
works.

## Development

```sh
python -m unittest discover -s tests
python -m pip install pyyaml && python tools/check_playbooks.py
```

The tests run fake CLIs, so they need no agent installed and spend no quota. Alethe vendors this
skill: change it here, then run `npm run skill:sync -- --from <this checkout>` in the Alethe
repository.

## License

MIT. The vendor logos in `skills/alethe-orchestrate/assets/brands/` belong to their owners and are
not covered by the license; the skill uses them only to label each provider in diagrams.
