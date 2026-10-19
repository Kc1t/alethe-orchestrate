# Playbook file reference

`scripts/orchestrate.py playbook` prints the effective playbooks file. This page explains its
fields so the lead can follow it and the user can edit it. `playbook --init` copies the bundled
file next to the saved policy for editing; delete that copy to return to the bundled defaults.
Onboarding fills that copy from what the user has; see [onboarding.md](onboarding.md).

## Top level

| Field | Meaning |
|---|---|
| `setup` | Written by onboarding: the `date` the user approved the profiles and `notes` on what was found or skipped |
| `principles` | Saving rules that apply to every plan |
| `providers` | The CLIs the user approved, in the base order of preference |
| `models` | Model ids each CLI listed, optionally as `{ id, cost }` with the CLI's cost multiplier |
| `adapters` | A checked custom adapter for each provider without a built-in one |
| `routes` | Gateways on the model traffic path, such as `router9` |
| `tiers` | What `cheap`, `standard` and `strong` mean per provider: a model and an effort |
| `quota.criticalThreshold` | Percent of any main usage window that counts as low on tokens |
| `quota.whenLow` | `switch-provider` runs a role on the next provider in the order at the same tier; `keep` stays |
| `quota.onBothCritical` | `ask`, `run-cheapest` or `block` when every provider in the order is low |
| `quota.whenSpare` | What to do with a provider's spare quota: `spend-strong` runs workers on its strong tier, `prefer` runs them on it at their own tier, `ignore` changes nothing |
| `quota.spareWithinHours` | A weekly or monthly cycle that resets within this many hours counts as spare |
| `quota.spareMinLeft` | Percent of that cycle that must be left for it to count as spare |
| `quota.planEnds` | Dates a plan ends without renewing, by provider, for example `{ codex: "2026-10-20" }` |
| `budget.warnAt` | Percent of the plan budget that counts as low |
| `budget.whenLow` | `finish-and-report`, `downgrade-tier` or `stop` |
| `profile` | The active profile |
| `profiles` | Named sets of overrides, usually `base`, `savings` and `aggressive` |
| `pickOrder` | Which playbook to pick for which kind of task, checked top to bottom |
| `playbooks` | The playbooks, by id |
| `routing` | Optional; maps one delegation's kind and effort to a role, exported by the UI |

## Providers

`claude`, `codex`, `agy` and `kimi` have built-in adapters. Any other CLI, such as `kiro`,
`copilot` or `gemini`, runs as a `custom` worker built from its entry in `adapters`:

| Field | Meaning |
|---|---|
| `command`, `args` | The executable and the arguments before the prompt |
| `promptTransport`, `outputFormat` | As in a custom worker: `stdin` or `argument`; `text`, `json` or `jsonl` |
| `modelFlag`, `effortFlag` | The flags that take a model id and an effort, when the CLI has them |
| `checked` | The help command that confirmed the invocation, and when |

A custom adapter cannot enforce read-only work, so `auto` never sends it a `readOnly` phase. Add
the tier's model and effort through its flags when building the worker.

A route carries a CLI's API traffic; it is not a worker. `routes.router9` records the `port`,
whether it is `running`, and which CLIs it `carries`: only `claude` and `codex` speak its dialects.
Model names for a carried CLI go to whatever the gateway maps them to. Never start, install or
reconfigure a route; Alethe does that.

## Profiles

The active profile changes three things and leaves the playbooks alone:

| Field | Effect |
|---|---|
| `order` | Replaces the order of `providers`; providers it leaves out are tried last |
| `quota` | Overrides those `quota` fields |
| `tiers` | Overrides the model and effort of the tier and provider entries it names |

`base` usually has no overrides. Switch profiles by changing `profile`, after confirming when it is
an ongoing change rather than one run.

## Phases

A playbook lists `phases`. Each phase is one role:

