#!/usr/bin/env python3
"""Tests for the arian/windows-compat fork seams of bench/effort.py: tier-scoped
scales, stripped run mode, and the Windows-safe sandbox."""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.join(os.path.dirname(HERE), "bench")
sys.path.insert(0, BENCH)
import effort as e  # noqa: E402

TASKS_DIR = os.path.join(BENCH, "tasks")
FOUR_TIERS = {"low", "medium", "high", "xhigh"}


def _ns(root, **over):
    base = dict(root=root, tasks_dir=TASKS_DIR, seed=e.SEED_DEFAULT, model=e.MODEL,
                mock=True, scale="pilot", parallel=1, rerun_failed=False, regrade=False,
                force=False)
    base.update(over)
    return argparse.Namespace(**base)


class TierScopedPipelineTest(unittest.TestCase):
    """Option A: a pilot4 scale runs low..xhigh only; every downstream stage must
    treat the missing max tier as n/a, never KeyError and never silent zeros."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="effort-pilot4-")
        self.paths = e.Paths(self.tmp, TASKS_DIR)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_build_cells_pilot4_has_no_max(self):
        tasks = e.load_tasks(TASKS_DIR)
        cells = e.build_cells(tasks, "pilot4")
        self.assertEqual({c["tier"] for c in cells}, FOUR_TIERS)
        self.assertEqual(len(cells), len(tasks) * 4 * 3)
        # TIERS itself is untouched: max support stays for 5-tier scales.
        self.assertIn("max", e.TIERS)
        self.assertIn("max", {c["tier"] for c in e.build_cells(tasks, "pilot")})

    def test_build_cells_probe_low_is_low_only_single_rep(self):
        # Difficulty pilot: find the generator difficulty where low passes ~50%.
        tasks = e.load_tasks(TASKS_DIR)
        cells = e.build_cells(tasks, "probe-low")
        self.assertEqual({c["tier"] for c in cells}, {"low"})
        self.assertEqual(len(cells), len(tasks))

    def test_mock_pipeline_on_four_tier_scale(self):
        ns = _ns(self.tmp, scale="pilot4")
        self.assertEqual(e.cmd_validate(ns), 0)
        e.cmd_run(ns)
        e.cmd_grade(ns)
        self.assertEqual(e.cmd_analyze(ns), 0)
        self.assertEqual(e.cmd_report(ns), 0)
        self.assertEqual(e.cmd_calibrate(ns), 0)

        results, _ = e.read_jsonl(self.paths.results)
        self.assertEqual({r["tier"] for r in results}, FOUR_TIERS)

        a = e.load_json(self.paths.analysis)
        self.assertEqual(set(a["manifest"]["tiers_present"]), FOUR_TIERS)
        # uniform_max is omitted, so it cannot empty the comparable-task set.
        self.assertNotIn("uniform_max", a["policies"])
        pc = a["policy_comparison"]
        self.assertIs(pc["incomplete_matrix"], False)
        self.assertIsInstance(pc["undominated"], bool)
        # H3 (max vs xhigh) is n/a, not a silent "not observed".
        for cls, info in a["per_class"].items():
            self.assertIsNone(info["overthinking"]["flag"], cls)
            self.assertIsNone(info["overthinking"]["strict_regression"], cls)

        with open(self.paths.results_md, encoding="utf-8") as f:
            md = f.read()
        self.assertNotIn("uniform_max", md)
        self.assertNotIn("(not max)", md)
        self.assertIn("H3 (overthinking tail at max): n/a", md)

        cal = e.load_json(self.paths.calibration)
        for cls, c in cal["classes"].items():
            self.assertIn(c["recommended_tier"], FOUR_TIERS, cls)
            self.assertIsNone(c["overthinking"], cls)


class BuildClaudeCmdTest(unittest.TestCase):
    def test_default_argv_is_the_legacy_command_minus_the_prompt(self):
        # Legacy argv from invoke_claude at 9561671, with the prompt moved to stdin.
        self.assertEqual(
            e.build_claude_cmd("high", "m", settings_path="s.json"),
            ["claude", "-p", "--effort", "high", "--model", "m",
             "--output-format", "json", "--settings", "s.json"])
        self.assertEqual(
            e.build_claude_cmd("low", "m"),
            ["claude", "-p", "--effort", "low", "--model", "m",
             "--output-format", "json"])

    def test_stripped_argv(self):
        cmd = e.build_claude_cmd("xhigh", "m", settings_path="cap.json",
                                 stripped=True, append_system_prompt_file="ctx.md")
        self.assertEqual(
            cmd,
            ["claude", "-p", "--effort", "xhigh", "--model", "m",
             "--output-format", "json", "--setting-sources", "", "--strict-mcp-config",
             "--settings", "cap.json", "--append-system-prompt-file", "ctx.md"])
        # The empty setting-sources value must be its own argv element.
        i = cmd.index("--setting-sources")
        self.assertEqual(cmd[i + 1], "")

    def test_invoke_claude_passes_mode_to_subprocess(self):
        seen = []

        class _P:
            returncode, stdout, stderr = 0, "{}", ""

        def fake_run(cmd, **kw):
            seen.append((cmd, kw.get("input")))
            return _P()

        long_prompt = "x" * 40000  # past the ~32k Windows command-line cap
        orig = e.subprocess.run
        e.subprocess.run = fake_run
        try:
            e.invoke_claude(long_prompt, "low", "m", 5, {}, "cap.json", stripped=True,
                            append_system_prompt_file="ctx.md")
        finally:
            e.subprocess.run = orig
        self.assertEqual(seen, [(e.build_claude_cmd("low", "m", "cap.json", True, "ctx.md"),
                                 long_prompt)])

    def test_launch_failure_reports_the_os_error(self):
        # WinError 206 (command line too long) subclasses FileNotFoundError; it must
        # not be reported as a missing CLI.
        def fake_run(cmd, **kw):
            raise FileNotFoundError(206, "The filename or extension is too long")

        orig = e.subprocess.run
        e.subprocess.run = fake_run
        try:
            res = e.invoke_claude("P", "low", "m", 5, {})
        finally:
            e.subprocess.run = orig
        self.assertEqual(res.returncode, 127)
        self.assertIn("too long", res.stderr)


class StrippedAutoMemoryTest(unittest.TestCase):
    """Stripped runs must not see the host's auto-memory (MEMORY.md): --setting-sources ""
    does not stop it (request body captured 2026-09-26); the env switch does."""

    def _env_seen(self, stripped):
        seen = []

        class _P:
            returncode, stdout, stderr = 0, "{}", ""

        def fake_run(cmd, **kw):
            seen.append(kw["env"])
            return _P()

        orig = e.subprocess.run
        e.subprocess.run = fake_run
        try:
            e.invoke_claude("P", "low", "m", 5, {"PATH": "p"}, stripped=stripped)
        finally:
            e.subprocess.run = orig
        return seen[0]

    def test_stripped_disables_auto_memory(self):
        self.assertEqual(self._env_seen(True).get("CLAUDE_CODE_DISABLE_AUTO_MEMORY"), "1")

    def test_default_mode_leaves_env_alone(self):
        self.assertEqual(self._env_seen(False), {"PATH": "p"})


class ChildEnvEffortTest(unittest.TestCase):
    def test_session_effort_readout_is_not_inherited(self):
        # CLAUDE_EFFORT is the parent session's effort as Claude Code exports it; a child
        # run must be governed by --effort alone.
        env, _ = e.build_child_env({"CLAUDE_EFFORT": "high", "PATH": "p"})
        self.assertNotIn("CLAUDE_EFFORT", env)
        self.assertEqual(env["PATH"], "p")


class ValidateStrippedTest(unittest.TestCase):
    """validate --stripped probes the same configuration the stripped matrix runs."""

    def test_validate_accepts_stripped(self):
        p = e.build_parser()
        self.assertIs(p.parse_args(["validate", "--stripped"]).stripped, True)
        self.assertIs(p.parse_args(["validate"]).stripped, False)

    def test_every_validate_probe_is_stripped(self):
        tmp = tempfile.mkdtemp(prefix="effort-validate-")
        calls = []
        orig = (e.invoke_claude, e.detect_cli_version)

        def fake_invoke(prompt, tier, model, timeout_s, env, settings_path=None, **kw):
            calls.append(kw.get("stripped"))
            env_json = {"result": "ok", "session_id": "s", "effort": tier,
                        "usage": {"input_tokens": 1, "output_tokens": 1},
                        "total_cost_usd": 0.0}
            return e._SandboxResult(0, json.dumps(env_json), "", False)

        e.invoke_claude, e.detect_cli_version = fake_invoke, (lambda: "fake")
        try:
            ns = _ns(tmp, mock=False, stripped=True)
            e.cmd_validate(ns)
        finally:
            e.invoke_claude, e.detect_cli_version = orig
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertTrue(calls)
        self.assertEqual(set(calls), {True})


class StrippedRunModeTest(unittest.TestCase):
    """--stripped / --worker-context reach every claude call made during run/grade.
    invoke_claude and detect_cli_version are faked: no real claude process runs."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="effort-stripped-")
        self.tasks = os.path.join(self.tmp, "tasks")
        os.makedirs(self.tasks)
        shutil.copy(os.path.join(TASKS_DIR, "T1a.json"), self.tasks)
        self.ctx = os.path.join(self.tmp, "worker.md")
        with open(self.ctx, "w", encoding="utf-8") as f:
            f.write("You are a delegate worker.\n")
        self.calls = []
        self._orig = (e.invoke_claude, e.detect_cli_version)

        def fake_invoke(prompt, tier, model, timeout_s, env, settings_path=None, **kw):
            self.calls.append({"tier": tier, "settings_path": settings_path, **kw})
            env_json = {"result": "<answer>x</answer>", "session_id": "s", "effort": tier,
                        "usage": {"input_tokens": 1, "output_tokens": 1}}
            if "GRADE THIS PAYLOAD" in prompt:
                env_json["result"] = '{"criteria": [], "score": 1.0, "pass": true}'
            return e._SandboxResult(0, json.dumps(env_json), "", False)

        e.invoke_claude = fake_invoke
        e.detect_cli_version = lambda: "fake"

    def tearDown(self):
        e.invoke_claude, e.detect_cli_version = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_run_passes_stripped_and_worker_context(self):
        ns = _ns(self.tmp, tasks_dir=self.tasks, mock=False, force=True,
                 stripped=True, worker_context=self.ctx)
        self.assertEqual(e.cmd_run(ns), 0)
        self.assertEqual(len(self.calls), 5 * 3)
        for c in self.calls:
            self.assertIs(c.get("stripped"), True)
            self.assertEqual(c.get("append_system_prompt_file"), os.path.abspath(self.ctx))
            self.assertTrue(c["settings_path"])  # capture hook still installed

    def test_blind_grader_honors_stripped_without_worker_context(self):
        shutil.copy(os.path.join(HERE, "fixtures-v2", "R2_blind.json"), self.tasks)
        os.remove(os.path.join(self.tasks, "T1a.json"))
        ns = _ns(self.tmp, tasks_dir=self.tasks, mock=False, force=True, suite="v2",
                 grade_mock=False, stripped=True, worker_context=self.ctx)
        self.assertEqual(e.cmd_run(ns), 0)
        del self.calls[:]
        self.assertEqual(e.cmd_grade(ns), 0)
        self.assertEqual(len(self.calls), 5 * 3)  # one grader call per cell
        for c in self.calls:
            self.assertEqual(c["tier"], e.GRADER_EFFORT)
            self.assertIs(c.get("stripped"), True)
            # The worker's context is not the grader's: blindness by payload shape.
            self.assertIsNone(c.get("append_system_prompt_file"))

    def test_run_composite_passes_stripped_and_worker_context(self):
        shutil.copy(os.path.join(HERE, "fixtures-v2", "X1_composite.json"), self.tasks)
        ns = _ns(self.tmp, tasks_dir=self.tasks, mock=False, force=True, suite="v2",
                 arms="uniform_high", reps=1, stripped=True, worker_context=self.ctx)
        self.assertEqual(e.cmd_run_composite(ns), 0)
        self.assertTrue(self.calls)
        for c in self.calls:
            self.assertIs(c.get("stripped"), True)
            self.assertEqual(c.get("append_system_prompt_file"), os.path.abspath(self.ctx))

    def test_cli_flags_on_run_grade_and_run_composite(self):
        p = e.build_parser()
        for sub in ("run", "run-composite", "grade"):
            a = p.parse_args([sub, "--stripped", "--worker-context", "w.md"])
            self.assertIs(a.stripped, True, sub)
            self.assertEqual(a.worker_context, "w.md", sub)
            d = p.parse_args([sub])
            self.assertIs(d.stripped, False, sub)
            self.assertIsNone(d.worker_context, sub)

    def test_missing_worker_context_file_is_a_hard_error(self):
        ns = _ns(self.tmp, tasks_dir=self.tasks, mock=False, force=True,
                 stripped=True, worker_context=os.path.join(self.tmp, "nope.md"))
        with self.assertRaises(SystemExit):
            e.cmd_run(ns)
        self.assertEqual(self.calls, [])


