<a id="readme-top"></a>

<br />
<div align="center">
  <a href="https://github.com/Kc1t/alethe-orchestrate-skill">
    <img src="./docs/assets/alethe.png" alt="Alethe logo" width="120">
  </a>

  <h1 align="center">alethe-orchestrate</h1>

  <p align="center"><b>Orchestrate coding agents, and prove it was worth it.</b></p>

  <p align="center">
    <a href="https://github.com/Kc1t/alethe-orchestrate-skill/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/Kc1t/alethe-orchestrate-skill/actions/workflows/ci.yml/badge.svg"></a>
    <a href="./CHANGELOG.md"><img alt="Skill version" src="https://img.shields.io/badge/skill-v16-4f46e5?style=flat-square"></a>
    <a href="./LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-blue?style=flat-square"></a>
    <img alt="Python 3.9+ optional" src="https://img.shields.io/badge/python-3.9%2B%20optional-3776ab?style=flat-square&logo=python&logoColor=white">
    <img alt="Windows, macOS and Linux" src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-555?style=flat-square">
    <a href="https://agentskills.io"><img alt="Agent Skill" src="https://img.shields.io/badge/Agent%20Skill-SKILL.md-111?style=flat-square"></a>
  </p>

  <p align="center"><b>English</b> · <a href="./README.pt-BR.md">Português (BR)</a></p>
</div>

## Install

```sh
npx skills add Kc1t/alethe-orchestrate-skill
```

Then type `/alethe setup`. After that, ask in plain words: "orchestrate this refactor", "what did that cost?".

<details>
<summary>Claude Code plugin, Codex plugin or by hand</summary>

```text
/plugin marketplace add Kc1t/alethe-orchestrate-skill
/plugin install alethe-orchestrate@alethe
```

```sh
codex plugin marketplace add Kc1t/alethe-orchestrate-skill
codex plugin add alethe-orchestrate@alethe
```

Or copy `skills/alethe-orchestrate` into `~/.claude/skills/`, `~/.codex/skills/` or
`~/.agents/skills/`.

</details>

| Type | It does |
| --- | --- |
| `/alethe <task>` | Orchestrates the task |
| `/alethe always` | Keeps it on in every project, so you never call it again |
| `/alethe on`, `save`, `max`, `careful` | Keeps it on for this project, with that goal or care level |
| `/alethe from now on <instruction>` | Keeps it on, with your instruction as a standing rule |
| `/alethe report`, `status`, `list` | What the current orchestration did and cost |
| `/alethe stop`, `skip <phase>`, `switch <playbook>` | Changes course and records why |
| `/alethe off` | Turns it off here |

## How It Works

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="./docs/assets/drawings/how-it-works-dark.svg">
    <img src="./docs/assets/drawings/how-it-works-light.svg" alt="You ask your agent to orchestrate a refactor. The lead agent picks a playbook, writes the briefs and dry-runs the plan, then orchestrate.py runs one wave of workers: Claude Code on haiku, read-only; Codex at low effort, writing in its own worktree; Antigravity, read-only. They leave result.md, diff.patch and outcome.json while full transcripts stay on disk. The lead reads only the results, checks, integrates and marks them, runs the next wave, and finally writes the orchestration report" width="900">
  </picture>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="./docs/assets/drawings/stay-on-dark.svg">
    <img src="./docs/assets/drawings/stay-on-light.svg" alt="A conversation. The first message says /alethe from now on, be careful with the database, and the lead turns the mode on with careful and keeps the words as a rule. The next messages need no /alethe: a hook reminds the lead of the goal, care and rules each time. It fixes a typo itself because it is too small to hand off, orchestrates moving 40 endpoints with cheap scouts and writers in worktrees, and answers how is it going with a short status. It stays on for the project until /alethe off or 12 hours without a prompt" width="820">
  </picture>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="./docs/assets/drawings/mid-task-dark.svg">
    <img src="./docs/assets/drawings/mid-task-light.svg" alt="A tasks.md from a spec-driven workflow with tasks 1 to 3 done. /alethe joins at task 4. The lead takes the spec and the diff so far as the plan and sends tasks 4 and 5 out: four Codex writers with one worktree per group, two Claude haiku workers fixing the tests, and the coupled part stays with the lead. Task 6, the review gate, stays with the original workflow, whose checks become the gates" width="860">
  </picture>