| Field | Meaning |
|---|---|
| `id` | Unique within the playbook |
| `role` | The name used in briefs and shown to the user |
| `who` | `lead` is you, in this session; anything else is a worker wave |
| `tier` | `cheap`, `standard` or `strong`, resolved through the active tiers |
| `provider` | `auto` (default) takes the first provider in the active order that can run the phase; a provider id pins it |
| `model`, `effort` | Override the tier for this phase |
| `readOnly` | Run workers with `mode: read` |
| `workers` | Units in the wave, within the runner's limit |
| `isolate` | Give each writer its own worktree |
| `runner` | The plan `strategy` for the wave: `economy`, `balanced`, `quality`, `research`, `parallel` or `rescue` |
| `does`, `returns`, `limit` | What to put in each brief and what to ask back |
| `gate` | What you check after the phase before moving on |
| `if` | The phase runs only when the condition holds |
| `with` | Joins that phase's step. When any path in the step has `if`, the paths are alternatives and the first whose `if` holds runs; when none has `if`, they all run in the same wave |
| `after` | Runs only after the `gate` of that phase fails, or after that escalation phase |
| `then` | `next` (default), `recheck` (check the gate again) or `done` (stop here) |
| `rules` | Model choices for this role, checked top to bottom: `if` a condition, `use` a tier, provider, model or effort |

## Choosing the model

For each worker:

1. Start from the phase's tier and provider, with the active profile's tiers and order.
2. Apply the first rule whose `if` holds. Skip a rule whose model belongs to a different provider
   unless it also names that provider.
3. If the provider it lands on is low on tokens and `quota.whenLow` is `switch-provider`, move to the
   next provider in the order that can run the phase, at the same tier and effort. A rule that
   names a provider keeps it.
4. If every provider is low, follow `quota.onBothCritical`.
5. If a provider has spare quota, apply `quota.whenSpare` to the worker. Skip this when the budget
   is low, when the chosen rule has a quota or budget condition, or when the phase or rule pins a
   different provider. When several are spare, use the one that loses its quota first.

Always pass the resulting model and effort explicitly in the plan. A worker without them runs on its
CLI's default model.

## Usage windows

| Provider | Main windows | Cycle used for spare quota |
|---|---|---|
| `claude` | `5h`, `week` (plus `opus`) | week |
| `codex` | `5h`, `week` | week |
| `agy` | `gemini`, `claude` (plus `gpt`) | none |
| `kimi` | `5h`, `week` (plus `month`) | week |
| `kiro` | `credits` | monthly credits |
| `copilot` | `premium` | monthly premium requests |
| `gemini` | `day` | none |

Alethe reads Claude, Codex, Antigravity and Kimi usage. For the others, ask the user, or treat the
provider as not low.

## Spare quota

A provider's quota is spare when it is not low, at least `spareMinLeft` percent of its cycle is
left, and that quota would be lost: its plan ends before the cycle resets, or the cycle resets
within `spareWithinHours`. A plan that ends in 2 days while the week resets in 6 loses everything
left, so spending it on the strong tier costs nothing.

## Conditions

`if` takes one condition or a list; a list holds when all of them hold. Prefix one with `not ` to
negate it. `<provider>` is any provider id and `<window>` one of its windows above.

| Condition | Holds when |
|---|---|
| `narrow` | The task is small and clear, up to about 3 files |
| `kind:<kind>` | The unit's kind is `research`, `code`, `review`, `command`, `scrap` or `docs` |
| `light`, `standard`, `deep` | The unit's effort class |
| `<provider>-low` | A main window of that provider is past `criticalThreshold`, it is listed in `conserveProviders`, or the user said its tokens are running out |
| `all-low` | Every provider in the order is low; `both-low` means the same |
| `<provider>-above:<n>` | The busiest main window of that provider is past n percent |
| `<provider>-<window>-above:<n>` | That window is past n percent, for example `claude-opus-above:50` or `codex-week-above:80` |
| `<provider>-spare` | That provider has spare quota |
| `budget-low` | More than `budget.warnAt` percent of the plan budget is spent |
| `checks-failed`, `checks-failed-twice` | The phase's checks failed once, or twice |
| `report-weak` | A report lacks the evidence it was asked for |
| `conflict` | Reports contradict each other |
| `stuck` | A worker stopped at a decision it could not make |
| `no-pass` | No attempt passed |
| `findings-left` | Confirmed review findings remain |

In skill-only mode no live quota reading exists. Treat a provider as low only when Alethe reported
it, the user said so, or the policy lists it in `conserveProviders`. Treat it as spare only when
Alethe or the user gave its usage and reset time, and the plan end comes from `quota.planEnds` or
the user. Ignore a `planEnds` date that has passed.
