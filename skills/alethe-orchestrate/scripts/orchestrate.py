#!/usr/bin/env python3
"""Run bounded CLI-agent batches without a shell or third-party packages."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


PLAN_VERSION = 1
STATE_VERSION = 1
POLICY_VERSION = 1
MAX_WORKERS = 16
DEFAULT_TIMEOUT_SECONDS = 1200
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SAFE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
NOTE_LIMITS = {"title": 120, "why": 500, "workerWhy": 300}
WORKTREE_EXCLUDE = "/.alethe/worktrees/"
EXCLUDE_LOCK = threading.Lock()
RAN_STATUSES = ("succeeded", "failed", "timed_out")
UNSAFE_FLAGS = {
    "--dangerously-bypass-approvals-and-sandbox",
    "--dangerously-skip-permissions",
    "--auto",
    "--trust-all-tools",
    "--allow-all-tools",
    "--yolo",
}
BATCH_SUFFIXES = (".cmd", ".bat")
BATCH_UNSAFE = re.compile(r'["&|<>^%!\r\n]')
PROVIDER_ALIASES = {"antigravity": "agy"}
BUILTIN_PROVIDERS = ("codex", "claude", "agy", "kimi")
PROVIDER_CAPABILITIES: Dict[str, Dict[str, bool]] = {
    "codex": {
        "structuredOutput": True,
        "readOnly": True,
        "write": True,
        "resume": True,
        "tokenUsage": True,
    },
    "claude": {
        "structuredOutput": True,
        "readOnly": True,
        "write": True,
        "resume": True,
        "tokenUsage": True,
    },
    "agy": {
        "structuredOutput": True,
        "readOnly": True,
        "write": True,
        "resume": True,
        "tokenUsage": True,
    },
    "kimi": {
        "structuredOutput": True,
        "readOnly": False,
        "write": True,
        "resume": True,
        "tokenUsage": False,
    },
    "custom": {
        "structuredOutput": False,
        "readOnly": False,
        "write": True,
        "resume": False,
        "tokenUsage": False,
    },
}
STRATEGY_ALIASES = {"performance": "parallel"}
STRATEGIES: Dict[str, Dict[str, Any]] = {
    "auto": {
        "maxWorkers": MAX_WORKERS,
        "maxConcurrent": 4,
        "description": "Choose the smallest strategy supported by the plan.",
    },
    "economy": {
        "maxWorkers": 1,
        "maxConcurrent": 1,
        "description": "Minimize agent usage with one concise worker and no speculative fan-out.",
    },
    "balanced": {
        "maxWorkers": 4,
        "maxConcurrent": 2,
        "description": "Use a small general-purpose batch for independent work.",
    },
    "quality": {
        "maxWorkers": 1,
        "maxConcurrent": 1,
        "description": "Run writer, reviewer, and repair work as separate sequential waves.",
    },
    "research": {
        "maxWorkers": 8,
        "maxConcurrent": 4,
        "description": "Compare independent read-only investigations with compact evidence.",
    },
    "parallel": {
        "maxWorkers": 8,
        "maxConcurrent": 4,
        "description": "Implement disjoint units concurrently; every writer uses a worktree.",
    },
    "rescue": {
        "maxWorkers": 1,
        "maxConcurrent": 1,
        "description": "Resume one interrupted or failed provider session without restarting the work.",
    },
}
DEFAULT_POLICY: Dict[str, Any] = {
    "version": POLICY_VERSION,
    "onboarded": False,
    "backend": "auto",
    "defaultStrategy": "auto",
    "providerSwitch": "ask",
    "providerOrder": list(BUILTIN_PROVIDERS),
    "conserveProviders": [],
    "maxWorkers": MAX_WORKERS,
    "maxConcurrent": 4,
    "budget": {},
    "modelTiers": {},
}
BUDGET_FIELDS = (
    "maxCalls",
    "maxWallSeconds",
    "maxEstimatedPromptTokens",
    "maxReportedCostUsd",
    "maxReportedTokens",
)
ORCHESTRATION_BUDGET_FIELDS = ("maxCalls", "maxReportedCostUsd", "maxReportedTokens")
ORCHESTRATION_BUDGET_FILE = "budget.json"
MAX_BUDGET_CALLS = 64
MODEL_TIERS = ("cheap", "standard", "strong")
MODEL_TIER_KEYS = ("cheap", "strong")
COST_REPORTING_PROVIDERS = ("claude",)
ARGUMENT_PROMPT_LIMIT = 30000 if os.name == "nt" else 100000
WORKER_ENV_FLAG = "ALETHE_ORCHESTRATE_WORKER"
POLL_SECONDS = 1.0
STATE_REFRESH_SECONDS = 5.0
FINGERPRINT_MAX_BYTES = 20 * 1024 * 1024
SNAPSHOT_LIMIT = 5000
MAX_LISTED_PATHS = 50
NESTED_AGENT_FEATURES = ("multi_agent", "multi_agent_v2")
CLAUDE_AGENT_TOOLS = "Agent,Workflow"
WORKER_STATUSES = ("DONE", "DONE_WITH_CONCERNS", "BLOCKED", "NEEDS_CONTEXT")
VERDICTS = ("PASS", "FAIL", "NOT_PROVEN")
MARKS = ("used", "partial", "discarded")
SHORT_TASK_CHARS = 400
HANDOFF_LINE = re.compile(
    r"^[\s>*_`#-]*(STATUS|SUMMARY|VERDICT)[*_`]*\s*:[*_`\s]*(.+?)[*_`\s]*$", re.MULTILINE | re.IGNORECASE
)
FAILURE_HINTS = {
    "rate_limited": "the provider hit a usage limit; run the unit on the next provider in the order, or after the reset",
    "auth_required": "log in to the CLI or check its subscription, then run the unit again",
    "not_installed": "install the CLI or pick another provider",
    "stalled": "it went quiet for too long; resume its session or narrow the task",
    "timed_out": "it ran out of time; resume its session or narrow the task",
    "budget": "a budget stopped it; raise the budget or drop the unit",
    "budget_exceeded": "its own cost cap stopped it; raise maxReportedCostUsd or narrow the task",
    "invalid_output": "its output did not parse; check stderr.log and the CLI version",
}
ERROR_LINE = re.compile(r"\berror\b|\bfailed\b|denied|forbidden|exception|\b4\d\d\b|\b5\d\d\b", re.IGNORECASE)
FAILURE_PATTERNS = (
    ("rate_limited", re.compile(r"\b429\b|rate.?limit|usage limit|quota|too many requests|hit your (?:\w+ )?limit", re.I)),
    (
        "auth_required",
        re.compile(
            r"\b40[13]\b|auth_error|unauthori[sz]ed|forbidden|not logged in|please log ?in|login required"
            r"|invalid api key|subscription does not have access",
            re.I,
        ),
    ),
    ("budget_exceeded", re.compile(r"max.?budget|budget exceeded", re.I)),
)
WORKER_CONTRACT = """

Runtime contract:
- Work only on this assigned unit and only inside the stated scope.
- Do not delegate, spawn subagents, or launch another agent CLI.
- Do not commit, push, tag, release, or open a pull request.
- End with a concise handoff: outcome, evidence, files changed, checks run, failures, and risks.
- Finish with a line `STATUS: DONE`, `STATUS: DONE_WITH_CONCERNS`, `STATUS: BLOCKED` or
  `STATUS: NEEDS_CONTEXT`, then a line `SUMMARY: <one sentence>`. Use BLOCKED or NEEDS_CONTEXT
  instead of guessing, and put what you need in the handoff.