</p>

## Why It's Different

- **Real spend, never estimated:** tokens and cost as each CLI reported them, split between used and discarded results.
- **Enforced limits:** budgets per wave and per orchestration, a hard cost cap on Claude workers, no subagents.
- **Lean, checked workers:** no MCP servers in Codex and Claude workers, and git catches a read-only worker that wrote.
- **Easy to audit:** Python's standard library only, no shell, no network, no install scripts.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="./docs/assets/drawings/savings-dark.svg">
    <img src="./docs/assets/drawings/savings-light.svg" alt="Two hand-drawn bar charts. Left: one Claude haiku worker on the same one-line task used 76,160 tokens and $0.16 with version 11, and 38,157 tokens and $0.08 with version 12. Right: in a real two-worker run, 5.0 KB of worker transcripts stayed on disk while the lead read 595 bytes of results" width="820">
  </picture>
</p>

## Agents

| Agent | CLI | Read-only work | Writing | Resume | Reports |
|:-:|---|---|---|:-:|---|
| <img src="./docs/assets/agents/claude-code.png" width="28" height="28" alt=""><br>**Claude Code** | `claude` | `plan` permission mode | `acceptEdits` | ✓ | Tokens and cost |
| <img src="./docs/assets/agents/codex.png" width="28" height="28" alt=""><br>**Codex** | `codex` | `read-only` sandbox | `workspace-write` sandbox | ✓ | Tokens |
| <img src="./docs/assets/agents/antigravity.png" width="28" height="28" alt=""><br>**Antigravity** | `agy` | `plan` mode | `accept-edits` mode | ✓ | Tokens |
| <picture><source media="(prefers-color-scheme: dark)" srcset="./docs/assets/agents/kimi-dark.svg"><img src="./docs/assets/agents/kimi-light.svg" width="28" height="28" alt=""></picture><br>**Kimi Code** | `kimi` | Contract, checked afterwards | Prompt mode, in its own worktree | ✓ | Nothing |
| <picture><source media="(prefers-color-scheme: dark)" srcset="./docs/assets/agents/shell-dark.svg"><img src="./docs/assets/agents/shell-light.svg" width="28" height="28" alt=""></picture><br>**Any other CLI** | your adapter | Contract, checked afterwards | Its narrowest write flag | | Whatever its output carries |

Any other CLI with a non-interactive mode, such as Kiro, Copilot CLI or Gemini CLI, runs as a custom worker.

## Playbooks

| Playbook | Use it when | What it saves |
|---|---|---|
| `direct` | The task is narrow and clear, up to about 3 files | All orchestration overhead |
| `cascade` | A mechanical change with an automatic check | Most of the cost, while retries stay rare |
| `scout-then-build` | Unfamiliar code with much to read and little to write | Your context: scouts return summaries, not files |
| `plan-big-execute-small` | Up to about 10 independent reads, audits or checks | The strong tier only decomposes and synthesizes |
| `audit-at-scale` | Dozens or hundreds of similar items | The volume runs on the cheap tier |
| `parallel-worktrees` | Independent modules with disjoint files | Wall time, not tokens |
| `plan-execute` | One feature built in sequential steps | The strong tier is billed only for planning |
| `advisor-escalation` | A long mechanical task with a few hard calls | A strong advisor only at decision points |
| `best-of-n` | A hard, high-stakes fix worth several attempts | Nothing: it buys reliability |
| `review-gate` | A finished diff before merge | Strong review only on diffs worth reviewing |
| `complete` | Anything else; the conditions decide per unit | Each unit runs on the cheapest role that fits |

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="./docs/assets/drawings/change-course-dark.svg">
    <img src="./docs/assets/drawings/change-course-light.svg" alt="Top row, dashed: the scout-then-build playbook, scout, plan, build, review. Bottom row, what ran: scout, plan, a freeform wave to fix the build script because the bug was there, build, and review crossed out because the diff was three lines. The journal.jsonl records each change with its reason, and the report shows them under Changes to the plan" width="820">
  </picture>
