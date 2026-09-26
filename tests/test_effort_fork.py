#!/usr/bin/env python3
"""Tests for the arian/windows-compat fork seams of bench/effort.py: tier-scoped
scales, stripped run mode, and the Windows-safe sandbox."""
import argparse
import os
import shutil
import sys
import tempfile
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
    def test_default_argv_is_the_legacy_command(self):
        # Literal legacy argv from invoke_claude at 9561671.
        self.assertEqual(
            e.build_claude_cmd("PROMPT", "high", "m", settings_path="s.json"),
            ["claude", "-p", "--effort", "high", "--model", "m",
             "--output-format", "json", "--settings", "s.json", "PROMPT"])
        self.assertEqual(
            e.build_claude_cmd("PROMPT", "low", "m"),
            ["claude", "-p", "--effort", "low", "--model", "m",
             "--output-format", "json", "PROMPT"])

    def test_stripped_argv(self):
        cmd = e.build_claude_cmd("PROMPT", "xhigh", "m", settings_path="cap.json",
                                 stripped=True, append_system_prompt_file="ctx.md")
        self.assertEqual(
            cmd,
            ["claude", "-p", "--effort", "xhigh", "--model", "m",
             "--output-format", "json", "--setting-sources", "", "--strict-mcp-config",
             "--settings", "cap.json", "--append-system-prompt-file", "ctx.md", "PROMPT"])
        # The empty setting-sources value must be its own argv element.
        i = cmd.index("--setting-sources")
        self.assertEqual(cmd[i + 1], "")

    def test_invoke_claude_passes_mode_to_subprocess(self):
        seen = []

        class _P:
            returncode, stdout, stderr = 0, "{}", ""

        def fake_run(cmd, **kw):
            seen.append(cmd)
            return _P()

        orig = e.subprocess.run
        e.subprocess.run = fake_run
        try:
            e.invoke_claude("P", "low", "m", 5, {}, "cap.json", stripped=True,
                            append_system_prompt_file="ctx.md")
        finally:
            e.subprocess.run = orig
        self.assertEqual(seen, [e.build_claude_cmd("P", "low", "m", "cap.json", True,
                                                   "ctx.md")])


if __name__ == "__main__":
    unittest.main()
