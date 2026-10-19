import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "alethe-orchestrate"
SCRIPT = SKILL / "scripts" / "orchestrate.py"
FAKE = Path(__file__).resolve().parent / "fake_cli.py"

spec = importlib.util.spec_from_file_location("orchestrate", SCRIPT)
orchestrate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orchestrate)


def remove_tree(path):
    def retry(function, target, _info):
        os.chmod(target, stat.S_IWRITE)
        function(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=retry)
    else:
        shutil.rmtree(path, onerror=retry)


def git(cwd, *args):
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="orchestrate-test-"))
        self.addCleanup(remove_tree, self.root)
        self.policy = self.root / "policy.json"

    def call(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = orchestrate.main([str(arg) for arg in args])
        return code, out.getvalue(), err.getvalue()

    def make_repo(self):
        repo = self.root / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        git(repo, "add", "README.md")
        git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "init")
        return repo

    def worker(self, worker_id, mode, args, output_format, cwd, **extra):
        return {
            "id": worker_id,
            "provider": "custom",
            "mode": mode,
            "cwd": str(cwd),
            "command": sys.executable,
            "args": [str(FAKE), *args],
            "outputFormat": output_format,
            "task": f"Task for {worker_id}.",
            **extra,
        }

    def write_plan(self, name, plan):
        path = self.root / f"{name}.json"
        path.write_text(json.dumps(plan), encoding="utf-8")
        return path

    def run_two_waves(self):
        repo = self.make_repo()
        orchestration = self.root / "orchestration"
        shared = {"version": 1, "title": "Rename the login helper", "playbook": "plan-big-execute-small"}
        explore = self.write_plan(
            "explore",
            {
                **shared,
                "phase": "explore",
                "why": "Map the callers before changing anything.",
                "strategy": "research",
                "maxConcurrent": 1,
                "budget": {"maxCalls": 2},
                "workers": [
                    self.worker("map-callers", "read-only", ["claude"], "json", repo, why="find every caller"),
                    self.worker("broken", "read-only", ["fail"], "text", repo, why="expected to fail"),
                    self.worker("extra", "read-only", ["claude"], "json", repo, why="stopped by the budget"),
                ],
            },
        )
        build = self.write_plan(
            "build",
            {
                **shared,
                "phase": "build",
                "strategy": "balanced",
                "maxConcurrent": 1,
                "workers": [
                    self.worker(
                        "rename", "write", ["codex", "{result}", "README.md"], "jsonl", repo, why="mechanical rename"
                    ),
                    self.worker("add-file", "write", ["write", "hello.txt"], "text", repo, isolate=True),
                ],
            },
        )
        code, _, err = self.call("run", explore, "--run-dir", orchestration / "01-explore", "--policy", self.policy)
        self.assertEqual(code, 1, err)
        code, _, err = self.call("run", build, "--run-dir", orchestration / "02-build", "--policy", self.policy)
        self.assertEqual(code, 0, err)
        return repo, orchestration

    def test_plan_notes_reach_the_preview(self):
        plan = self.write_plan(
            "plan",
            {
                "version": 1,
                "title": "Rename   the\nhelper",
                "why": "Map callers first.",
                "playbook": "plan-big-execute-small",
                "phase": "explore",
                "workers": [self.worker("map", "read-only", ["claude"], "json", self.root, why="find every caller")],
            },
        )
        code, out, err = self.call("dry-run", plan, "--policy", self.policy)
        self.assertEqual(code, 0, err)
        preview = json.loads(out)
        self.assertEqual(preview["title"], "Rename the helper")
        self.assertEqual(preview["phase"], "explore")
        self.assertEqual(preview["workers"][0]["why"], "find every caller")
        self.assertEqual(preview["workers"][0]["command"], Path(sys.executable).stem)

    def test_long_or_unknown_notes_are_refused(self):
        worker = self.worker("a", "read-only", ["claude"], "json", self.root)
        too_long = self.write_plan("long", {"version": 1, "why": "x" * 501, "workers": [worker]})
        code, _, err = self.call("validate", too_long, "--policy", self.policy)
        self.assertEqual(code, 2)
        self.assertIn("plan.why must be at most 500 characters", err)
        unknown = self.write_plan("unknown", {"version": 1, "reason": "x", "workers": [worker]})
        code, _, err = self.call("validate", unknown, "--policy", self.policy)
        self.assertEqual(code, 2)
        self.assertIn("unknown plan fields: reason", err)

    def test_flags_that_approve_every_tool_need_permission(self):
        for flag in ("--trust-all-tools", "--allow-all-tools", "--yolo"):
            plan = self.write_plan("unsafe", {"version": 1, "workers": [self.worker("a", "write", [flag], "text", self.root)]})
            code, _, err = self.call("validate", plan, "--policy", self.policy)
            self.assertEqual(code, 2)
            self.assertIn("unsafe flag", err)
        allowed = self.worker("a", "write", ["--yolo"], "text", self.root, allowUnsafe=True)
        plan = self.write_plan("allowed", {"version": 1, "workers": [allowed]})
        self.assertEqual(self.call("validate", plan, "--policy", self.policy)[0], 0)

    def test_report_explains_what_each_wave_did_and_spent(self):
        _, orchestration = self.run_two_waves()
        code, out, err = self.call("report", orchestration, "--format", "json")
        self.assertEqual(code, 0, err)
        report = json.loads(out)
        totals = report["totals"]
        self.assertEqual(totals["runs"], 2)
        self.assertEqual(totals["statuses"], {"succeeded": 3, "failed": 1, "skipped": 1})
        self.assertEqual(totals["tokens"], 77100)
        self.assertEqual(totals["cachedTokens"], 58000)
        self.assertAlmostEqual(totals["costUsd"], 0.0421)
        self.assertEqual(totals["budgetStops"], ["budget maxCalls 2 exhausted"])
        self.assertEqual(totals["changes"], {"writers": 2, "files": 2, "insertions": 3, "deletions": 0})
        self.assertEqual(report["playbooks"], ["plan-big-execute-small"])

        explore = {worker["id"]: worker for worker in report["runs"][0]["workers"]}
        self.assertEqual(explore["map-callers"]["summary"], "Found 14 callers of login() across src/api and src/ui.")
        self.assertEqual(explore["map-callers"]["why"], "find every caller")
        self.assertEqual(explore["broken"]["stderrTail"], "boom: missing fixture")
        self.assertEqual(explore["extra"]["error"], "budget maxCalls 2 exhausted")

        follow = report["followUps"]
        self.assertEqual([item["worker"] for item in follow["worktrees"]], ["add-file"])
        self.assertEqual([item["worker"] for item in follow["mainCheckoutChanges"]], ["rename"])
        self.assertEqual(sorted(item["worker"] for item in follow["attention"]), ["broken", "extra"])

        saved = self.root / "report.md"
        code, markdown, _ = self.call("report", orchestration, "--write", saved)
        self.assertEqual(code, 0)
        self.assertIn("## 1. explore", markdown)
        self.assertIn("## 2. build", markdown)
        self.assertIn("- **Cost:** $0.04 reported by", markdown)
        self.assertIn("Failed: worker exited with status 1 (boom: missing fixture).", markdown)
        self.assertIn("- **Budget:** stopped 1 worker (budget maxCalls 2 exhausted)", markdown)
        self.assertEqual(saved.read_text(encoding="utf-8"), markdown)

    def test_worktrees_stay_out_of_git_status(self):
        repo, _ = self.run_two_waves()
        again = self.write_plan(
            "again", {"version": 1, "workers": [self.worker("second", "write", ["write", "b.txt"], "text", repo, isolate=True)]}
        )
        code, _, err = self.call("run", again, "--run-dir", self.root / "again", "--policy", self.policy)
        self.assertEqual(code, 0, err)
        self.assertEqual(git(repo, "status", "--porcelain").splitlines(), [" M README.md"])
        exclude = Path(git(repo, "rev-parse", "--git-path", "info/exclude").strip())
        exclude = exclude if exclude.is_absolute() else repo / exclude
        self.assertEqual(exclude.read_text(encoding="utf-8").count("/.alethe/worktrees/"), 1)

    def test_report_reads_runs_saved_before_plan_json(self):
        _, orchestration = self.run_two_waves()
        (orchestration / "01-explore" / "plan.json").unlink()
        code, out, err = self.call("report", orchestration / "01-explore", "--format", "json")
        self.assertEqual(code, 0, err)
        run = json.loads(out)["runs"][0]
        self.assertIsNone(run["phase"])
        self.assertEqual(len(run["workers"]), 3)

    def test_report_defaults_to_the_latest_run(self):
        scratch = self.root / "tmp"
        scratch.mkdir()
        previous = tempfile.tempdir
        tempfile.tempdir = str(scratch)
        self.addCleanup(setattr, tempfile, "tempdir", previous)
        plan = self.write_plan("one", {"version": 1, "workers": [self.worker("only", "read-only", ["claude"], "json", self.root)]})
        code, _, err = self.call("run", plan, "--policy", self.policy)
        self.assertEqual(code, 0, err)
        code, out, err = self.call("report", "--format", "json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["totals"]["workers"], 1)

    def test_report_prints_non_ascii_results_through_a_pipe(self):
        run_dir = self.root / "unicode"
        plan = self.write_plan("unicode", {"version": 1, "workers": [self.worker("only", "read-only", ["write", "out.txt"], "text", self.root)]})
        self.assertEqual(self.call("run", plan, "--run-dir", run_dir, "--policy", self.policy)[0], 0)
        (run_dir / "workers" / "only" / "result.md").write_text("Concluído: três arquivos → revisados.\n", encoding="utf-8")
        env = {key: value for key, value in os.environ.items() if key not in ("PYTHONIOENCODING", "PYTHONUTF8")}
        result = subprocess.run([sys.executable, str(SCRIPT), "report", str(run_dir)], capture_output=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        self.assertIn("três arquivos → revisados", result.stdout.decode("utf-8"))

    def test_version_comes_from_the_skill_metadata(self):
        version = re.search(r'version: "(\d+)"', (SKILL / "SKILL.md").read_text(encoding="utf-8")).group(1)
        self.assertEqual(orchestrate.skill_version(), version)
        result = subprocess.run([sys.executable, str(SCRIPT), "--version"], capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), f"alethe-orchestrate {version}")
        code, out, _ = self.call("doctor", "--policy", self.policy)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["skill"]["version"], version)

    def test_the_preview_renders_as_a_diagram(self):
        plan = self.write_plan("plan", {"version": 1, "workers": [self.worker("map", "read-only", ["claude"], "json", self.root)]})
        preview = self.root / "preview.json"
        code, _, err = self.call("dry-run", plan, "--policy", self.policy, "--write", preview)
        self.assertEqual(code, 0, err)
        svg = self.root / "plan.svg"
        result = subprocess.run(
            [sys.executable, str(SKILL / "scripts" / "diagram.py"), str(preview), str(svg)], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("<svg", svg.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
