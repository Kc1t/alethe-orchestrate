import json
import sys
from pathlib import Path


def main() -> int:
    mode = sys.argv[1]
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
    if mode == "fail":
        print("boom: missing fixture", file=sys.stderr)
        return 1
    raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    raise SystemExit(main())