</p>

## The Report

> **Orchestration report**
>
> **Check the report on real CLIs**, playbook `research`, 1 wave, 2026-10-18 21:20 to 21:20
>
> - **Result:** 2 of 2 workers succeeded
> - **Time:** 16s running, 29s of worker time
> - **Tokens:** 108,820 reported, 65,836 of them from cache
> - **Cost:** $0.16 reported by claude; codex reports no cost
> - **Lead context:** 5.0 KB of worker transcripts stayed on disk, 595 B of results to read
>
> | Worker | Role | Ran on | Mode | Status | Time | Tokens | Cost |
> | --- | --- | --- | --- | --- | --- | --- | --- |
> | `claude-haiku` | cheapest Claude model for a one-line answer | claude, haiku | read | succeeded | 12s | 76,160 | $0.16 |
> | `codex-low` | default Codex model at low effort | codex, default model, low | read | succeeded | 16s | 32,660 | - |

<details>
<summary>Commands and files</summary>

Your agent runs these for you, from `skills/alethe-orchestrate/scripts/orchestrate.py`:

| Stage | Command | What it does |
| --- | --- | --- |
| Setup | `doctor`, `playbook`, `policy`, `mode` | Checks the CLIs, prints or edits the playbooks and preferences, keeps it on |
| Plan | `scaffold`, `validate`, `dry-run` | Starts, checks and previews a plan |
| Run | `new`, `run --in current`, `budget`, `note`, `stop` | Runs the waves of one orchestration |
| After | `status`, `mark`, `report`, `list`, `use` | Explains and values what ran |

The policy and your playbooks live in `%APPDATA%\Alethe\` on Windows and `~/.config/alethe/`
elsewhere, with one folder per orchestration under `orchestrations/`:

```text
<folder>/
├── budget.json              limits for every wave, optional
├── 01-explore/
│   ├── state.json           the batch at a glance, live while it runs
│   ├── plan.json            the resolved plan, without task text
│   └── workers/<id>/
│       ├── prompt.txt       the brief the worker received
│       ├── result.md        its final answer
│       ├── outcome.json     status, failure kind, metrics, tripwire
│       ├── diff.patch       what a writer changed
│       ├── mark.json        used, partial or discarded, optional
│       └── stdout.log, stderr.log
└── 02-build/
```

</details>

## Video

<table>
  <tr>
    <th width="38%">Video</th>
    <th>What you will see</th>
  </tr>
  <tr>
    <td>
      <a href="https://www.youtube.com/watch?v=8jvrucR7QCU&amp;t=54s">
        <img src="https://i.ytimg.com/vi/8jvrucR7QCU/hqdefault.jpg" alt="Stop Using One AI Agent at a Time: Orchestrate AI Agents" width="100%">
      </a>
    </td>
    <td>
      <strong><a href="https://www.youtube.com/watch?v=8jvrucR7QCU&amp;t=54s">Stop Using One AI Agent at a Time: Orchestrate AI Agents</a></strong>
      <br><br>
      A practical introduction to coordinating several AI coding agents, and to the git worktree
      isolation that keeps them out of each other's way.
      <br><br>
      <sub>Kauã Miguel - Dev · Portuguese</sub>
    </td>
  </tr>
</table>

## Development

```sh
python -m unittest discover -s tests
```

## License

MIT, see [`LICENSE`](LICENSE). The **Alethe** name and logo and the vendor marks belong to their owners. Part of [Alethe](https://github.com/Kc1t/alethe-agents) · [Changelog](CHANGELOG.md) · [Issues](https://github.com/Kc1t/alethe-orchestrate-skill/issues)

<p align="right">(<a href="#readme-top">back to top</a>)</p>
