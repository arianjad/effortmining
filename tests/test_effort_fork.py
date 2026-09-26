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


if __name__ == "__main__":
    unittest.main()
