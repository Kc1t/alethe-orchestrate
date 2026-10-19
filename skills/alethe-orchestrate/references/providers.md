# Provider adapters

Read this reference when choosing a provider, resuming a worker, or defining a custom adapter. The
runner uses argument arrays and never passes commands through a shell.

## Built-in adapters

| Provider | Executable | Read-only | Write | Resume | Structured result |
|---|---|---:|---:|---:|---:|
| Codex | `codex` | sandbox `read-only` | sandbox `workspace-write` | `codex exec resume` | JSONL events + final message |
| Claude Code | `claude` | permission mode `plan` | `acceptEdits` | `--resume` | JSON result |
| Agy / Antigravity | `agy` | mode `plan` | `accept-edits` | `--conversation` | JSON result |
| Kimi Code | `kimi` | worker contract (see below) | `--yolo` | `--session` | stream JSON |

`antigravity` is accepted as an alias for `agy` in plans.

Use `provider: auto` for a new worker with no provider-specific model, effort, or session. The
runner selects the first installed provider in the saved `providerOrder` that is not listed in
`conserveProviders`. Explicit providers are switched only when `providerSwitch` is `automatic`;
otherwise they are honored or validation asks for a decision.

The runner probes optional flags from local help where needed. CLI behavior changes over time, so
check the generated `stderr.log` and `outcome.json` rather than treating process exit alone as
success.

The equivalent new-session command shapes are:

```text
codex exec --json --sandbox read-only|workspace-write --cd <cwd> --output-last-message <result> -
claude --print --output-format json --permission-mode plan|acceptEdits
agy --output-format json --mode plan|accept-edits --print-timeout <seconds>s --print=<task>
kimi --prompt <task> --output-format stream-json [--yolo]
```

Codex and Claude receive the task through standard input. Agy and Kimi require it attached to the
prompt flag: Agy's `--print` otherwise swallows the next flag as the prompt and ignores the real
one, so the runner always uses the attached `--print=<task>` form. Keep stdout and stderr in
separate files and enforce an external deadline even when a provider also offers its own timeout.

Claude `acceptEdits` does not approve every shell command. The runner requests non-interactive
permission handling when the installed CLI supports it; a denied command remains a worker failure
or limitation for the lead to handle.

Kimi cannot combine `--plan` with `--prompt`, so a read-only Kimi worker runs in the default mode
and read-only behavior is enforced by the worker contract instead of a CLI sandbox; prefer Codex,
Claude, or Agy for untrusted read-only investigations. Kimi `--yolo` still follows Kimi's own Ask
When Needed policy. Use isolated worktrees for Kimi writers and do not replace it with `--auto`;
the runner treats `--auto` as an unsafe custom flag.

## Resuming

Copy a successful worker's `sessionId` into a later worker's `resume` field. Keep the provider the
same. A resumed provider controls its original session directory and permission state; the runner
cannot retrofit a new Codex sandbox onto an existing session.

Resume only a closely related follow-up. If no session ID was emitted, create a new worker with a
compact handoff instead.

## Custom CLIs

Use `provider: "custom"` with:

- `command`: executable name or explicit executable path
- `args`: argument array; `{cwd}` and `{result}` placeholders are replaced without shell expansion
- `promptTransport`: `stdin` or `argument`
- `outputFormat`: `text`, `json`, or `jsonl`

Custom adapters do not automatically claim read-only, resume, token, or quota support. Enforce
provider-specific restrictions in its arguments and use an isolated worktree when it can write.
Onboarding records each checked adapter in the playbooks file under `adapters`; build the worker
from that entry.

Give a custom CLI the narrowest tool permission that still lets it write, such as Kiro's
`--trust-tools=fs_read,fs_write` or Copilot's `--allow-tool write`. Known unsafe flags, including
ones that approve every tool such as `--trust-all-tools`, `--allow-all-tools` and `--yolo`, are
rejected unless `allowUnsafe` is true. Set that field only after the user explicitly authorizes the
loss of isolation.

## Unsupported MCP features

Plain CLI workers do not appear on Alethe's orchestration board. The runner cannot provide live
mid-turn steering, approval dialogs, or quota readings that a provider does not expose. Use the
`alethe_*` MCP tools when those capabilities matter.