""".strip()


class PlanError(ValueError):
    pass


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise PlanError(f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise PlanError(f"invalid JSON in {path}: {error}") from error


def read_optional_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def skill_version() -> Optional[str]:
    try:
        text = (Path(__file__).resolve().parent.parent / "SKILL.md").read_text(encoding="utf-8")
    except OSError:
        return None
    frontmatter = text.split("\n---", 1)[0]
    match = re.search(r'^\s+version:\s*"?([0-9][0-9.]*)"?\s*$', frontmatter, re.MULTILINE)
    return match.group(1) if match else None


def default_policy_path() -> Path:
    configured = os.environ.get("ALETHE_ORCHESTRATE_POLICY")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "Alethe" / "alethe-orchestrate.json"
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "alethe" / "orchestrate.json"


PLAYBOOKS_FILE = "playbooks.yaml"
USER_PLAYBOOKS_FILE = "alethe-playbooks.yaml"


def bundled_playbooks_path() -> Path:
    return Path(__file__).resolve().parent.parent / PLAYBOOKS_FILE


def user_playbooks_path(policy_path: Path) -> Path:
    configured = os.environ.get("ALETHE_ORCHESTRATE_PLAYBOOKS")
    if configured:
        return Path(configured).expanduser()
    return policy_path.with_name(USER_PLAYBOOKS_FILE)


def effective_playbooks_path(policy_path: Path) -> Path:
    user = user_playbooks_path(policy_path)
    return user if user.is_file() else bundled_playbooks_path()


def read_playbooks(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise PlanError(f"cannot read playbooks at {path}: {error}") from error
    if not re.search(r"^version:\s*1\s*$", text, re.MULTILINE):
        raise PlanError(f"{path} must declare 'version: 1'")
    return text


def init_playbooks(policy_path: Path, force: bool) -> Path:
    target = user_playbooks_path(policy_path)
    if target.exists() and not force:
        raise PlanError(f"{target} already exists; pass --force to replace it with the bundled playbooks")
    text = read_playbooks(bundled_playbooks_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, target)
    return target


def normalized_strategy(value: Any, label: str) -> str:
    strategy = require_string(value, label).lower()
    strategy = STRATEGY_ALIASES.get(strategy, strategy)
    if strategy not in STRATEGIES:
        raise PlanError(f"{label} must be one of {', '.join(STRATEGIES)}")
    return strategy


def validate_provider_list(value: Any, label: str, *, allow_empty: bool) -> List[str]:
    if not isinstance(value, list):
        raise PlanError(f"{label} must be an array")
    providers: List[str] = []
    for raw in value:
        provider = require_string(raw, label).lower()
        provider = PROVIDER_ALIASES.get(provider, provider)
        if provider not in BUILTIN_PROVIDERS:
            raise PlanError(f"{label} contains unsupported provider {provider}")
        if provider not in providers:
            providers.append(provider)
    if not allow_empty and not providers:
        raise PlanError(f"{label} must contain at least one provider")
    return providers


def validate_budget(raw: Any, label: str) -> Dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise PlanError(f"{label} must be an object")
    unknown = set(raw) - set(BUDGET_FIELDS)
    if unknown:
        raise PlanError(f"{label} has unknown fields: {', '.join(sorted(unknown))}")
    budget: Dict[str, Any] = {}
    max_calls = raw.get("maxCalls")
    if max_calls is not None:
        if not isinstance(max_calls, int) or isinstance(max_calls, bool):
            raise PlanError(f"{label}.maxCalls must be an integer")
        if not 1 <= max_calls <= MAX_BUDGET_CALLS:
            raise PlanError(f"{label}.maxCalls must be between 1 and {MAX_BUDGET_CALLS}")
        budget["maxCalls"] = max_calls
    max_wall = raw.get("maxWallSeconds")
    if max_wall is not None:
        if not isinstance(max_wall, int) or isinstance(max_wall, bool):
            raise PlanError(f"{label}.maxWallSeconds must be an integer")
        if not 1 <= max_wall <= 86400:
            raise PlanError(f"{label}.maxWallSeconds must be between 1 and 86400")
        budget["maxWallSeconds"] = max_wall
    max_tokens = raw.get("maxEstimatedPromptTokens")
    if max_tokens is not None:
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens < 1:
            raise PlanError(f"{label}.maxEstimatedPromptTokens must be a positive integer")
        budget["maxEstimatedPromptTokens"] = max_tokens
    max_cost = raw.get("maxReportedCostUsd")
    if max_cost is not None:
        if not isinstance(max_cost, (int, float)) or isinstance(max_cost, bool) or max_cost <= 0:
            raise PlanError(f"{label}.maxReportedCostUsd must be a positive number")
        budget["maxReportedCostUsd"] = max_cost
    max_reported = raw.get("maxReportedTokens")
    if max_reported is not None:
        if not isinstance(max_reported, int) or isinstance(max_reported, bool) or max_reported < 1:
            raise PlanError(f"{label}.maxReportedTokens must be a positive integer")
        budget["maxReportedTokens"] = max_reported
    return budget


def estimated_prompt_tokens(text: str) -> int:
    """Prompt-only chars/4 heuristic; provider-side context is additional and not estimable."""
    return max(1, -(-len(text) // 4))


def reported_total_tokens(usage: Any) -> Optional[int]:
    if not isinstance(usage, dict):
        return None
    for key in ("total_tokens", "totalTokens"):
        value = usage.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
    # No explicit total: sum the parts. Codex's input_tokens already includes its
    # cached_input_tokens, so the cached field is deliberately not added.
    parts = [
        usage.get(key)
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        )
    ]
    numeric = [int(value) for value in parts if isinstance(value, (int, float)) and not isinstance(value, bool)]
    return sum(numeric) if numeric else None


def validate_model_tiers(raw: Any, label: str) -> Dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise PlanError(f"{label} must be an object")
    unknown = set(raw) - set(MODEL_TIER_KEYS)
    if unknown:
        raise PlanError(f"{label} has unknown tiers: {', '.join(sorted(unknown))}")
    tiers: Dict[str, Any] = {}
    for tier, mapping in raw.items():
        if not isinstance(mapping, dict):
            raise PlanError(f"{label}.{tier} must be an object")
        entries: Dict[str, Any] = {}
        for raw_provider, spec in mapping.items():
            provider = PROVIDER_ALIASES.get(str(raw_provider).lower(), str(raw_provider).lower())
            if provider not in BUILTIN_PROVIDERS:
                raise PlanError(f"{label}.{tier} contains unsupported provider {provider}")
            if not isinstance(spec, dict):
                raise PlanError(f"{label}.{tier}.{provider} must be an object")
            unknown_spec = set(spec) - {"model", "effort"}
            if unknown_spec:
                raise PlanError(
                    f"{label}.{tier}.{provider} has unknown fields: {', '.join(sorted(unknown_spec))}"
                )
            model = optional_name(spec.get("model"), f"{label}.{tier}.{provider}.model")
            effort = optional_name(spec.get("effort"), f"{label}.{tier}.{provider}.effort")
            if not model and not effort:
                raise PlanError(f"{label}.{tier}.{provider} must set model or effort")
            entries[provider] = {
                key: value for key, value in (("model", model), ("effort", effort)) if value
            }
        if entries:
            tiers[tier] = entries
    return tiers


def resolve_model_tier(worker: Dict[str, Any], policy: Dict[str, Any]) -> None:
    tier = worker["tier"]
    if tier == "standard":
        worker["modelNote"] = None
        return
    spec = policy["modelTiers"].get(tier, {}).get(worker["provider"], {})
    if spec:
        worker["model"] = spec.get("model")
        worker["effort"] = spec.get("effort")
        parts = ", ".join(f"{key} {value}" for key, value in spec.items())
        worker["modelNote"] = f"tier {tier} on {worker['provider']}: {parts}"
    else:
        worker["model"] = None
        worker["effort"] = None
        worker["modelNote"] = f"tier {tier}: no model configured for {worker['provider']}"


def validate_policy(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise PlanError("policy must be a JSON object")
    unknown = set(raw) - set(DEFAULT_POLICY)
    if unknown:
        raise PlanError(f"unknown policy fields: {', '.join(sorted(unknown))}")
    if raw.get("version", POLICY_VERSION) != POLICY_VERSION:
        raise PlanError(f"policy.version must be {POLICY_VERSION}")
    onboarded = raw.get("onboarded", False)
    if not isinstance(onboarded, bool):
        raise PlanError("policy.onboarded must be a boolean")
    backend = raw.get("backend", DEFAULT_POLICY["backend"])
    if backend not in ("auto", "skill", "mcp"):
        raise PlanError("policy.backend must be auto, skill or mcp")
    provider_switch = raw.get("providerSwitch", DEFAULT_POLICY["providerSwitch"])
    if provider_switch not in ("ask", "automatic", "never"):
        raise PlanError("policy.providerSwitch must be ask, automatic or never")
    max_workers = raw.get("maxWorkers", DEFAULT_POLICY["maxWorkers"])
    max_concurrent = raw.get("maxConcurrent", DEFAULT_POLICY["maxConcurrent"])
    for label, value in (("maxWorkers", max_workers), ("maxConcurrent", max_concurrent)):
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= MAX_WORKERS:
            raise PlanError(f"policy.{label} must be between 1 and {MAX_WORKERS}")
    return {
        "version": POLICY_VERSION,
        "onboarded": onboarded,
        "backend": backend,
        "defaultStrategy": normalized_strategy(
            raw.get("defaultStrategy", DEFAULT_POLICY["defaultStrategy"]),
            "policy.defaultStrategy",
        ),
        "providerSwitch": provider_switch,
        "providerOrder": validate_provider_list(
            raw.get("providerOrder", DEFAULT_POLICY["providerOrder"]),
            "policy.providerOrder",
            allow_empty=False,
        ),
        "conserveProviders": validate_provider_list(
            raw.get("conserveProviders", DEFAULT_POLICY["conserveProviders"]),
            "policy.conserveProviders",
            allow_empty=True,
        ),
        "maxWorkers": max_workers,
        "maxConcurrent": max_concurrent,
        "budget": validate_budget(raw.get("budget"), "policy.budget"),
        "modelTiers": validate_model_tiers(raw.get("modelTiers"), "policy.modelTiers"),
    }


def load_policy(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return dict(DEFAULT_POLICY)
    return validate_policy(read_json(path))


def save_policy(path: Path, policy: Dict[str, Any]) -> None:
    atomic_write_json(path, validate_policy(policy))


def available_builtin_providers() -> List[str]:
    commands = {"agy": "agy"}
    return [
        provider
        for provider in BUILTIN_PROVIDERS
        if shutil.which(commands.get(provider, provider)) is not None
    ]


def choose_provider(requested: str, worker: Dict[str, Any], policy: Dict[str, Any]) -> str:
    if requested == "custom":
        return requested
    available = available_builtin_providers()
    conserved = set(policy["conserveProviders"])
    read_only = worker.get("mode") == "read-only"
    candidates = [
        provider
        for provider in policy["providerOrder"]
        if provider in available
        and provider not in conserved
        and (not read_only or PROVIDER_CAPABILITIES[provider]["readOnly"])
    ]
    if worker.get("resume") and requested == "auto":
        raise PlanError(
            f"worker {worker['id']} must name the provider that owns its resumed session"
        )
    if requested == "auto":
        if worker.get("model") or worker.get("effort"):
            raise PlanError(f"worker {worker['id']} cannot combine provider auto with model or effort")
        if not candidates:
            needed = "read-only " if read_only else ""
            raise PlanError(f"no unconserved built-in provider can run a {needed}worker")
        return candidates[0]
    if requested not in conserved:
        return requested
    switch = policy["providerSwitch"]
    if switch == "never":
        return requested
    if switch == "ask":
        raise PlanError(
            f"provider {requested} is marked for conservation; choose another provider or enable automatic switching"
        )
    alternatives = [provider for provider in candidates if provider != requested]
    if not alternatives:
        raise PlanError(f"no available provider can replace conserved provider {requested}")
    if worker.get("model") or worker.get("effort") or worker.get("resume"):
        raise PlanError(
            f"worker {worker['id']} pins provider-specific state and cannot switch automatically"
        )
    return alternatives[0]


def infer_strategy(workers: Sequence[Dict[str, Any]]) -> Tuple[str, str]:
    if len(workers) == 1:
        if workers[0].get("resume"):
            return "rescue", "one resumed worker session"
        return "economy", "one new worker"
    if all(worker["mode"] == "read-only" for worker in workers):
        return "research", f"{len(workers)} read-only workers"
    writers = [worker for worker in workers if worker["mode"] == "write"]
    if len(writers) >= 2 and all(worker["isolate"] for worker in writers):
        return "parallel", f"{len(writers)} isolated writers"
    return "balanced", "mixed modes or a non-isolated writer"


def enforce_strategy(
    requested: str,
    workers: Sequence[Dict[str, Any]],
    requested_concurrency: Optional[int],
    policy: Dict[str, Any],
) -> Tuple[str, int]:
    strategy = infer_strategy(workers)[0] if requested == "auto" else requested
    rules = STRATEGIES[strategy]
    max_workers = min(rules["maxWorkers"], policy["maxWorkers"])
    if len(workers) > max_workers:
        raise PlanError(f"strategy {strategy} allows at most {max_workers} workers")
    if strategy == "research" and any(worker["mode"] != "read-only" for worker in workers):
        raise PlanError("strategy research accepts read-only workers only")
    if strategy == "parallel" and any(
        worker["mode"] == "write" and not worker["isolate"] for worker in workers
    ):
        raise PlanError("strategy parallel requires every writer to use isolate: true")
    if strategy == "rescue" and (len(workers) != 1 or not workers[0].get("resume")):
        raise PlanError("strategy rescue requires exactly one worker with resume")
    concurrency = requested_concurrency or rules["maxConcurrent"]
    concurrency = min(concurrency, rules["maxConcurrent"], policy["maxConcurrent"])
    return strategy, concurrency


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlanError(f"{label} must be a non-empty string")
    return value.strip()


def optional_name(value: Any, label: str) -> Optional[str]:
    if value is None:
        return None
    text = require_string(value, label)
    if not SAFE_NAME_PATTERN.fullmatch(text) or text.startswith("-"):
        raise PlanError(f"{label} contains unsafe characters")
    return text


def optional_note(value: Any, label: str, limit: int) -> Optional[str]:
    if value is None:
        return None
    text = " ".join(require_string(value, label).split())
    if len(text) > limit:
        raise PlanError(f"{label} must be at most {limit} characters")
    return text


def normalized_provider(value: Any) -> str:
    provider = require_string(value, "worker.provider").lower()
    provider = PROVIDER_ALIASES.get(provider, provider)
    if provider != "auto" and provider not in PROVIDER_CAPABILITIES:
        raise PlanError(f"unsupported provider {provider}; use provider custom for another CLI")
    return provider


def validate_relative_path(value: Any, label: str) -> str:
    text = require_string(value, label).replace("\\", "/")
    path = Path(text)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise PlanError(f"{label} must be a safe relative path")
    return text


def load_task(worker: Dict[str, Any], plan_dir: Path) -> str:
    inline = worker.get("task")
    task_file = worker.get("taskFile")
    if (inline is None) == (task_file is None):
        raise PlanError(f"worker {worker.get('id', '?')} must set exactly one of task or taskFile")
    if inline is not None:
        task = require_string(inline, "worker.task")
    else:
        path = Path(require_string(task_file, "worker.taskFile"))
        if not path.is_absolute():
            path = plan_dir / path
        try:
            task = path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise PlanError(f"cannot read task file {path}: {error}") from error
        if not task:
            raise PlanError(f"task file {path} is empty")
    return f"{task.rstrip()}\n\n{WORKER_CONTRACT}\n"


def validate_plan(
    raw: Any,
    plan_path: Path,
    policy: Optional[Dict[str, Any]] = None,
    strategy_override: Optional[str] = None,
) -> Dict[str, Any]:
    policy = validate_policy(policy or DEFAULT_POLICY)
    if not isinstance(raw, dict):
        raise PlanError("plan must be a JSON object")
    unknown = set(raw) - {
        "version",
        "title",
        "why",
        "playbook",
        "phase",
        "strategy",
        "preset",
        "maxConcurrent",
        "defaultTimeoutSeconds",
        "budget",
        "workers",
    }
    if unknown:
        raise PlanError(f"unknown plan fields: {', '.join(sorted(unknown))}")
    if raw.get("version") != PLAN_VERSION:
        raise PlanError(f"plan.version must be {PLAN_VERSION}")
    title = optional_note(raw.get("title"), "plan.title", NOTE_LIMITS["title"])
    why = optional_note(raw.get("why"), "plan.why", NOTE_LIMITS["why"])
    playbook = optional_name(raw.get("playbook"), "plan.playbook")
    phase = optional_name(raw.get("phase"), "plan.phase")
    if strategy_override is None and "strategy" in raw and "preset" in raw:
        raise PlanError("use strategy, not strategy and legacy preset together")
    strategy_value = strategy_override or raw.get(
        "strategy", raw.get("preset", policy["defaultStrategy"])
    )
    requested_strategy = normalized_strategy(strategy_value, "plan.strategy")
    requested_concurrency = raw.get("maxConcurrent")
    if requested_concurrency is not None:
        if not isinstance(requested_concurrency, int) or isinstance(requested_concurrency, bool):
            raise PlanError("maxConcurrent must be an integer")
        if not 1 <= requested_concurrency <= MAX_WORKERS:
            raise PlanError(f"maxConcurrent must be between 1 and {MAX_WORKERS}")
    default_timeout = raw.get("defaultTimeoutSeconds", DEFAULT_TIMEOUT_SECONDS)
    if not isinstance(default_timeout, int) or isinstance(default_timeout, bool):
        raise PlanError("defaultTimeoutSeconds must be an integer")
    if not 1 <= default_timeout <= 86400:
        raise PlanError("defaultTimeoutSeconds must be between 1 and 86400")
    workers = raw.get("workers")
    if not isinstance(workers, list) or not workers:
        raise PlanError("workers must be a non-empty array")
    if len(workers) > MAX_WORKERS:
        raise PlanError(f"a plan may contain at most {MAX_WORKERS} workers")

    seen = set()
    normalized_workers: List[Dict[str, Any]] = []
    for index, item in enumerate(workers):
        if not isinstance(item, dict):
            raise PlanError(f"workers[{index}] must be an object")
        unknown = set(item) - {
            "id",
            "why",
            "provider",
            "mode",
            "cwd",
            "task",
            "taskFile",
            "timeoutSeconds",
            "isolate",
            "seedPaths",
            "model",
            "effort",
            "tier",
            "resume",
            "command",
            "args",
            "promptTransport",
            "outputFormat",
            "allowUnsafe",
            "mcp",
            "idleTimeoutSeconds",
        }
        if unknown:
            raise PlanError(
                f"worker {item.get('id', index)} has unknown fields: {', '.join(sorted(unknown))}"
            )
        worker_id = require_string(item.get("id"), f"workers[{index}].id")
        if not ID_PATTERN.fullmatch(worker_id):
            raise PlanError(f"worker id {worker_id!r} is not safe")
        if worker_id in seen:
            raise PlanError(f"duplicate worker id {worker_id}")
        seen.add(worker_id)
        requested_provider = normalized_provider(item.get("provider"))
        mode = item.get("mode", "read-only")
        if mode not in ("read-only", "write"):
            raise PlanError(f"worker {worker_id} mode must be read-only or write")
        cwd = Path(require_string(item.get("cwd"), f"worker {worker_id}.cwd")).expanduser()
        if not cwd.is_absolute():
            cwd = (plan_path.parent / cwd).resolve()
        if not cwd.is_dir():
            raise PlanError(f"worker {worker_id} cwd is not a directory: {cwd}")
        timeout = item.get("timeoutSeconds", default_timeout)
        if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 86400:
            raise PlanError(f"worker {worker_id} timeoutSeconds must be between 1 and 86400")
        isolate = item.get("isolate", False)
        if not isinstance(isolate, bool):
            raise PlanError(f"worker {worker_id} isolate must be a boolean")
        if isolate and mode != "write":
            raise PlanError(f"worker {worker_id} only needs isolate in write mode")
        seed_paths = item.get("seedPaths", [])
        if not isinstance(seed_paths, list):
            raise PlanError(f"worker {worker_id} seedPaths must be an array")
        seed_paths = [
            validate_relative_path(value, f"worker {worker_id}.seedPaths") for value in seed_paths
        ]
        if seed_paths and not isolate:
            raise PlanError(f"worker {worker_id} seedPaths requires isolate")
        model = optional_name(item.get("model"), f"worker {worker_id}.model")
        effort = optional_name(item.get("effort"), f"worker {worker_id}.effort")
        tier = item.get("tier", "standard")
        if tier not in MODEL_TIERS:
            raise PlanError(f"worker {worker_id} tier must be one of {', '.join(MODEL_TIERS)}")
        if tier != "standard" and (model or effort):
            raise PlanError(
                f"worker {worker_id} cannot combine tier {tier} with an explicit model or effort"
            )
        resume = optional_name(item.get("resume"), f"worker {worker_id}.resume")
        if resume and isolate:
            raise PlanError(f"worker {worker_id} cannot combine resume with isolate")
        mcp = item.get("mcp", False)
        if not isinstance(mcp, bool):
            raise PlanError(f"worker {worker_id} mcp must be a boolean")
        idle_timeout = item.get("idleTimeoutSeconds")
        if idle_timeout is not None and (
            not isinstance(idle_timeout, int) or isinstance(idle_timeout, bool) or not 5 <= idle_timeout <= 86400
        ):
            raise PlanError(f"worker {worker_id} idleTimeoutSeconds must be between 5 and 86400")
        task = load_task(item, plan_path.parent)
        normalized = {
            "id": worker_id,
            "why": optional_note(item.get("why"), f"worker {worker_id}.why", NOTE_LIMITS["workerWhy"]),
            "provider": requested_provider,
            "requestedProvider": requested_provider,
            "mode": mode,
            "cwd": str(cwd),
            "timeoutSeconds": timeout,
            "isolate": isolate,
            "seedPaths": seed_paths,
            "model": model,
            "effort": effort,
            "tier": tier,
            "resume": resume,
            "mcp": mcp,
            "idleTimeoutSeconds": idle_timeout,
            "task": task,
        }
        if requested_provider == "custom":
            normalized.update(validate_custom(item, worker_id))
        chosen_provider = choose_provider(requested_provider, normalized, policy)
        normalized["provider"] = chosen_provider
        if chosen_provider == requested_provider:
            normalized["routingNote"] = None
        elif requested_provider == "auto":
            normalized["routingNote"] = "selected by provider order"
        else:
            normalized["routingNote"] = (
                f"conserved provider {requested_provider} replaced by providerSwitch=automatic"
            )
        resolve_model_tier(normalized, policy)
        prompt_in_argument = chosen_provider in ("agy", "kimi") or (
            chosen_provider == "custom" and normalized["promptTransport"] == "argument"
        )
        if prompt_in_argument and len(task) > ARGUMENT_PROMPT_LIMIT:
            raise PlanError(
                f"worker {worker_id} task is {len(task)} characters, but {chosen_provider} takes its prompt "
                f"as an argument limited to {ARGUMENT_PROMPT_LIMIT} here; shorten it or point to files"
            )
        normalized["estimatedPromptTokens"] = estimated_prompt_tokens(task)
        normalized_workers.append(normalized)

    budget = {**policy["budget"], **validate_budget(raw.get("budget"), "plan.budget")}
    token_limit = budget.get("maxEstimatedPromptTokens")
    if token_limit is not None:
        estimate = sum(worker["estimatedPromptTokens"] for worker in normalized_workers)
        if estimate > token_limit:
            raise PlanError(
                f"estimated prompt tokens {estimate} exceed budget maxEstimatedPromptTokens {token_limit}"
            )

    strategy, max_concurrent = enforce_strategy(
        requested_strategy, normalized_workers, requested_concurrency, policy
    )
    if strategy == "economy":
        # Economy means the cheapest run: default its single worker to the cheap tier unless
        # the plan already pinned a tier or a model.
        worker = normalized_workers[0]
        if worker["tier"] == "standard" and not worker["model"] and not worker["effort"]:
            worker["tier"] = "cheap"
            resolve_model_tier(worker, policy)

    return {
        "version": PLAN_VERSION,
        "title": title,
        "why": why,
        "playbook": playbook,
        "phase": phase,
        "strategy": strategy,
        "requestedStrategy": requested_strategy,
        "maxConcurrent": max_concurrent,
        "defaultTimeoutSeconds": default_timeout,
        "budget": budget,
        "policy": policy,
        "workers": normalized_workers,
    }


def validate_custom(worker: Dict[str, Any], worker_id: str) -> Dict[str, Any]:
    command = require_string(worker.get("command"), f"worker {worker_id}.command")
    args = worker.get("args", [])
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise PlanError(f"worker {worker_id}.args must be an array of strings")
    transport = worker.get("promptTransport", "stdin")
    if transport not in ("stdin", "argument"):
        raise PlanError(f"worker {worker_id}.promptTransport must be stdin or argument")
    output_format = worker.get("outputFormat", "text")
    if output_format not in ("text", "json", "jsonl"):
        raise PlanError(f"worker {worker_id}.outputFormat must be text, json or jsonl")
    allow_unsafe = worker.get("allowUnsafe", False)
    if not isinstance(allow_unsafe, bool):
        raise PlanError(f"worker {worker_id}.allowUnsafe must be a boolean")
    if not allow_unsafe and any(arg in UNSAFE_FLAGS for arg in args):
        raise PlanError(f"worker {worker_id} uses an unsafe flag without allowUnsafe")
    return {
        "command": command,
        "args": args,
        "promptTransport": transport,
        "outputFormat": output_format,
        "allowUnsafe": allow_unsafe,
    }


def run_git(
    cwd: Path, args: Sequence[str], input_bytes: Optional[bytes] = None, timeout: float = 300
) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise PlanError(f"git {' '.join(args)} timed out after {timeout:g}s") from error
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise PlanError(f"git {' '.join(args)} failed: {message}")
    return result.stdout


def is_inside(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath([str(path.resolve()), str(root.resolve())]) == str(root.resolve())
    except ValueError:
        return False


def reject_seed_symlinks(path: Path) -> None:
    if path.is_symlink():
        raise PlanError(f"seed path is a symlink: {path}")
    if not path.is_dir():
        return
    for current, directories, files in os.walk(path, followlinks=False):
        for name in [*directories, *files]:
            candidate = Path(current) / name
            if candidate.is_symlink():
                raise PlanError(f"seed path contains a symlink: {candidate}")


def exclude_worktrees(root: Path) -> None:
    with EXCLUDE_LOCK:
        ignored = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "-q", ".alethe/worktrees/probe"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode == 0
        if ignored:
            return
        exclude = Path(run_git(root, ["rev-parse", "--git-path", "info/exclude"]).decode().strip())
        if not exclude.is_absolute():
            exclude = root / exclude
        existing = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(WORKTREE_EXCLUDE + "\n")


def prepare_worktree(worker: Dict[str, Any], run_id: str) -> Path:
    origin = Path(worker["cwd"])
    root = Path(run_git(origin, ["rev-parse", "--show-toplevel"]).decode().strip()).resolve()
    target = root / ".alethe" / "worktrees" / f"skill-{run_id}-{worker['id']}"
    if target.exists():
        raise PlanError(f"worktree target already exists: {target}")
    exclude_worktrees(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    run_git(root, ["worktree", "add", "--detach", str(target), "HEAD"])

    seed_paths: List[str] = worker["seedPaths"]
    if seed_paths:
        patch = run_git(root, ["diff", "--binary", "HEAD", "--", *seed_paths])
        if patch.strip():
            run_git(target, ["apply", "-"], patch)
        for relative in seed_paths:
            source = root / relative
            if not source.exists() and not source.is_symlink():
                continue
            tracked = subprocess.run(
                ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", relative],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode == 0
            if tracked:
                continue
            if not is_inside(source, root):
                raise PlanError(f"seed path escapes the repository: {relative}")
            reject_seed_symlinks(source)
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination, symlinks=True, dirs_exist_ok=True)
            else:
                shutil.copy2(source, destination, follow_symlinks=False)
    return target


def command_output(args: Sequence[str], cache: Dict[str, str], lock: threading.Lock) -> str:
    key = "\0".join(args)
    with lock:
        if key in cache:
            return cache[key]
    try:
        result = subprocess.run(
            list(args),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        output = result.stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        output = ""
    with lock:
        cache[key] = output
    return output


def command_help(launch: Sequence[str], cache: Dict[str, str], lock: threading.Lock) -> str:
    return command_output([*launch, "--help"], cache, lock)


def resolve_executable(name: str) -> str:
    expanded = str(Path(name).expanduser())
    if os.path.dirname(expanded):
        path = Path(expanded)
        if not path.is_file():
            raise PlanError(f"executable not found: {name}")
        return str(path.resolve())
    resolved = shutil.which(name)
    if not resolved:
        raise PlanError(f"executable not found on PATH: {name}")
    return resolved


def is_batch_file(executable: str) -> bool:
    return os.name == "nt" and Path(executable).suffix.lower() in BATCH_SUFFIXES


def shim_target(shim: Path) -> Optional[List[str]]:
    try:
        text = shim.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    lines = [line for line in text.splitlines() if "%*" in line]
    if not lines:
        return None
    head = lines[-1].split("%*", 1)[0].rsplit("&", 1)[-1]
    tokens = re.findall(r'"([^"]+)"', head)
    if not tokens or re.sub(r'"[^"]*"', "", head).strip():
        return None
    folder = str(shim.parent) + "\\"
    launch: List[str] = []
    for token in tokens:
        if token == "%_prog%":
            bundled = shim.parent / "node.exe"
            node = str(bundled) if bundled.is_file() else shutil.which("node")
            if not node:
                return None
            launch.append(node)
            continue
        value = token.replace("%~dp0", folder).replace("%dp0%", folder)
        if "%" in value or not Path(value).is_file():
            return None
        launch.append(str(Path(value).resolve()))
    return launch


def launch_command(executable: str) -> List[str]:
    if not is_batch_file(executable):
        return [executable]
    # cmd.exe cuts a batch argument at a newline and runs what follows an unbalanced quote.
    return shim_target(Path(executable)) or [executable]


def refuse_batch_arguments(args: Sequence[str]) -> None:
    if not is_batch_file(args[0]):
        return
    if any(BATCH_UNSAFE.search(arg) for arg in args[1:]):
        raise PlanError(
            f"{Path(args[0]).name} is a batch file and cmd.exe would rewrite its arguments; "
            "point the worker at the real executable or send the prompt through stdin"
        )


def in_git_worktree(cwd: Path) -> bool:
    return subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--is-inside-work-tree"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def build_invocation(
    worker: Dict[str, Any],
    cwd: Path,
    worker_dir: Path,
    help_cache: Dict[str, str],
    help_lock: threading.Lock,
    timeout: int,
    cost_cap: Optional[float] = None,
) -> Tuple[List[str], bool, str, Path]:
    provider = worker["provider"]
    mode = worker["mode"]
    model = worker["model"]
    effort = worker["effort"]
    resume = worker["resume"]
    result_path = worker_dir / "result.md"

    if provider == "codex":
        launch = launch_command(resolve_executable("codex"))
        features = command_output([*launch, "features", "list"], help_cache, help_lock)
        args = list(launch)
        for feature in NESTED_AGENT_FEATURES:
            if re.search(rf"^{feature}\s", features, re.MULTILINE):
                args += ["--disable", feature]
        sandbox = "read-only" if mode == "read-only" else "workspace-write"
        args += ["exec", "--sandbox", sandbox]
        if resume:
            args.append("resume")
        args += ["--json", "--output-last-message", str(result_path)]
        if not resume:
            args += ["--cd", str(cwd)]
        if model:
            args += ["--model", model]
        if effort:
            args += ["--config", f"model_reasoning_effort={effort}"]
        if not worker["mcp"]:
            args += ["--config", "mcp_servers={}"]
        if not in_git_worktree(cwd):
            args.append("--skip-git-repo-check")
        if resume:
            args.append(resume)
        args.append("-")
        return args, True, "jsonl", result_path

    if provider == "claude":
        launch = launch_command(resolve_executable("claude"))
        permission = "plan" if mode == "read-only" else "acceptEdits"
        args = [
            *launch,
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            permission,
        ]
        help_text = command_help(launch, help_cache, help_lock)
        if "--permission-prompts" in help_text:
            args += ["--permission-prompts", "none"]
        if "--disable-slash-commands" in help_text:
            args.append("--disable-slash-commands")
        if "--disallowedTools" in help_text:
            args += ["--disallowedTools", CLAUDE_AGENT_TOOLS]
        if not worker["mcp"] and "--strict-mcp-config" in help_text:
            args.append("--strict-mcp-config")
        if cost_cap is not None and "--max-budget-usd" in help_text:
            args += ["--max-budget-usd", f"{cost_cap:.2f}"]
        if model:
            args += ["--model", model]
        if effort:
            args += ["--effort", effort]
        if resume:
            args += ["--resume", resume]
        return args, True, "jsonl", result_path

    if provider == "agy":
        launch = launch_command(resolve_executable("agy"))
        agent_mode = "plan" if mode == "read-only" else "accept-edits"
        # The prompt must be attached to --print: agy otherwise treats the next flag as the
        # prompt and drops the real one.
        args = [
            *launch,
            "--output-format",
            "json",
            "--mode",
            agent_mode,
            "--print-timeout",
            f"{timeout}s",
        ]
        help_text = command_help(launch, help_cache, help_lock)
        if "--disable-slash-commands" in help_text:
            args.append("--disable-slash-commands")
        if "--add-dir" in help_text:
            args += ["--add-dir", str(cwd)]
        if model:
            args += ["--model", model]
        if effort:
            args += ["--effort", effort]
        if resume:
            args += ["--conversation", resume]
        args.append(f"--print={worker['task']}")
        return args, False, "json", result_path

    if provider == "kimi":
        launch = launch_command(resolve_executable("kimi"))
        # Prompt mode always runs in Kimi's auto permission mode and refuses --plan and --yolo.
        args = [*launch, "--output-format", "stream-json"]
        if model:
            args += ["--model", model]
        if resume:
            args += ["--session", resume]
        args.append(f"--prompt={worker['task']}")
        return args, False, "jsonl", result_path

    launch = launch_command(resolve_executable(worker["command"]))
    replacements = {"{cwd}": str(cwd), "{result}": str(result_path)}
    custom_args = []
    for raw in worker["args"]:
        value = raw
        for marker, replacement in replacements.items():
            value = value.replace(marker, replacement)
        custom_args.append(value)
    stdin_prompt = worker["promptTransport"] == "stdin"
    if not stdin_prompt:
        custom_args.append(worker["task"])
    return [*launch, *custom_args], stdin_prompt, worker["outputFormat"], result_path


def worker_environment() -> Dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if key != "CLAUDECODE"}
    environment[WORKER_ENV_FLAG] = "1"
    return environment


def start_process(
    args: Sequence[str],
    cwd: Path,
    stdin: Any,
    stdout: Any,
    stderr: Any,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.Popen:
    refuse_batch_arguments(args)
    options: Dict[str, Any] = {
        "args": list(args),
        "cwd": str(cwd),
        "stdin": stdin,
        "stdout": stdout,
        "stderr": stderr,
        "shell": False,
        "env": env,
    }
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        options["start_new_session"] = True
    return subprocess.Popen(**options)


def stop_process_tree(process: subprocess.Popen) -> None:
    if os.name == "nt":
        if process.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def feed_stdin(stream: Any, data: bytes) -> None:
    def write() -> None:
        try:
            stream.write(data)
            stream.close()
        except (OSError, ValueError):
            pass

    threading.Thread(target=write, daemon=True).start()


def exit_code_of(process: subprocess.Popen) -> int:
    return process.returncode if process.returncode is not None else -1


def watch_process(
    process: subprocess.Popen,
    worker_id: str,
    timeout: int,
    idle_timeout: Optional[int],
    logs: Sequence[Path],
    state: "BatchState",
) -> Tuple[int, Optional[str]]:
    started = time.monotonic()
    last_size = 0
    last_change = last_refresh = started
    while True:
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            stop_process_tree(process)
            return exit_code_of(process), "timed_out"
        try:
            return process.wait(timeout=min(POLL_SECONDS, remaining)), None
        except subprocess.TimeoutExpired:
            pass
        now = time.monotonic()
        size = sum(file_bytes(path) for path in logs)
        if size != last_size:
            last_size, last_change = size, now
        if idle_timeout is not None and now - last_change >= idle_timeout:
            stop_process_tree(process)
            return exit_code_of(process), "stalled"
        if now - last_refresh >= STATE_REFRESH_SECONDS:
            last_refresh = now
            state.update_worker(worker_id, {"outputBytes": size, "idleSeconds": round(now - last_change)})


def json_values(text: str, output_format: str) -> List[Any]:
    if not text.strip():
        return []
    if output_format == "json":
        try:
            return [json.loads(text)]
        except json.JSONDecodeError:
            pass
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return [json.loads(line)]
                except json.JSONDecodeError:
                    continue
        return []
    if output_format == "jsonl":
        values = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                values.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return values
    return []


def text_from_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    for key in ("result", "output", "text", "content", "response"):
        text = value.get(key)
        if isinstance(text, str) and text.strip():
            return text.strip()
    message = value.get("message")
    if isinstance(message, str):
        return message.strip()
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
            return "".join(parts).strip()
    for key in ("part", "data", "response"):
        nested = value.get(key)
        if isinstance(nested, dict):
            text = text_from_value(nested)
            if text:
                return text
    return ""


def result_text_from_values(values: Sequence[Any]) -> str:
    for value in reversed(values):
        if isinstance(value, dict) and value.get("type") == "result":
            text = text_from_value(value)
            if text:
                return text
    chunks = []
    for value in values:
        if not isinstance(value, dict):
            continue
        kind = value.get("type") or value.get("role")
        if kind not in ("assistant", "message", "text", "output"):
            continue
        text = text_from_value(value)
        if text:
            chunks.append(text)
    if chunks:
        return "\n".join(chunks).strip()
    for value in reversed(values):
        text = text_from_value(value)
        if text:
            return text
    return ""


def extract_session(values: Sequence[Any]) -> Optional[str]:
    for value in reversed(values):
        if not isinstance(value, dict):
            continue
        for key in (
            "session_id",
            "sessionId",
            "sessionID",
            "conversation_id",
            "conversationId",
            "thread_id",
        ):
            session = value.get(key)
            if isinstance(session, str) and session.strip():
                return session.strip()
    return None


def extract_metrics(values: Sequence[Any]) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {}
    for value in values:
        if not isinstance(value, dict):
            continue
        usage = value.get("usage") or value.get("tokenUsage") or value.get("token_usage")
        if isinstance(usage, dict):
            metrics["usage"] = usage
        cost = value.get("total_cost_usd")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            metrics["totalCostUsd"] = cost
        part = value.get("part")
        if isinstance(part, dict):
            tokens = part.get("tokens")
            if isinstance(tokens, dict):
                metrics["usage"] = tokens
            part_cost = part.get("cost")
            if isinstance(part_cost, (int, float)) and not isinstance(part_cost, bool):
                metrics["totalCostUsd"] = part_cost
    return metrics


def classify_result(
    provider: str,
    output_format: str,
    stdout_path: Path,
    result_path: Path,
    exit_code: int,
    timed_out: bool,
) -> Tuple[str, str, List[Any], Optional[str]]:
    stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace")
    values = json_values(stdout_text, output_format)
    error: Optional[str] = None
    text = ""

    if result_path.is_file():
        text = result_path.read_text(encoding="utf-8", errors="replace").strip()
    else:
        text = stdout_text.strip() if output_format == "text" else result_text_from_values(values)
        if text:
            result_path.write_text(text + "\n", encoding="utf-8")

    if timed_out:
        return "timed_out", text, values, "worker exceeded its deadline"
    if exit_code != 0:
        return "failed", text, values, f"worker exited with status {exit_code}"
    if output_format in ("json", "jsonl") and not values:
        return "failed", text, values, "worker output was not valid structured JSON"
    if provider in ("claude", "agy") and values:
        final = values[-1]
        if isinstance(final, dict):
            if final.get("is_error") is True or str(final.get("subtype", "")).startswith("error"):
                error = f"worker returned {final.get('subtype', 'an error result')}"
            if provider == "claude" and final.get("type") != "result":
                error = "Claude output did not end with a result object"
    if error:
        return "failed", text, values, error
    if not text:
        return "failed", text, values, "worker produced no final result"
    return "succeeded", text, values, None


def capture_diff(cwd: Path, worker_dir: Path, isolated: bool) -> Tuple[Optional[Path], Optional[str]]:
    if not in_git_worktree(cwd):
        return None, None
    try:
        run_git(cwd, ["rev-parse", "--verify", "--quiet", "HEAD"], timeout=30)
    except PlanError:
        return None, "the repository has no commits yet, so there is no diff to capture"
    try:
        if isolated:
            untracked = run_git(cwd, ["ls-files", "--others", "--exclude-standard", "-z"])
            paths = [
                value.decode("utf-8", errors="surrogateescape")
                for value in untracked.split(b"\0")
                if value
            ]
            if paths:
                run_git(cwd, ["add", "-N", "--", *paths])
        status = run_git(cwd, ["status", "--short"])
        (worker_dir / "status.txt").write_bytes(status)
        patch = run_git(cwd, ["diff", "--binary", "HEAD"])
    except PlanError as error:
        return None, str(error)
    if not patch.strip():
        return None, None
    diff_path = worker_dir / "diff.patch"
    diff_path.write_bytes(patch)
    return diff_path, None


def checkout_root(cwd: Path) -> Optional[Path]:
    try:
        return Path(run_git(cwd, ["rev-parse", "--show-toplevel"], timeout=30).decode().strip()).resolve()
    except PlanError:
        return None


def file_fingerprint(path: Path) -> str:
    try:
        if path.is_symlink():
            return "link:" + os.readlink(path)
        if path.is_dir():
            return "dir"
        size = path.stat().st_size
        if size > FINGERPRINT_MAX_BYTES:
            return f"size:{size}:{path.stat().st_mtime_ns}"
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "missing"


def checkout_snapshot(root: Path, ignore: Sequence[Path] = ()) -> Optional[Dict[str, str]]:
    try:
        raw = run_git(root, ["status", "--porcelain=v1", "-z", "--untracked-files=all"], timeout=120)
    except PlanError:
        return None
    tokens = raw.decode("utf-8", errors="surrogateescape").split("\0")
    entries: Dict[str, str] = {}
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if len(token) < 4:
            continue
        code, path = token[:2], token[3:]
        if "R" in code or "C" in code:
            index += 1
        absolute = root / path
        if any(is_inside(absolute, folder) for folder in ignore):
            continue
        entries[path] = f"{code}:{file_fingerprint(absolute)}"
        if len(entries) > SNAPSHOT_LIMIT:
            return None
    return entries


def changed_paths(before: Dict[str, str], after: Dict[str, str]) -> List[str]:
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


class CheckoutRegistry:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active: Dict[Path, Dict[str, str]] = {}
        self.overlaps: Dict[str, Dict[str, str]] = {}

    def enter(self, root: Path, worker_id: str, mode: str) -> None:
        with self.lock:
            active = self.active.setdefault(root, {})
            mine = self.overlaps.setdefault(worker_id, {})
            for other, other_mode in active.items():
                mine[other] = other_mode
                self.overlaps.setdefault(other, {})[worker_id] = mode
            active[worker_id] = mode

    def leave(self, root: Path, worker_id: str) -> Dict[str, str]:
        with self.lock:
            self.active.get(root, {}).pop(worker_id, None)
            return dict(self.overlaps.pop(worker_id, {}))


def parse_handoff(text: str) -> Dict[str, Optional[str]]:
    status = verdict = summary = None
    for match in HANDOFF_LINE.finditer(text or ""):
        key, value = match.group(1).upper(), match.group(2).strip()
        if key == "STATUS":
            candidate = value.split()[0].strip(".,;:").upper()
            status = candidate if candidate in WORKER_STATUSES else status
        elif key == "VERDICT":
            candidate = re.sub(r"[\s-]+", "_", value.strip(".,;: ")).upper()
            verdict = next((option for option in VERDICTS if candidate.startswith(option)), verdict)
        else:
            summary = value
    if summary and len(summary) > NOTE_LIMITS["workerWhy"]:
        summary = summary[: NOTE_LIMITS["workerWhy"] - 3].rstrip() + "..."
    return {"workerStatus": status, "workerSummary": summary, "verdict": verdict}


def extract_details(values: Sequence[Any]) -> Dict[str, List[str]]:
    denials: List[str] = []
    billed: List[str] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        raw = value.get("permission_denials")
        if isinstance(raw, list):
            denials = [
                str(item.get("tool_name") or item.get("toolName") or "tool") if isinstance(item, dict) else "tool"
                for item in raw
            ]
        usage = value.get("modelUsage")
        if isinstance(usage, dict) and usage:
            billed = sorted(str(key) for key in usage)
    return {"permissionDenials": denials, "billedModels": billed}


def tail_text(path: Path, lines: int = 20) -> str:
    size = file_bytes(path)
    if not size:
        return ""
    with path.open("rb") as handle:
        handle.seek(max(0, size - 65536))
        text = handle.read().decode("utf-8", errors="replace")
    kept = [line for line in text.splitlines() if line.strip()]
    return "\n".join(kept[-lines:])


def classify_failure(
    status: str, error: Optional[str], stderr_path: Path, result_text: str, stalled: bool
) -> Tuple[Optional[str], Optional[str]]:
    if status == "succeeded":
        return None, None
    if stalled:
        return "stalled", None
    if status == "timed_out":
        return "timed_out", None
    if str(error or "").startswith("executable not found"):
        return "not_installed", None
    text = "\n".join(part for part in (error or "", tail_text(stderr_path), (result_text or "")[-4000:]) if part)
    for kind, pattern in FAILURE_PATTERNS:
        if pattern.search(text):
            if kind != "rate_limited":
                return kind, None
            reset = re.search(r"\b(?:resets?|try again|retry)\b[^\n.]{0,60}", text, re.IGNORECASE)
            return kind, reset.group(0).strip() if reset else None
    if "structured JSON" in str(error) or "result object" in str(error):
        return "invalid_output", None
    if "no final result" in str(error):
        return "no_result", None
    return "error", None


class BatchState:
    def __init__(self, path: Path, initial: Dict[str, Any]) -> None:
        self.path = path
        self.value = initial
        self.lock = threading.Lock()
        atomic_write_json(self.path, self.value)

    def update_worker(self, worker_id: str, patch: Dict[str, Any]) -> None:
        with self.lock:
            self.value["workers"][worker_id].update(patch)
            atomic_write_json(self.path, self.value)

    def finish(self, status: str, extra: Optional[Dict[str, Any]] = None) -> None:
        with self.lock:
            self.value["status"] = status
            self.value["finishedAt"] = now_iso()
            if extra:
                self.value.update(extra)
            atomic_write_json(self.path, self.value)


class ProcessRegistry:
    def __init__(self) -> None:
        self.processes: Dict[int, subprocess.Popen] = {}
        self.lock = threading.Lock()

    def add(self, process: subprocess.Popen) -> None:
        with self.lock:
            self.processes[process.pid] = process

    def remove(self, process: subprocess.Popen) -> None:
        with self.lock:
            self.processes.pop(process.pid, None)

    def stop_all(self) -> None:
        with self.lock:
            processes = list(self.processes.values())
        for process in processes:
            stop_process_tree(process)


def orchestration_refusal(
    limits: Dict[str, Any],
    used: Dict[str, Any],
    calls: int = 0,
    cost: Optional[float] = None,
    tokens: Optional[int] = None,
) -> Optional[str]:
    max_calls = limits.get("maxCalls")
    if max_calls is not None and int(used.get("calls") or 0) + calls >= max_calls:
        return f"orchestration budget maxCalls {max_calls} exhausted"
    spent = [value for value in (number(used.get("reportedCostUsd")), cost) if value is not None]
    max_cost = limits.get("maxReportedCostUsd")
    if max_cost is not None and spent and sum(spent) >= max_cost:
        return f"orchestration budget maxReportedCostUsd {max_cost} exhausted"
    counted = [value for value in (number(used.get("reportedTokens")), tokens) if value is not None]
    max_tokens = limits.get("maxReportedTokens")
    if max_tokens is not None and counted and sum(counted) >= max_tokens:
        return f"orchestration budget maxReportedTokens {max_tokens} exhausted"
    return None


class BudgetTracker:
    """Thread-safe batch budget. Gates are checked at worker submit time, so with
    maxConcurrent > 1 they are approximate: already-running workers finish."""

    def __init__(
        self,
        budget: Dict[str, Any],
        outer: Optional[Dict[str, Any]] = None,
        max_concurrent: int = 1,
        workers: int = 1,
    ) -> None:
        self.budget = budget
        self.outer_limits: Dict[str, Any] = (outer or {}).get("limits", {})
        self.outer_used: Dict[str, Any] = (outer or {}).get("used", {})
        self.max_concurrent = max_concurrent
        self.workers = workers
        self.finished: set = set()
        self.reserved: Dict[str, float] = {}
        self.lock = threading.Lock()
        self.calls = 0
        self.started_clock = time.monotonic()
        self.reported_cost = 0.0
        self.cost_seen = False
        self.reported_tokens = 0
        self.tokens_seen = False

    def remaining_wall(self) -> Optional[float]:
        limit = self.budget.get("maxWallSeconds")
        if limit is None:
            return None
        return limit - (time.monotonic() - self.started_clock)

    def remaining_cost(self) -> Optional[float]:
        limits = []
        plan_limit = self.budget.get("maxReportedCostUsd")
        if plan_limit is not None:
            limits.append(plan_limit - self.reported_cost)
        outer_limit = self.outer_limits.get("maxReportedCostUsd")
        if outer_limit is not None:
            limits.append(outer_limit - (number(self.outer_used.get("reportedCostUsd")) or 0) - self.reported_cost)
        return min(limits) if limits else None

    def refusal(self) -> Optional[str]:
        max_calls = self.budget.get("maxCalls")
        if max_calls is not None and self.calls >= max_calls:
            return f"budget maxCalls {max_calls} exhausted"
        max_wall = self.budget.get("maxWallSeconds")
        if max_wall is not None and time.monotonic() - self.started_clock >= max_wall:
            return f"budget maxWallSeconds {max_wall} exhausted"
        max_cost = self.budget.get("maxReportedCostUsd")
        if max_cost is not None and self.cost_seen and self.reported_cost >= max_cost:
            return f"budget maxReportedCostUsd {max_cost} exhausted"
        max_tokens = self.budget.get("maxReportedTokens")
        if max_tokens is not None and self.tokens_seen and self.reported_tokens >= max_tokens:
            return f"budget maxReportedTokens {max_tokens} exhausted"
        return orchestration_refusal(
            self.outer_limits,
            self.outer_used,
            self.calls,
            self.reported_cost if self.cost_seen else None,
            self.reported_tokens if self.tokens_seen else None,
        )

    def admit(self, worker_id: str, wants_cost_cap: bool = False) -> Tuple[Optional[str], Optional[float]]:
        with self.lock:
            refusal = self.refusal()
            if refusal is not None:
                return refusal, None
            cap = None
            remaining = self.remaining_cost() if wants_cost_cap else None
            if remaining is not None:
                free = remaining - sum(self.reserved.values())
                pending = self.workers - len(self.finished)
                slots = max(1, min(self.max_concurrent, pending) - len(self.reserved))
                cap = math.floor(max(0.0, free) / slots * 100) / 100
                if cap < 0.01:
                    return "budget maxReportedCostUsd leaves less than $0.01 for this worker", None
                self.reserved[worker_id] = cap
            self.calls += 1
            return None, cap

    def finish(self, worker_id: str, metrics: Dict[str, Any]) -> None:
        with self.lock:
            if worker_id in self.finished:
                return
            self.finished.add(worker_id)
            self.reserved.pop(worker_id, None)
            cost = metrics.get("totalCostUsd")
            if isinstance(cost, (int, float)) and not isinstance(cost, bool):
                self.cost_seen = True
                self.reported_cost += cost
            tokens = reported_total_tokens(metrics.get("usage"))
            if tokens is not None:
                self.tokens_seen = True
                self.reported_tokens += tokens

    def usage(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "calls": self.calls,
                "wallSeconds": round(time.monotonic() - self.started_clock, 3),
                "reportedCostUsd": round(self.reported_cost, 6) if self.cost_seen else None,
                "reportedTokens": self.reported_tokens if self.tokens_seen else None,
            }


def run_worker(
    worker: Dict[str, Any],
    run_id: str,
    run_dir: Path,
    state: BatchState,
    help_cache: Dict[str, str],
    help_lock: threading.Lock,
    registry: ProcessRegistry,
    tracker: BudgetTracker,
    checkouts: CheckoutRegistry,
) -> Dict[str, Any]:
    worker_id = worker["id"]
    worker_dir = run_dir / "workers" / worker_id
    worker_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = worker_dir / "prompt.txt"
    stdout_path = worker_dir / "stdout.log"
    stderr_path = worker_dir / "stderr.log"
    outcome_path = worker_dir / "outcome.json"
    prompt_path.write_text(worker["task"], encoding="utf-8")
    started_clock = time.monotonic()
    outcome: Dict[str, Any] = {
        "id": worker_id,
        "provider": worker["provider"],
        "status": "failed",
        "exitCode": None,
        "timedOut": False,
        "startedAt": now_iso(),
        "finishedAt": None,
        "durationSeconds": 0.0,
        "cwd": worker["cwd"],
        "worktree": None,
        "resultPath": None,
        "stdoutPath": None,
        "stderrPath": None,
        "diffPath": None,
        "diffError": None,
        "sessionId": None,
        "metrics": {},
        "costCapUsd": None,
        "error": None,
        "failureKind": None,
        "resetHint": None,
        "workerStatus": None,
        "workerSummary": None,
        "verdict": None,
        "permissionDenials": [],
        "billedModels": [],
        "readOnlyViolation": None,
        "touchedFiles": None,
        "dirtyBefore": None,
        "sharedCheckoutWith": [],
    }

    def settle(**fields: Any) -> Dict[str, Any]:
        outcome.update(fields)
        outcome["finishedAt"] = now_iso()
        outcome["durationSeconds"] = round(time.monotonic() - started_clock, 3)
        atomic_write_json(outcome_path, outcome)
        state.update_worker(worker_id, outcome)
        return outcome

    refusal, cost_cap = tracker.admit(worker_id, worker["provider"] == "claude")
    if refusal is not None:
        tracker.finish(worker_id, {})
        return settle(status="skipped", error=refusal, failureKind="budget")

    process: Optional[subprocess.Popen] = None
    root: Optional[Path] = None
    metrics: Dict[str, Any] = {}
    try:
        cwd = prepare_worktree(worker, run_id) if worker["isolate"] else Path(worker["cwd"])
        outcome.update(cwd=str(cwd), worktree=str(cwd) if worker["isolate"] else None, costCapUsd=cost_cap)
        timeout = worker["timeoutSeconds"]
        remaining_wall = tracker.remaining_wall()
        if remaining_wall is not None:
            timeout = max(1, int(min(timeout, remaining_wall)))
        args, stdin_prompt, output_format, result_path = build_invocation(
            worker, cwd, worker_dir, help_cache, help_lock, timeout, cost_cap
        )
        before = None
        if not worker["isolate"]:
            root = checkout_root(cwd)
            if root is not None:
                checkouts.enter(root, worker_id, worker["mode"])
                before = checkout_snapshot(root, ignore=[run_dir])
        state.update_worker(
            worker_id,
            {
                "status": "running",
                "startedAt": outcome["startedAt"],
                "cwd": str(cwd),
                "worktree": outcome["worktree"],
                "costCapUsd": cost_cap,
            },
        )
        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            stdin_mode = subprocess.PIPE if stdin_prompt else subprocess.DEVNULL
            process = start_process(args, cwd, stdin_mode, stdout_file, stderr_file, worker_environment())
            registry.add(process)
            if stdin_prompt and process.stdin is not None:
                feed_stdin(process.stdin, worker["task"].encode("utf-8"))
            exit_code, ended = watch_process(
                process, worker_id, timeout, worker["idleTimeoutSeconds"], (stdout_path, stderr_path), state
            )
            registry.remove(process)
        overlapped = checkouts.leave(root, worker_id) if root is not None else {}
        status, result_text, values, error = classify_result(
            worker["provider"], output_format, stdout_path, result_path, exit_code, ended is not None
        )
        if ended == "stalled":
            error = f"worker printed nothing for {worker['idleTimeoutSeconds']}s"
        metrics = extract_metrics(values)
        details = extract_details(values)
        handoff = parse_handoff(result_text)
        kind, reset_hint = classify_failure(status, error, stderr_path, result_text, ended == "stalled")
        diff_path, diff_error = (
            capture_diff(cwd, worker_dir, worker["isolate"]) if worker["mode"] == "write" else (None, None)
        )
        touched = dirty_before = violation = None
        writer_nearby = any(mode == "write" for mode in overlapped.values())
        if before is not None and root is not None and not writer_nearby:
            after = checkout_snapshot(root, ignore=[run_dir])
            if after is not None:
                touched = changed_paths(before, after)[:MAX_LISTED_PATHS]
                if worker["mode"] == "read-only":
                    violation = bool(touched)
                else:
                    dirty_before = sorted(before)[:MAX_LISTED_PATHS]
        tracker.finish(worker_id, metrics)
        return settle(
            status=status,
            exitCode=exit_code,
            timedOut=ended is not None,
            resultPath=str(result_path),
            stdoutPath=str(stdout_path),
            stderrPath=str(stderr_path),
            diffPath=str(diff_path) if diff_path else None,
            diffError=diff_error,
            sessionId=extract_session(values),
            metrics=metrics,
            error=error,
            failureKind=kind,
            resetHint=reset_hint,
            readOnlyViolation=violation,
            touchedFiles=touched,
            dirtyBefore=dirty_before,
            sharedCheckoutWith=sorted(overlapped),
            **handoff,
            **details,
        )
    except Exception as error:  # Every worker failure must settle the batch state.
        if process is not None:
            stop_process_tree(process)
            registry.remove(process)
        if root is not None:
            checkouts.leave(root, worker_id)
        tracker.finish(worker_id, metrics)
        message = str(error)
        return settle(
            status="failed",
            error=message,
            failureKind="not_installed" if message.startswith("executable not found") else "error",
            stdoutPath=str(stdout_path),
            stderrPath=str(stderr_path),
        )


def validate_orchestration_limits(raw: Any, label: str) -> Dict[str, Any]:
    limits = validate_budget(raw, label)
    extra = set(limits) - set(ORCHESTRATION_BUDGET_FIELDS)
    if extra:
        raise PlanError(
            f"{label} only takes {', '.join(ORCHESTRATION_BUDGET_FIELDS)}, not {', '.join(sorted(extra))}"
        )
    return limits


def load_orchestration_budget(folder: Path) -> Dict[str, Any]:
    path = folder / ORCHESTRATION_BUDGET_FILE
    if not path.is_file():
        return {}
    raw = read_json(path)
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise PlanError(f"{path} must be an object with version 1")
    return validate_orchestration_limits(raw.get("limits"), f"{path.name} limits")


def orchestration_usage(folder: Path, exclude: Optional[Path] = None) -> Dict[str, Any]:
    calls, runs = 0, 0
    cost: Optional[float] = None
    tokens: Optional[int] = None
    if not folder.is_dir():
        return {"runs": 0, "calls": 0, "reportedCostUsd": None, "reportedTokens": None}
    for child in sorted(folder.iterdir()):
        if exclude is not None and child.resolve() == exclude.resolve():
            continue
        state = read_optional_json(child / "state.json")
        if not isinstance(state, dict):
            continue
        runs += 1
        usage = state.get("budgetUsage") if isinstance(state.get("budgetUsage"), dict) else {}
        calls += int(number(usage.get("calls")) or 0)
        spent = number(usage.get("reportedCostUsd"))
        if spent is not None:
            cost = (cost or 0.0) + spent
        reported = number(usage.get("reportedTokens"))
        if reported is not None:
            tokens = (tokens or 0) + int(reported)
    return {
        "runs": runs,
        "calls": calls,
        "reportedCostUsd": round(cost, 6) if cost is not None else None,
        "reportedTokens": tokens,
    }


def budget_payload(folder: Path, updates: Dict[str, Any], clear: bool) -> Dict[str, Any]:
    folder = folder.expanduser().resolve()
    path = folder / ORCHESTRATION_BUDGET_FILE
    if clear:
        if path.exists():
            path.unlink()
        limits: Dict[str, Any] = {}
    else:
        limits = load_orchestration_budget(folder)
        if updates:
            limits = validate_orchestration_limits({**limits, **updates}, "budget")
            folder.mkdir(parents=True, exist_ok=True)
            atomic_write_json(path, {"version": 1, "limits": limits, "updatedAt": now_iso()})
    used = orchestration_usage(folder)
    remaining: Dict[str, Any] = {}
    if "maxCalls" in limits:
        remaining["calls"] = max(0, limits["maxCalls"] - used["calls"])
    if "maxReportedCostUsd" in limits:
        remaining["reportedCostUsd"] = round(max(0.0, limits["maxReportedCostUsd"] - (used["reportedCostUsd"] or 0)), 6)
    if "maxReportedTokens" in limits:
        remaining["reportedTokens"] = max(0, limits["maxReportedTokens"] - (used["reportedTokens"] or 0))
    return {
        "path": str(path),
        "limits": limits,
        "used": used,
        "remaining": remaining,
        "note": "Reported cost covers only CLIs that report it; token and call limits cover the rest.",
    }


def mark_payload(run_dir: Path, worker_id: str, mark: str, why: Optional[str]) -> Dict[str, Any]:
    run_dir = run_dir.expanduser().resolve()
    state = read_json(run_dir / "state.json")
    if not isinstance(state, dict) or worker_id not in state.get("workers", {}):
        raise PlanError(f"{run_dir} has no worker {worker_id}")
    entry = {
        "worker": worker_id,
        "mark": mark,
        "why": optional_note(why, "mark why", NOTE_LIMITS["workerWhy"]),
        "markedAt": now_iso(),
    }
    atomic_write_json(run_dir / "workers" / worker_id / "mark.json", entry)
    return entry


def task_text(worker: Dict[str, Any]) -> str:
    return worker["task"].split("\n\nRuntime contract:", 1)[0]


def dirty_checkout(cwd: str) -> bool:
    try:
        return bool(run_git(Path(cwd), ["status", "--porcelain"], timeout=60).strip())
    except PlanError:
        return False


def plan_warnings(plan: Dict[str, Any]) -> List[str]:
    workers = plan["workers"]
    warnings: List[str] = []
    blind = []
    for worker in workers:
        label = Path(worker["command"]).stem if worker["provider"] == "custom" else worker["provider"]
        if worker["provider"] not in COST_REPORTING_PROVIDERS and label not in blind:
            blind.append(label)
    if "maxReportedCostUsd" in plan["budget"] and blind:
        warnings.append(
            f"maxReportedCostUsd only sees cost that Claude reports; {listed(blind)} "
            f"{'report' if len(blind) > 1 else 'reports'} none, so cap {'them' if len(blind) > 1 else 'it'} "
            "with maxReportedTokens or maxCalls"
        )
    writers = [worker for worker in workers if worker["mode"] == "write"]
    small = [worker for worker in writers if len(task_text(worker).split()) <= 50]
    if len(writers) >= 2 and len(small) == len(writers):
        warnings.append(
            f"{len(writers)} writers with short briefs: each worker first loads its own CLI context, "
            "so these may cost less done directly or as one worker"
        )
    for worker in workers:
        name = worker["id"]
        if worker["provider"] != "custom" and not (worker["model"] or worker["effort"]):
            warnings.append(f"{name} runs on {worker['provider']}'s default model; pin a tier, model or effort")
        if worker["provider"] == "kimi" and worker["mode"] == "read-only":
            warnings.append(
                f"{name}: Kimi runs prompts with every permission, so read-only rests on the worker contract; "
                "the runner checks the checkout afterwards"
            )
        if worker["provider"] == "kimi" and worker["mode"] == "write" and not worker["isolate"]:
            warnings.append(f"{name}: Kimi writes without asking; give it isolate: true")
        if (
            worker["provider"] in ("codex", "claude")
            and not worker["mcp"]
            and re.search(r"\bmcp\b", task_text(worker), re.IGNORECASE)
        ):
            warnings.append(f"{name} mentions MCP, but workers start without MCP servers; set mcp: true if it needs one")
        if worker["mode"] == "write" and not worker["isolate"] and dirty_checkout(worker["cwd"]):
            warnings.append(
                f"{name} writes in a checkout with uncommitted changes, so its diff will include them; "
                "use isolate: true or commit first"
            )
    return warnings


def default_run_dir() -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return Path(tempfile.gettempdir()) / f"alethe-orchestrate-{stamp}-{suffix}"


def run_batch(
    plan_path: Path,
    requested_run_dir: Optional[Path],
    policy_path: Path,
    strategy_override: Optional[str],
) -> int:
    if os.environ.get(WORKER_ENV_FLAG):
        raise PlanError("this process is an orchestration worker, and workers cannot start orchestrations")
    plan = validate_plan(
        read_json(plan_path), plan_path.resolve(), load_policy(policy_path), strategy_override
    )
    run_dir = (requested_run_dir or default_run_dir()).expanduser().resolve()
    if run_dir.exists() and any(run_dir.iterdir()):
        raise PlanError(f"run directory is not empty: {run_dir}")
    outer = None
    if requested_run_dir is not None:
        limits = load_orchestration_budget(run_dir.parent)
        if limits:
            used = orchestration_usage(run_dir.parent, exclude=run_dir)
            refusal = orchestration_refusal(limits, used)
            if refusal:
                raise PlanError(f"{refusal}; raise it with budget {run_dir.parent}")
            outer = {
                "path": str(run_dir.parent / ORCHESTRATION_BUDGET_FILE),
                "limits": limits,
                "used": used,
            }
    run_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        run_dir / "plan.json", plan_payload(plan, plan_path.resolve(), policy_path, dry_run=False)
    )
    suffix = run_dir.name[-8:]
    run_id = suffix if re.fullmatch(r"[0-9a-f]{8}", suffix) else uuid.uuid4().hex[:8]
    initial_workers = {
        worker["id"]: {
            "id": worker["id"],
            "provider": worker["provider"],
            "status": "queued",
            "cwd": worker["cwd"],
            "worktree": None,
        }
        for worker in plan["workers"]
    }
    state = BatchState(
        run_dir / "state.json",
        {
            "version": STATE_VERSION,
            "runId": run_id,
            "status": "running",
            "strategy": plan["strategy"],
            "requestedStrategy": plan["requestedStrategy"],
            "maxConcurrent": plan["maxConcurrent"],
            "policyPath": str(policy_path),
            "planPath": str(plan_path.resolve()),
            "runDir": str(run_dir),
            "startedAt": now_iso(),
            "finishedAt": None,
            "budget": plan["budget"],
            "orchestrationBudget": outer,
            "workers": initial_workers,
        },
    )
    help_cache: Dict[str, str] = {}
    help_lock = threading.Lock()
    registry = ProcessRegistry()
    checkouts = CheckoutRegistry()
    tracker = BudgetTracker(plan["budget"], outer, plan["maxConcurrent"], len(plan["workers"]))
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=plan["maxConcurrent"])
    futures: List[concurrent.futures.Future] = []
    try:
        futures = [
            executor.submit(
                run_worker,
                worker,
                run_id,
                run_dir,
                state,
                help_cache,
                help_lock,
                registry,
                tracker,
                checkouts,
            )
            for worker in plan["workers"]
        ]
        outcomes = [future.result() for future in concurrent.futures.as_completed(futures)]
    except KeyboardInterrupt:
        registry.stop_all()
        for future in futures:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
        state.finish("cancelled", {"budgetUsage": tracker.usage()})
        print(json.dumps({"status": "cancelled", "runDir": str(run_dir)}))
        return 130
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    succeeded = sum(outcome["status"] == "succeeded" for outcome in outcomes)
    status = "done" if succeeded == len(outcomes) else "partial" if succeeded else "failed"
    budget_usage = tracker.usage()
    state.finish(status, {"budgetUsage": budget_usage})
    print(
        json.dumps(
            {
                "status": status,
                "runDir": str(run_dir),
                "budget": plan["budget"],
                "budgetUsage": budget_usage,
                "workers": outcomes,
            },
            ensure_ascii=False,
        )
    )
    return 0 if status == "done" else 1


def flag_value(args: Sequence[str], flag: str) -> Optional[str]:
    for index, arg in enumerate(args):
        if arg == flag and index + 1 < len(args):
            return args[index + 1]
        if arg.startswith(flag + "="):
            return arg[len(flag) + 1 :]
    return None


def plan_payload(
    plan: Dict[str, Any], plan_path: Path, policy_path: Path, dry_run: bool = True
) -> Dict[str, Any]:
    if plan["requestedStrategy"] == "auto":
        strategy_reason = f"auto inferred: {infer_strategy(plan['workers'])[1]}"
    else:
        strategy_reason = "requested explicitly"
    wall_limit = plan["budget"].get("maxWallSeconds")
    workers = []
    for worker in plan["workers"]:
        effective_timeout = worker["timeoutSeconds"]
        if wall_limit is not None:
            effective_timeout = min(effective_timeout, wall_limit)
        custom_args = worker.get("args", []) if worker["provider"] == "custom" else []
        workers.append(
            {
                "id": worker["id"],
                "why": worker["why"],
                "requestedProvider": worker["requestedProvider"],
                "provider": worker["provider"],
                "command": Path(worker["command"]).stem if worker["provider"] == "custom" else None,
                "switched": worker["provider"] != worker["requestedProvider"],
                "routingNote": worker["routingNote"],
                "tier": worker["tier"],
                "model": worker["model"] or flag_value(custom_args, "--model"),
                "effort": worker["effort"] or flag_value(custom_args, "--effort"),
                "modelNote": worker["modelNote"],
                "mode": worker["mode"],
                "isolate": worker["isolate"],
                "seedPaths": worker["seedPaths"],
                "timeoutSeconds": worker["timeoutSeconds"],
                "effectiveTimeoutSeconds": effective_timeout,
                "promptChars": len(worker["task"]),
                "estimatedPromptTokens": worker["estimatedPromptTokens"],
                "subagents": "blocked by the CLI"
                if worker["provider"] in ("codex", "claude")
                else "refused by the worker contract",
                "mcp": worker["mcp"] if worker["provider"] in ("codex", "claude") else None,
                "idleTimeoutSeconds": worker["idleTimeoutSeconds"],
                "telemetry": {
                    "tokenUsage": PROVIDER_CAPABILITIES.get(worker["provider"], {}).get(
                        "tokenUsage", False
                    )
                },
            }
        )
    return {
        "dryRun": dry_run,
        "skillVersion": skill_version(),
        "planPath": str(plan_path),
        "policyPath": str(policy_path),
        "title": plan["title"],
        "why": plan["why"],
        "playbook": plan["playbook"],
        "phase": plan["phase"],
        "strategy": plan["strategy"],
        "requestedStrategy": plan["requestedStrategy"],
        "strategyReason": strategy_reason,
        "maxConcurrent": plan["maxConcurrent"],
        "budget": plan["budget"],
        "workers": workers,
        "totals": {
            "workers": len(workers),
            "estimatedPromptTokens": sum(worker["estimatedPromptTokens"] for worker in workers),
        },
        "estimates": (
            "prompt-only chars/4 heuristic; provider-side context such as repository reads "
            "and tool calls is additional and cannot be estimated"
        ),
        "warnings": plan_warnings(plan),
    }


def find_run_dirs(paths: Sequence[Path]) -> List[Path]:
    if not paths:
        runs = [
            candidate
            for candidate in Path(tempfile.gettempdir()).glob("alethe-orchestrate-*")
            if (candidate / "state.json").is_file()
        ]
        if not runs:
            raise PlanError("no runs found; pass the run directory that run printed")
        return [max(runs, key=lambda candidate: (candidate / "state.json").stat().st_mtime)]
    found: List[Path] = []
    for raw in paths:
        path = raw.expanduser().resolve()
        if (path / "state.json").is_file():
            candidates = [path]
        elif path.is_dir():
            candidates = sorted(child for child in path.iterdir() if (child / "state.json").is_file())
        else:
            raise PlanError(f"not a run directory: {path}")
        if not candidates:
            raise PlanError(f"no runs found in {path}")
        for candidate in candidates:
            if candidate not in found:
                found.append(candidate)
    return found


def number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return None


def cached_tokens(usage: Any) -> Optional[int]:
    if not isinstance(usage, dict):
        return None
    for key in ("cache_read_input_tokens", "cached_input_tokens"):
        value = number(usage.get(key))
        if value is not None:
            return int(value)
    return None


def file_bytes(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def diff_stats(path: Path) -> Optional[Dict[str, int]]:
    if not path.is_file():
        return None
    files = insertions = deletions = 0
    in_hunk = False
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("diff --git "):
                files += 1
                in_hunk = False
            elif line.startswith("@@"):
                in_hunk = True
            elif in_hunk and line.startswith("+"):
                insertions += 1
            elif in_hunk and line.startswith("-"):
                deletions += 1
    return {"files": files, "insertions": insertions, "deletions": deletions}


def result_summary(path: Path, limit: int = 200) -> Optional[str]:
    if not path.is_file():
        return None
    first = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = re.sub(r"^(?:[-*+>]|\d+[.)])\s+", "", raw.strip()).replace("**", "").strip()
        if not line or line.startswith(("#", "|", "```")) or set(line) <= set("-*_=| ") or HANDOFF_LINE.match(line):
            continue
        first = first or line
        if len(line.split()) >= 3 or re.search(r"[.!?]$", line):
            first = line
            break
    if first is None:
        return None
    return first if len(first) <= limit else first[: limit - 3].rstrip() + "..."


def last_line(path: Path, limit: int = 200) -> Optional[str]:
    size = file_bytes(path)
    if not size:
        return None
    with path.open("rb") as handle:
        handle.seek(max(0, size - 4096))
        tail = handle.read().decode("utf-8", errors="replace")
    lines = [line.strip() for line in tail.splitlines() if line.strip()]
    if not lines:
        return None
    errors = [line for line in lines[-20:] if ERROR_LINE.search(line)]
    line = errors[-1] if errors else lines[-1]
    return line if len(line) <= limit else line[: limit - 3].rstrip() + "..."


def seconds_between(started: Any, finished: Any) -> Optional[float]:
    try:
        return (dt.datetime.fromisoformat(finished) - dt.datetime.fromisoformat(started)).total_seconds()
    except (TypeError, ValueError):
        return None


def collect_run(run_dir: Path) -> Dict[str, Any]:
    state = read_json(run_dir / "state.json")
    if not isinstance(state, dict) or not isinstance(state.get("workers"), dict):
        raise PlanError(f"{run_dir} has no valid state.json")
    plan = read_optional_json(run_dir / "plan.json")
    plan = plan if isinstance(plan, dict) else {}
    planned = {
        entry["id"]: entry
        for entry in plan.get("workers", [])
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }
    workers = []
    for worker_id, entry in state["workers"].items():
        worker_dir = run_dir / "workers" / worker_id
        outcome = read_optional_json(worker_dir / "outcome.json")
        outcome = outcome if isinstance(outcome, dict) else entry
        intent = planned.get(worker_id, {})
        metrics = outcome.get("metrics") if isinstance(outcome.get("metrics"), dict) else {}
        result_path = worker_dir / "result.md"
        stderr_path = worker_dir / "stderr.log"
        diff_path = worker_dir / "diff.patch"
        provider = outcome.get("provider") or entry.get("provider")
        status = outcome.get("status", "unknown")
        handoff = {key: outcome.get(key) for key in ("workerStatus", "workerSummary", "verdict")}
        if not any(handoff.values()) and result_path.is_file():
            handoff = parse_handoff(result_path.read_text(encoding="utf-8", errors="replace"))
        mark = read_optional_json(worker_dir / "mark.json")
        mark = mark if isinstance(mark, dict) and mark.get("mark") in MARKS else {}
        workers.append(
            {
                "id": worker_id,
                "why": intent.get("why"),
                "provider": provider,
                "label": intent.get("command") or provider,
                "requestedProvider": intent.get("requestedProvider"),
                "routingNote": intent.get("routingNote"),
                "tier": intent.get("tier"),
                "model": intent.get("model"),
                "effort": intent.get("effort"),
                "modelNote": intent.get("modelNote"),
                "mode": intent.get("mode"),
                "isolate": intent.get("isolate"),
                "status": status,
                "error": outcome.get("error"),
                "stderrTail": last_line(stderr_path) if status != "succeeded" else None,
                "durationSeconds": number(outcome.get("durationSeconds")),
                "tokens": reported_total_tokens(metrics.get("usage")),
                "cachedTokens": cached_tokens(metrics.get("usage")),
                "costUsd": number(metrics.get("totalCostUsd")),
                "sessionId": outcome.get("sessionId"),
                "worktree": outcome.get("worktree"),
                "summary": handoff["workerSummary"] or result_summary(result_path),
                "workerStatus": handoff["workerStatus"],
                "verdict": handoff["verdict"],
                "failureKind": outcome.get("failureKind"),
                "resetHint": outcome.get("resetHint"),
                "permissionDenials": list(outcome.get("permissionDenials") or []),
                "billedModels": list(outcome.get("billedModels") or []),
                "readOnlyViolation": outcome.get("readOnlyViolation"),
                "touchedFiles": outcome.get("touchedFiles"),
                "dirtyBefore": outcome.get("dirtyBefore"),
                "costCapUsd": number(outcome.get("costCapUsd")),
                "diffError": outcome.get("diffError"),
                "mark": mark.get("mark"),
                "markWhy": mark.get("why"),
                "resultPath": str(result_path) if result_path.is_file() else None,
                "resultBytes": file_bytes(result_path),
                "transcriptBytes": file_bytes(worker_dir / "stdout.log") + file_bytes(stderr_path),
                "stderrPath": str(stderr_path) if file_bytes(stderr_path) else None,
                "diff": diff_stats(diff_path),
                "diffPath": str(diff_path) if diff_path.is_file() else None,
            }
        )
    usage = state.get("budgetUsage") if isinstance(state.get("budgetUsage"), dict) else {}
    wall = number(usage.get("wallSeconds"))
    if wall is None:
        wall = seconds_between(state.get("startedAt"), state.get("finishedAt"))
    return {
        "runDir": str(run_dir),
        "runId": state.get("runId"),
        "status": state.get("status"),
        "title": plan.get("title"),
        "why": plan.get("why"),
        "playbook": plan.get("playbook"),
        "phase": plan.get("phase"),
        "strategy": state.get("strategy"),
        "requestedStrategy": state.get("requestedStrategy"),
        "strategyReason": plan.get("strategyReason"),
        "maxConcurrent": state.get("maxConcurrent"),
        "startedAt": state.get("startedAt"),
        "finishedAt": state.get("finishedAt"),
        "wallSeconds": wall,
        "budget": state.get("budget") if isinstance(state.get("budget"), dict) else {},
        "budgetUsage": usage,
        "workers": workers,
    }


def concerns(worker: Dict[str, Any]) -> List[str]:
    reasons = []
    said = worker["workerStatus"]
    if said in ("BLOCKED", "NEEDS_CONTEXT"):
        reasons.append(
            f"it said {said.replace('_', ' ').lower()}; change its context, tier or scope before sending it again"
        )
    elif said == "DONE_WITH_CONCERNS":
        reasons.append("it finished with concerns to review")
    if worker["verdict"] in ("FAIL", "NOT_PROVEN"):
        reasons.append(f"its verdict is {worker['verdict'].replace('_', ' ').lower()}")
    if worker["readOnlyViolation"]:
        touched = list(worker["touchedFiles"] or [])[:5]
        reasons.append(f"it changed the checkout while read-only ({listed(touched)})")
    denials = worker["permissionDenials"]
    if denials:
        reasons.append(
            f"{counted(len(denials), 'tool call')} denied ({listed(sorted(set(denials)))}), so its checks may not have run"
        )
    return reasons


def value_totals(workers: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not any(worker["mark"] for worker in workers):
        return None
    groups: Dict[str, Any] = {}
    for key in (*MARKS, "unmarked"):
        members = [
            worker
            for worker in workers
            if (worker["mark"] or "unmarked") == key and (key != "unmarked" or worker["status"] in RAN_STATUSES)
        ]
        groups[key] = {
            "workers": [worker["id"] for worker in members],
            "tokens": summed([worker["tokens"] for worker in members]),
            "costUsd": summed([worker["costUsd"] for worker in members]),
        }
    return groups


def report_budget(runs: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    folders = {Path(run["runDir"]).parent for run in runs}
    if len(folders) != 1:
        return None
    folder = folders.pop()
    try:
        limits = load_orchestration_budget(folder)
    except PlanError:
        return None
    if not limits:
        return None
    return {"path": str(folder / ORCHESTRATION_BUDGET_FILE), "limits": limits, "used": orchestration_usage(folder)}


def summed(values: Sequence[Any]) -> Optional[float]:
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def build_report(run_dirs: Sequence[Path]) -> Dict[str, Any]:
    runs = sorted((collect_run(path) for path in run_dirs), key=lambda run: run["startedAt"] or "")
    workers = [worker for run in runs for worker in run["workers"]]
    ran = [
        worker
        for worker in workers
        if worker["status"] == "succeeded"
        or (worker["status"] in RAN_STATUSES and worker["transcriptBytes"])
    ]
    labels: List[str] = []
    for worker in workers:
        if worker["label"] and worker["label"] not in labels:
            labels.append(worker["label"])
    statuses: Dict[str, int] = {}
    for worker in workers:
        statuses[worker["status"]] = statuses.get(worker["status"], 0) + 1
    by_provider = {
        label: {
            "workers": sum(worker["label"] == label for worker in workers),
            "seconds": summed([w["durationSeconds"] for w in workers if w["label"] == label]),
            "tokens": summed([w["tokens"] for w in workers if w["label"] == label]),
            "costUsd": summed([w["costUsd"] for w in workers if w["label"] == label]),
        }
        for label in labels
    }

    def silent(key: str) -> List[str]:
        reporting = {w["label"] for w in workers if w[key] is not None}
        return sorted({w["label"] for w in ran if w["label"] not in reporting})

    changed = [worker for worker in workers if worker["diff"]]
    attention = [worker for worker in workers if worker["status"] != "succeeded" or concerns(worker)]
    said: Dict[str, int] = {}
    for worker in workers:
        if worker["status"] in RAN_STATUSES:
            key = worker["workerStatus"] or "unreported"
            said[key] = said.get(key, 0) + 1
    titles = [run["title"] for run in runs if run["title"]]
    playbooks: List[str] = []
    for run in runs:
        if run["playbook"] and run["playbook"] not in playbooks:
            playbooks.append(run["playbook"])
    return {
        "version": 1,
        "generatedAt": now_iso(),
        "skillVersion": skill_version(),
        "title": titles[0] if titles else None,
        "playbooks": playbooks,
        "startedAt": runs[0]["startedAt"] if runs else None,
        "finishedAt": max((run["finishedAt"] or "" for run in runs), default="") or None,
        "totals": {
            "runs": len(runs),
            "workers": len(workers),
            "statuses": statuses,
            "wallSeconds": summed([run["wallSeconds"] for run in runs]),
            "workerSeconds": summed([worker["durationSeconds"] for worker in workers]),
            "calls": int(sum(number(run["budgetUsage"].get("calls")) or 0 for run in runs)),
            "workerStatuses": said,
            "tokens": summed([worker["tokens"] for worker in workers]),
            "cachedTokens": summed([worker["cachedTokens"] for worker in workers]),
            "tokensNotReportedBy": silent("tokens"),
            "costUsd": summed([worker["costUsd"] for worker in workers]),
            "costReportedBy": sorted({w["label"] for w in workers if w["costUsd"] is not None}),
            "costNotReportedBy": silent("costUsd"),
            "transcriptBytes": sum(worker["transcriptBytes"] for worker in workers),
            "resultBytes": sum(worker["resultBytes"] for worker in workers),
            "changes": {
                "writers": len(changed),
                "files": sum(worker["diff"]["files"] for worker in changed),
                "insertions": sum(worker["diff"]["insertions"] for worker in changed),
                "deletions": sum(worker["diff"]["deletions"] for worker in changed),
            },
            "budgetStops": [
                worker["error"]
                for worker in workers
                if worker["status"] == "skipped"
                and str(worker["error"] or "").startswith(("budget", "orchestration budget"))
            ],
            "value": value_totals(workers),
        },
        "orchestrationBudget": report_budget(runs),
        "byProvider": by_provider,
        "runs": runs,
        "followUps": {
            "worktrees": [
                {"worker": w["id"], "path": w["worktree"], "diff": w["diff"]}
                for w in workers
                if w["worktree"]
            ],
            "mainCheckoutChanges": [
                {"worker": w["id"], "diffPath": w["diffPath"], "diff": w["diff"]}
                for w in changed
                if not w["worktree"]
            ],
            "attention": [
                {
                    "worker": w["id"],
                    "status": w["status"],
                    "error": w["error"],
                    "reasons": concerns(w),
                    "failureKind": w["failureKind"],
                    "hint": FAILURE_HINTS.get(w["failureKind"] or ""),
                    "resetHint": w["resetHint"],
                    "stderrTail": w["stderrTail"],
                    "stderrPath": w["stderrPath"],
                    "provider": w["provider"],
                    "resume": w["sessionId"]
                    if w["status"] in ("failed", "timed_out")
                    and PROVIDER_CAPABILITIES.get(w["provider"], {}).get("resume")
                    else None,
                }
                for w in attention
            ],
        },
    }


def human_seconds(seconds: Optional[float]) -> str:
    if seconds is None:
        return "-"
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def human_bytes(size: float) -> str:
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def human_cost(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"${value:.4f}" if 0 < value < 0.01 else f"${value:.2f}"


def human_count(value: Optional[float]) -> str:
    return "-" if value is None else f"{int(value):,}"


def local_time(stamp: Any) -> Optional[dt.datetime]:
    try:
        return dt.datetime.fromisoformat(stamp).astimezone()
    except (TypeError, ValueError):
        return None


def cell(value: Any) -> str:
    if value in (None, ""):
        return "-"
    return " ".join(str(value).split()).replace("|", "\\|")


def listed(names: Sequence[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def counted(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def change_text(diff: Dict[str, int]) -> str:
    return f"{counted(diff['files'], 'file')} (+{diff['insertions']} -{diff['deletions']})"


def ran_on(worker: Dict[str, Any]) -> str:
    provider = worker["provider"] or "?"
    requested = worker["requestedProvider"]
    head = worker["label"] or provider
    if requested and requested not in ("auto", provider):
        head = f"{requested} -> {head}"
    parts = [head]
    if worker["model"]:
        parts.append(worker["model"])
    elif worker["billedModels"]:
        parts.append(", ".join(worker["billedModels"]))
    elif provider != "custom":
        parts.append("default model")
    if worker["effort"]:
        parts.append(worker["effort"])
    return ", ".join(parts)


def status_text(worker: Dict[str, Any]) -> str:
    parts = [worker["status"].replace("_", " ")]
    if worker["workerStatus"] and worker["workerStatus"] != "DONE":
        parts.append(worker["workerStatus"].replace("_", " ").lower())
    if worker["verdict"]:
        parts.append(worker["verdict"].replace("_", " ").lower())
    if worker["readOnlyViolation"]:
        parts.append("wrote while read-only")
    return ", ".join(parts)


def spend_text(tokens: Optional[float], cost: Optional[float]) -> str:
    parts = [human_cost(cost) if cost is not None else "no cost reported"]
    parts.append(f"{human_count(tokens)} tokens" if tokens is not None else "no tokens reported")
    return ", ".join(parts)


def value_text(value: Dict[str, Any]) -> str:
    labels = {"used": "used", "partial": "partly used", "discarded": "discarded"}
    parts = []
    for key, label in labels.items():
        group = value[key]
        if group["workers"]:
            parts.append(f"{counted(len(group['workers']), 'result')} {label} ({spend_text(group['tokens'], group['costUsd'])})")
    text = "; ".join(parts) or "nothing marked yet"
    unmarked = value["unmarked"]["workers"]
    if unmarked:
        text += f"; {counted(len(unmarked), 'result')} not marked"
    return text


def limits_text(limits: Dict[str, Any], calls: Any, cost: Any, tokens: Any) -> str:
    parts = []
    if "maxCalls" in limits:
        parts.append(f"{int(number(calls) or 0)} of {limits['maxCalls']} calls")
    if "maxReportedCostUsd" in limits:
        spent = number(cost)
        limit = human_cost(limits["maxReportedCostUsd"])
        parts.append(f"{human_cost(spent)} of {limit}" if spent is not None else f"no cost reported against {limit}")
    if "maxReportedTokens" in limits:
        counted_tokens = number(tokens)
        limit = human_count(limits["maxReportedTokens"])
        parts.append(
            f"{human_count(counted_tokens)} of {limit} reported tokens"
            if counted_tokens is not None
            else f"no tokens reported against {limit}"
        )
    return ", ".join(parts)


def verb_for(names: Sequence[str], singular: str, plural: str) -> str:
    return f"{listed(names)} {singular if len(names) == 1 else plural}"


def mode_text(worker: Dict[str, Any]) -> str:
    if worker["mode"] == "write":
        return "write, worktree" if worker["isolate"] else "write"
    return "read" if worker["mode"] == "read-only" else "-"


def budget_text(run: Dict[str, Any]) -> Optional[str]:
    budget, usage = run["budget"], run["budgetUsage"]
    parts = []
    text = limits_text(budget, usage.get("calls"), usage.get("reportedCostUsd"), usage.get("reportedTokens"))
    if text:
        parts.append(text)
    if "maxWallSeconds" in budget:
        parts.append(f"{human_seconds(run['wallSeconds'])} of {human_seconds(budget['maxWallSeconds'])}")
    if "maxEstimatedPromptTokens" in budget:
        parts.append(f"prompts within {human_count(budget['maxEstimatedPromptTokens'])} estimated tokens")
    return ", ".join(parts) or None


def render_markdown(report: Dict[str, Any]) -> str:
    totals = report["totals"]
    runs = report["runs"]
    lines = ["# Orchestration report", ""]
    heading = []
    if report["title"]:
        heading.append(f"**{cell(report['title'])}**")
    if report["playbooks"]:
        heading.append("playbook " + ", ".join(f"`{name}`" for name in report["playbooks"]))
    heading.append(counted(totals["runs"], "wave"))
    started, finished = local_time(report["startedAt"]), local_time(report["finishedAt"])
    if started:
        span = started.strftime("%Y-%m-%d %H:%M")
        if finished:
            span += finished.strftime(" to %H:%M" if finished.date() == started.date() else " to %Y-%m-%d %H:%M")
        heading.append(span)
    lines += [", ".join(heading), ""]
    if len(runs) == 1 and runs[0]["why"]:
        lines += [f"Why: {cell(runs[0]['why'])}", ""]

    statuses = totals["statuses"]
    others = [
        f"{count} {status.replace('_', ' ')}"
        for status, count in sorted(statuses.items())
        if status != "succeeded"
    ]
    result = f"{statuses.get('succeeded', 0)} of {counted(totals['workers'], 'worker')} succeeded"
    lines.append(f"- **Result:** {result}" + (f", {', '.join(others)}" if others else ""))
    lines.append(
        f"- **Time:** {human_seconds(totals['wallSeconds'])} running, "
        f"{human_seconds(totals['workerSeconds'])} of worker time"
    )
    if totals["tokens"] is not None:
        tokens = f"{human_count(totals['tokens'])} reported"
        if totals["cachedTokens"]:
            tokens += f", {human_count(totals['cachedTokens'])} of them from cache"
    else:
        tokens = "none reported"
    if totals["tokensNotReportedBy"]:
        tokens += f"; {verb_for(totals['tokensNotReportedBy'], 'reports', 'report')} no tokens"
    lines.append(f"- **Tokens:** {tokens}")
    if totals["costUsd"] is not None:
        cost = f"{human_cost(totals['costUsd'])} reported by {listed(totals['costReportedBy'])}"
    else:
        cost = "none reported"
    if totals["costNotReportedBy"]:
        cost += f"; {verb_for(totals['costNotReportedBy'], 'reports', 'report')} no cost"
    lines.append(f"- **Cost:** {cost}")
    lines.append(
        f"- **Lead context:** {human_bytes(totals['transcriptBytes'])} of worker transcripts stayed on disk, "
        f"{human_bytes(totals['resultBytes'])} of results to read"
    )
    changes = totals["changes"]
    if changes["writers"]:
        lines.append(
            f"- **Changes:** {change_text(changes)} from {counted(changes['writers'], 'writer')}"
        )
    if totals["budgetStops"]:
        stops = sorted(set(totals["budgetStops"]))
        lines.append(f"- **Budget:** stopped {counted(len(totals['budgetStops']), 'worker')} ({'; '.join(stops)})")
    outer = report["orchestrationBudget"]
    if outer:
        used = outer["used"]
        spent = limits_text(outer["limits"], used["calls"], used["reportedCostUsd"], used["reportedTokens"])
        lines.append(f"- **Orchestration budget:** {spent}")
    if totals["value"]:
        lines.append(f"- **Value:** {value_text(totals['value'])}")

    for index, run in enumerate(runs, 1):
        name = run["phase"] or f"Wave {index}"
        lines += ["", f"## {index}. {name}" if len(runs) > 1 else f"## {name}", ""]
        if len(runs) > 1 and run["why"]:
            lines += [f"Why: {cell(run['why'])}", ""]
        strategy = str(run["strategy"] or "?")
        reason = run["strategyReason"] or ""
        if reason.startswith("auto inferred: "):
            strategy += f" (auto: {reason[len('auto inferred: '):]})"
        elif run["requestedStrategy"] and run["requestedStrategy"] == run["strategy"]:
            strategy += " (requested)"
        meta = [
            f"Strategy {strategy}",
            f"up to {run['maxConcurrent']} at a time",
            f"{run['status']} in {human_seconds(run['wallSeconds'])}",
        ]
        started = local_time(run["startedAt"])
        if started:
            meta.append(f"started {started.strftime('%H:%M')}")
        lines.append(", ".join(meta) + ".")
        budget = budget_text(run)
        if budget:
            lines.append(f"Budget: {budget}.")
        lines.append("")
        with_role = any(worker["why"] for worker in run["workers"])
        header = ["Worker"] + (["Role"] if with_role else []) + ["Ran on", "Mode", "Status", "Time", "Tokens", "Cost"]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "|".join(" --- " for _ in header) + "|")
        for worker in run["workers"]:
            row = [f"`{worker['id']}`"] + ([cell(worker["why"])] if with_role else [])
            row += [
                cell(ran_on(worker)),
                mode_text(worker),
                status_text(worker),
                human_seconds(worker["durationSeconds"]),
                human_count(worker["tokens"]),
                human_cost(worker["costUsd"]),
            ]
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")
        for worker in run["workers"]:
            detail = []
            if worker["summary"]:
                detail.append(cell(worker["summary"]))
            if worker["error"]:
                reason = cell(worker["error"])
                if worker["stderrTail"]:
                    reason += f" ({cell(worker['stderrTail'])})"
                detail.append(f"{worker['status'].replace('_', ' ').capitalize()}: {reason}.")
            if worker["diff"]:
                detail.append(f"Changed {change_text(worker['diff'])}.")
            if worker["dirtyBefore"]:
                detail.append(
                    f"{counted(len(worker['dirtyBefore']), 'file')} in its diff already had uncommitted changes."
                )
            if worker["diffError"]:
                detail.append(f"No diff: {cell(worker['diffError'])}.")
            if worker["readOnlyViolation"]:
                detail.append(f"Changed while read-only: {cell(listed(list(worker['touchedFiles'] or [])[:5]))}.")
            if worker["permissionDenials"]:
                denied = listed(sorted(set(worker["permissionDenials"])))
                detail.append(f"Denied {counted(len(worker['permissionDenials']), 'tool call')} ({cell(denied)}).")
            if worker["mark"]:
                marked = f"Marked {worker['mark']}"
                detail.append(marked + (f": {cell(worker['markWhy'])}." if worker["markWhy"] else "."))
            notes = [note for note in (worker["modelNote"], worker["routingNote"]) if note]
            text = " ".join(detail) or "No result."
            if notes:
                text += f" _({cell('; '.join(notes))})_"
            lines.append(f"- `{worker['id']}`: {text}")

    if len(report["byProvider"]) > 1:
        lines += ["", "## By provider", "", "| Provider | Workers | Time | Tokens | Cost |", "| --- | --- | --- | --- | --- |"]
        for provider, entry in report["byProvider"].items():
            lines.append(
                f"| {provider} | {entry['workers']} | {human_seconds(entry['seconds'])} | "
                f"{human_count(entry['tokens'])} | {human_cost(entry['costUsd'])} |"
            )

    follow = report["followUps"]
    todo = []
    for item in follow["attention"]:
        text = f"- `{item['worker']}` {item['status'].replace('_', ' ')}"
        if item["error"]:
            text += f": {cell(item['error'])}"
        if item["reasons"]:
            text += ("; " if item["error"] else ": ") + "; ".join(item["reasons"])
        if item["hint"]:
            text += f". {item['hint'][0].upper()}{item['hint'][1:]}"
        if item["resetHint"]:
            text += f" ({cell(item['resetHint'])})"
        if item["stderrPath"] and item["status"] != "succeeded":
            text += f". Logs: `{item['stderrPath']}`"
        if item["resume"]:
            text += f". Resume {item['provider']} session `{item['resume']}` with the rescue strategy"
        todo.append(text + ".")
    for item in follow["worktrees"]:
        changed = f": {change_text(item['diff'])}" if item["diff"] else ", no changes"
        todo.append(f"- Review worktree `{item['path']}` from `{item['worker']}`{changed}. Remove it once handled.")
    for item in follow["mainCheckoutChanges"]:
        todo.append(
            f"- `{item['worker']}` changed the main checkout: {change_text(item['diff'])}, see `{item['diffPath']}`."
        )
    value = totals["value"]
    if value and value["unmarked"]["workers"]:
        names = ", ".join(f"`{name}`" for name in value["unmarked"]["workers"])
        todo.append(f"- Mark {names} as used, partial or discarded.")
    if todo:
        lines += ["", "## Left to do", ""] + todo

    lines += ["", "---", ""]
    note = "Tokens and cost are only what each CLI reported; nothing is estimated."
    if "claude" in totals["costReportedBy"]:
        note += " Claude Code reports cost at API prices, so on a subscription that work used plan limits instead of money."
    lines.append(note)
    version = report["skillVersion"]
    lines.append(
        f"Generated by alethe-orchestrate{' v' + version if version else ''} from {counted(totals['runs'], 'run')}."
    )
    return "\n".join(lines) + "\n"


def render_status(report: Dict[str, Any]) -> str:
    totals = report["totals"]
    head = [report["title"] or "Orchestration"]
    if report["playbooks"]:
        head.append("playbook " + ", ".join(report["playbooks"]))
    head.append(counted(totals["runs"], "wave"))
    lines = [" | ".join(head)]
    waves = []
    for index, run in enumerate(report["runs"], 1):
        done = sum(worker["status"] == "succeeded" for worker in run["workers"])
        waves.append(f"{index}. {run['phase'] or 'wave'} {run['status']} ({done}/{len(run['workers'])})")
    lines.append("Waves: " + "; ".join(waves))
    lines.append(f"Spent: {counted(totals['calls'], 'worker call')}, {spend_text(totals['tokens'], totals['costUsd'])}")
    outer = report["orchestrationBudget"]
    if outer:
        used = outer["used"]
        lines.append("Budget: " + limits_text(outer["limits"], used["calls"], used["reportedCostUsd"], used["reportedTokens"]))
    follow = report["followUps"]
    if follow["attention"]:
        items = []
        for item in follow["attention"]:
            why = item["error"] or "; ".join(item["reasons"]) or item["status"]
            items.append(f"{item['worker']} ({why[:90]})")
        lines.append("Needs attention: " + "; ".join(items))
    if follow["worktrees"]:
        lines.append("Open worktrees: " + ", ".join(item["worker"] for item in follow["worktrees"]))
    value = totals["value"]
    if value and value["unmarked"]["workers"]:
        lines.append("Not marked: " + ", ".join(value["unmarked"]["workers"]))
    return "\n".join(lines) + "\n"


def probe_provider(provider: str) -> Dict[str, Any]:
    command = "agy" if provider == "agy" else provider
    executable = shutil.which(command)
    launch = launch_command(executable) if executable else None
    version = None
    if launch:
        try:
            result = subprocess.run(
                [*launch, "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=5,
                check=False,
            )
            version = result.stdout.strip().splitlines()[0] if result.stdout.strip() else None
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {
        "provider": provider,
        "installed": executable is not None,
        "executable": executable,
        "launch": launch,
        "version": version,
        "capabilities": PROVIDER_CAPABILITIES[provider],
    }


AUTH_COMMANDS = {"claude": ("auth", "status"), "codex": ("login", "status"), "kimi": ("provider", "list")}


def provider_logged_in(provider: str, launch: Optional[List[str]]) -> Optional[bool]:
    command = AUTH_COMMANDS.get(provider)
    if not launch or not command:
        return None
    try:
        result = subprocess.run(
            [*launch, *command],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = result.stdout or ""
    if provider == "claude":
        try:
            return bool(json.loads(output).get("loggedIn"))
        except (json.JSONDecodeError, AttributeError):
            return None
    if provider == "codex":
        if re.search(r"not logged in", output, re.IGNORECASE):
            return False
        return True if result.returncode == 0 and re.search(r"logged in", output, re.IGNORECASE) else None
    return bool(re.search(r"source=(oauth|api)", output))


def doctor_payload(policy_path: Path) -> Dict[str, Any]:
    python_ok = sys.version_info >= (3, 9)
    exists = policy_path.exists()
    policy: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    try:
        policy = load_policy(policy_path)
    except PlanError as plan_error:
        error = str(plan_error)
    providers = [probe_provider(provider) for provider in BUILTIN_PROVIDERS]
    for entry in providers:
        entry["loggedIn"] = provider_logged_in(entry["provider"], entry["launch"]) if entry["installed"] else None
    installed = [entry["provider"] for entry in providers if entry["installed"]]
    hints: List[str] = []
    for entry in providers:
        if entry["loggedIn"] is False:
            hints.append(f"{entry['provider']} is installed but not logged in")
    if not python_ok:
        hints.append("python 3.9 or newer is required")
    if not installed:
        hints.append("no built-in provider is installed; install one or use provider custom")
    if not policy or not policy["onboarded"]:
        hints.append("orchestration onboarding is incomplete; offer the setup choices")
    if error:
        hints.append(f"saved policy is invalid: {error}")
    elif policy and not policy["budget"]:
        hints.append("no default budget; policy set can add hard limits such as --max-calls")
    return {
        "skill": {"version": skill_version(), "path": str(Path(__file__).resolve().parent.parent)},
        "python": {"version": sys.version.split()[0], "ok": python_ok},
        "policyPath": str(policy_path),
        "policy": {
            "exists": exists,
            "valid": error is None,
            "error": error,
            "configured": exists and error is None and bool(policy and policy["onboarded"]),
            "budget": policy["budget"] if policy else None,
        },
        "providers": providers,
        "installedProviders": installed,
        "hints": hints,
    }


def scaffold_plan(strategy: str, workers: int, cwd: str, provider: str) -> Dict[str, Any]:
    strategy = normalized_strategy(strategy, "scaffold strategy")
    provider = normalized_provider(provider)
    if strategy == "auto":
        strategy = "economy"
        workers = 1
    rules = STRATEGIES[strategy]
    if not 1 <= workers <= rules["maxWorkers"]:
        raise PlanError(f"strategy {strategy} allows between 1 and {rules['maxWorkers']} workers")
    if strategy == "rescue" and provider == "auto":
        raise PlanError("a rescue scaffold needs --provider naming the session owner")
    write_mode = strategy in ("parallel", "quality")
    entries: List[Dict[str, Any]] = []
    for index in range(workers):
        entry: Dict[str, Any] = {
            "id": f"worker-{index + 1}",
            "provider": provider,
            "mode": "write" if write_mode else "read-only",
            "cwd": cwd,
            "task": "TODO: one bounded unit — goal, definition of done, owned paths, checks.",
        }
        if strategy == "parallel":
            entry["isolate"] = True
        if strategy == "rescue":
            entry["resume"] = "TODO-session-id"
        if provider == "custom":
            entry["command"] = "TODO-executable"
        entries.append(entry)
    return {"version": PLAN_VERSION, "strategy": strategy, "workers": entries}


def strategies_payload() -> List[Dict[str, Any]]:
    return [
        {
            "strategy": name,
            "maxWorkers": rules["maxWorkers"],
            "maxConcurrent": rules["maxConcurrent"],
            "description": rules["description"],
        }
        for name, rules in STRATEGIES.items()
    ]


def update_policy(args: argparse.Namespace, policy_path: Path) -> Dict[str, Any]:
    policy = load_policy(policy_path)
    if args.policy_action == "reset":
        policy = dict(DEFAULT_POLICY)
        save_policy(policy_path, policy)
        return policy
    if args.policy_action == "show":
        return policy
    if args.strategy:
        policy["defaultStrategy"] = normalized_strategy(args.strategy, "policy strategy")
    if args.backend:
        policy["backend"] = args.backend
    if args.provider_switch:
        policy["providerSwitch"] = args.provider_switch
    if args.provider_order:
        policy["providerOrder"] = validate_provider_list(
            args.provider_order, "provider order", allow_empty=False
        )
    if args.conserve_providers is not None:
        policy["conserveProviders"] = validate_provider_list(
            args.conserve_providers, "conserve providers", allow_empty=True
        )
    if args.max_workers is not None:
        policy["maxWorkers"] = args.max_workers
    if args.max_concurrent is not None:
        policy["maxConcurrent"] = args.max_concurrent
    budget = dict(policy.get("budget", {}))
    for key, value in (
        ("maxCalls", args.max_calls),
        ("maxWallSeconds", args.max_wall_seconds),
        ("maxEstimatedPromptTokens", args.max_estimated_prompt_tokens),
        ("maxReportedCostUsd", args.max_reported_cost_usd),
        ("maxReportedTokens", args.max_reported_tokens),
    ):
        if value is not None:
            budget[key] = value
    policy["budget"] = validate_budget(budget, "policy.budget")
    tiers = {
        tier: {provider: dict(spec) for provider, spec in mapping.items()}
        for tier, mapping in policy.get("modelTiers", {}).items()
    }
    for tier, key, values in (
        ("cheap", "model", args.cheap_model),
        ("cheap", "effort", args.cheap_effort),
        ("strong", "model", args.strong_model),
    ):
        if values:
            for pair in values:
                provider, separator, value = pair.partition("=")
                if not separator or not provider.strip() or not value.strip():
                    raise PlanError(f"expected PROVIDER={key.upper()}, got {pair!r}")
                tiers.setdefault(tier, {}).setdefault(provider.strip(), {})[key] = value.strip()
    policy["modelTiers"] = validate_model_tiers(tiers, "policy.modelTiers")
    policy["onboarded"] = True
    policy = validate_policy(policy)
    save_policy(policy_path, policy)
    return policy


def main(argv: Optional[Sequence[str]] = None) -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure and (sys.stdout.encoding or "").lower().replace("-", "") != "utf8":
        reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version", action="version", version=f"alethe-orchestrate {skill_version() or 'unknown'}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("strategies", help="list orchestration strategies and limits")
    playbook_parser = subparsers.add_parser(
        "playbook", help="print the strategy playbooks the planner follows"
    )
    playbook_parser.add_argument("--policy", type=Path)
    playbook_parser.add_argument("--path", action="store_true", help="print only the effective file path")
    playbook_parser.add_argument("--init", action="store_true", help="copy the bundled playbooks for editing")
    playbook_parser.add_argument("--force", action="store_true", help="with --init, replace an existing copy")
    probe_parser = subparsers.add_parser("probe", help="report available built-in providers")
    probe_parser.add_argument("providers", nargs="*", choices=["codex", "claude", "agy", "kimi"])
    doctor_parser = subparsers.add_parser("doctor", help="check the environment and saved policy")
    doctor_parser.add_argument("--policy", type=Path)
    scaffold_parser = subparsers.add_parser(
        "scaffold", help="print a starter plan for a strategy"
    )
    scaffold_parser.add_argument("strategy", choices=list(STRATEGIES))
    scaffold_parser.add_argument("--workers", type=int, default=1)
    scaffold_parser.add_argument("--cwd", default=".")
    scaffold_parser.add_argument("--provider", default="auto")
    scaffold_parser.add_argument("--write", type=Path)
    validate_parser = subparsers.add_parser("validate", help="validate a batch plan without running it")
    validate_parser.add_argument("plan", type=Path)
    validate_parser.add_argument("--policy", type=Path)
    validate_parser.add_argument("--strategy", choices=list(STRATEGIES))
    dry_run_parser = subparsers.add_parser(
        "dry-run", help="explain the strategy, providers, and budget a plan would use"
    )
    dry_run_parser.add_argument("plan", type=Path)
    dry_run_parser.add_argument("--policy", type=Path)
    dry_run_parser.add_argument("--strategy", choices=list(STRATEGIES))
    dry_run_parser.add_argument("--write", type=Path, help="save the resolved preview as JSON")
    run_parser = subparsers.add_parser("run", help="run a batch plan")
    run_parser.add_argument("plan", type=Path)
    run_parser.add_argument("--run-dir", type=Path)
    run_parser.add_argument("--policy", type=Path)
    run_parser.add_argument("--strategy", choices=list(STRATEGIES))
    report_parser = subparsers.add_parser(
        "report", help="explain what runs did, why, and what they reported spending"
    )
    report_parser.add_argument(
        "runs",
        nargs="*",
        type=Path,
        help="run directories, or a folder holding one per wave; defaults to the latest run",
    )
    report_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    report_parser.add_argument("--write", type=Path, help="also save the report to this file")
    status_parser = subparsers.add_parser(
        "status", help="print a few lines on where an orchestration stands, to pick it up again"
    )
    status_parser.add_argument("runs", nargs="*", type=Path)
    budget_parser = subparsers.add_parser(
        "budget", help="show or set the limits for every wave in an orchestration folder"
    )
    budget_parser.add_argument("folder", type=Path)
    budget_parser.add_argument("--max-calls", type=int)
    budget_parser.add_argument("--max-reported-cost-usd", type=float)
    budget_parser.add_argument("--max-reported-tokens", type=int)
    budget_parser.add_argument("--clear", action="store_true", help="remove the orchestration budget")
    mark_parser = subparsers.add_parser(
        "mark", help="record whether a worker's result was used, so the report shows what the spend bought"
    )
    mark_parser.add_argument("run_dir", type=Path)
    mark_parser.add_argument("worker")
    mark_parser.add_argument("mark", choices=list(MARKS))
    mark_parser.add_argument("--why")
    policy_parser = subparsers.add_parser("policy", help="show or change skill-only preferences")
    policy_parser.add_argument("policy_action", choices=["show", "set", "reset"])
    policy_parser.add_argument("strategy", nargs="?", choices=list(STRATEGIES))
    policy_parser.add_argument("--file", type=Path)
    policy_parser.add_argument("--backend", choices=["auto", "skill", "mcp"])
    policy_parser.add_argument("--provider-switch", choices=["ask", "automatic", "never"])
    policy_parser.add_argument("--provider-order", nargs="+", choices=list(BUILTIN_PROVIDERS))
    policy_parser.add_argument(
        "--conserve-providers", nargs="*", choices=list(BUILTIN_PROVIDERS)
    )
    policy_parser.add_argument("--max-workers", type=int)
    policy_parser.add_argument("--max-concurrent", type=int)
    policy_parser.add_argument("--max-calls", type=int)
    policy_parser.add_argument("--max-wall-seconds", type=int)
    policy_parser.add_argument("--max-estimated-prompt-tokens", type=int)
    policy_parser.add_argument("--max-reported-cost-usd", type=float)
    policy_parser.add_argument("--max-reported-tokens", type=int)
    policy_parser.add_argument("--cheap-model", nargs="*", metavar="PROVIDER=MODEL")
    policy_parser.add_argument("--cheap-effort", nargs="*", metavar="PROVIDER=EFFORT")
    policy_parser.add_argument("--strong-model", nargs="*", metavar="PROVIDER=MODEL")
    args = parser.parse_args(argv)

    try:
        if args.command == "strategies":
            print(json.dumps(strategies_payload(), indent=2))
            return 0
        if args.command == "playbook":
            policy_path = (args.policy or default_policy_path()).expanduser().resolve()
            if args.init:
                print(str(init_playbooks(policy_path, args.force)))
                return 0
            path = effective_playbooks_path(policy_path)
            if args.path:
                print(str(path))
                return 0
            text = read_playbooks(path)
            print(f"# source: {path}")
            print(text, end="" if text.endswith("\n") else "\n")
            return 0
        if args.command == "probe":
            providers = args.providers or ["codex", "claude", "agy", "kimi"]
            print(json.dumps([probe_provider(provider) for provider in providers], indent=2))
            return 0
        if args.command == "doctor":
            policy_path = (args.policy or default_policy_path()).expanduser().resolve()
            print(json.dumps(doctor_payload(policy_path), indent=2, ensure_ascii=False))
            return 0
        if args.command == "report":
            report = build_report(find_run_dirs(args.runs))
            if args.format == "json":
                text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
            else:
                text = render_markdown(report)
            if args.write:
                atomic_write_text(args.write.expanduser(), text)
            print(text, end="")
            return 0
        if args.command == "status":
            print(render_status(build_report(find_run_dirs(args.runs))), end="")
            return 0
        if args.command == "budget":
            updates = {
                key: value
                for key, value in (
                    ("maxCalls", args.max_calls),
                    ("maxReportedCostUsd", args.max_reported_cost_usd),
                    ("maxReportedTokens", args.max_reported_tokens),
                )
                if value is not None
            }
            if args.clear and updates:
                raise PlanError("pass --clear or new limits, not both")
            print(json.dumps(budget_payload(args.folder, updates, args.clear), indent=2))
            return 0
        if args.command == "mark":
            print(json.dumps(mark_payload(args.run_dir, args.worker, args.mark, args.why), indent=2, ensure_ascii=False))
            return 0
        if args.command == "scaffold":
            plan = scaffold_plan(args.strategy, args.workers, args.cwd, args.provider)
            if args.write:
                atomic_write_json(args.write, plan)
            print(json.dumps(plan, indent=2))
            return 0
        if args.command == "policy":
            policy_path = (args.file or default_policy_path()).expanduser().resolve()
            policy = update_policy(args, policy_path)
            print(json.dumps({"path": str(policy_path), "policy": policy}, indent=2))
            return 0
        if args.command == "validate":
            policy_path = (args.policy or default_policy_path()).expanduser().resolve()
            plan = validate_plan(
                read_json(args.plan),
                args.plan.resolve(),
                load_policy(policy_path),
                args.strategy,
            )
            summary = {
                "valid": True,
                "strategy": plan["strategy"],
                "requestedStrategy": plan["requestedStrategy"],
                "maxConcurrent": plan["maxConcurrent"],
                "budget": plan["budget"],
                "policyPath": str(policy_path),
                "warnings": plan_warnings(plan),
                "workers": [
                    {
                        "id": worker["id"],
                        "provider": worker["provider"],
                        "requestedProvider": worker["requestedProvider"],
                        "mode": worker["mode"],
                        "isolate": worker["isolate"],
                    }
                    for worker in plan["workers"]
                ],
            }
            print(json.dumps(summary, indent=2))
            return 0
        if args.command == "dry-run":
            policy_path = (args.policy or default_policy_path()).expanduser().resolve()
            plan = validate_plan(
                read_json(args.plan),
                args.plan.resolve(),
                load_policy(policy_path),
                args.strategy,
            )
            preview = plan_payload(plan, args.plan.resolve(), policy_path)
            if args.write:
                atomic_write_json(args.write, preview)
            print(
                json.dumps(
                    preview,
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0
        policy_path = (args.policy or default_policy_path()).expanduser().resolve()
        return run_batch(args.plan, args.run_dir, policy_path, args.strategy)
    except PlanError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