class SandboxTreeKillTest(unittest.TestCase):
    """A sandbox timeout must kill the whole process tree, not just the child."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="effort-sbx-test-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_timeout_kills_grandchild(self):
        marker = os.path.join(self.tmp, "grandchild-survived")
        started = os.path.join(self.tmp, "grandchild-started")
        grandchild = (f"import time; open({started!r}, 'w').write('x'); "
                      f"time.sleep(6); open({marker!r}, 'w').write('x')")
        program = ("import subprocess, sys, time\n"
                   f"subprocess.Popen([sys.executable, '-c', {grandchild!r}])\n"
                   "time.sleep(30)\n")
        t0 = time.monotonic()
        res = e.run_sandboxed(program, 2)
        elapsed = time.monotonic() - t0
        if "BlockingIOError" in res.stderr:
            # POSIX sandbox's RLIMIT_NPROC=64 is UID-wide; on some hosts (seen on
            # WSL2) the grandchild fork gets EAGAIN, so the tree path is unreachable.
            self.skipTest("sandbox RLIMIT_NPROC blocked the grandchild spawn")
        self.assertTrue(res.timed_out)
        self.assertLess(elapsed, 4.0)
        # Positive control: the grandchild really ran, so its absence below is a kill.
        self.assertTrue(os.path.exists(started), "grandchild never started")
        time.sleep(7)  # past the grandchild's 6 s sleep
        self.assertFalse(os.path.exists(marker), "grandchild outlived the timeout")

    def test_non_ascii_stdout_round_trips(self):
        res = e.run_sandboxed("print('\\u03bb')\n", 5)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout, "\u03bb\n")


if __name__ == "__main__":
    unittest.main()
