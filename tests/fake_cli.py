import json
import os
import sys
import time
from pathlib import Path


def main() -> int:
    mode = sys.argv[1]
    if mode != "sleep":
        sys.stdin.read()
    if mode == "claude":
        print(
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "result": "## Outcome\nFound 14 callers of login() across src/api and src/ui.\n",
                    "session_id": "sess-claude-1",
                    "total_cost_usd": 0.0421,
                    "usage": {
                        "input_tokens": 1200,
                        "cache_creation_input_tokens": 3000,
                        "cache_read_input_tokens": 18000,
                        "output_tokens": 800,
                    },
                }
            )
        )
        return 0
    if mode == "denied":
        events = [
            {"type": "system", "subtype": "init", "session_id": "sess-denied"},
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "Ran the tests.\nSTATUS: DONE\nSUMMARY: Fixed the parser and ran the tests.",
                "session_id": "sess-denied",
                "total_cost_usd": 0.01,
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "modelUsage": {"claude-haiku-4-5": {"inputTokens": 100}},
                "permission_denials": [{"tool_name": "Bash", "tool_use_id": "t1"}],
            },
        ]
        for event in events:
            print(json.dumps(event))
        return 0
    if mode == "codex":
        result_path, edited = sys.argv[2], sys.argv[3]
        Path(edited).write_text("base\nrenamed helper\n", encoding="utf-8")
        Path(result_path).write_text("Renamed the helper in README.md.\n", encoding="utf-8")
        events = [
            {"type": "thread.started", "thread_id": "thread-codex-1"},
            {"type": "turn.completed", "usage": {"input_tokens": 52000, "cached_input_tokens": 40000, "output_tokens": 2100}},
        ]
        for event in events:
            print(json.dumps(event))
        return 0
    if mode == "write":
        Path(sys.argv[2]).write_text("hello\nworld\n", encoding="utf-8")
        print("Outcome: wrote the new file with two lines.")
        return 0
    if mode == "say":
        print(sys.argv[2])
        return 0
    if mode == "fail":
        print("boom: missing fixture", file=sys.stderr)
        return 1
    if mode == "ratelimit":
        print("Error: 429 Too Many Requests. Your usage limit resets at 5:00 PM.", file=sys.stderr)
        return 1
    if mode == "sleep":
        time.sleep(float(sys.argv[2]))
        print("Outcome: woke up.")
        return 0
    if mode == "env":
        names = ("ALETHE_ORCHESTRATE_WORKER", "CLAUDECODE")
        print(json.dumps({name: os.environ.get(name) for name in names}))
        return 0
    if mode == "argv":
        Path(sys.argv[2]).write_text(json.dumps(sys.argv[3:]), encoding="utf-8")
        print("Outcome: recorded the arguments.")
        return 0
    raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    raise SystemExit(main())
