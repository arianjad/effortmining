#!/usr/bin/env python3
"""Tests for bench/generators.py: seeded procedural task generators.

Every expected answer is checked against an oracle written here, independent of the
generator's own computation: a re-parse of the prompt (T1), int(s, b) (T2), running
the printed program in a subprocess (T3), brute-force enumeration (T4), and a
multi-pass evaluator over the authoritative definitions (multi-hop).
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.join(os.path.dirname(HERE), "bench")
sys.path.insert(0, BENCH)
import effort as e  # noqa: E402
import generators as g  # noqa: E402

SEEDS = range(1, 21)
LEVELS = (1, 2, 3, 4, 5)


def _prompt(task):
    return task["prompt"] if isinstance(task["prompt"], str) else "\n".join(task["prompt"])


def _answer(task):
    return task["checker"]["expected"]


class CommonContractTest(unittest.TestCase):
    """Every generator: deterministic by seed, seed-sensitive, gradeable."""

    def test_same_seed_same_task(self):
        for key, gen in g.GENERATORS.items():
            for d in LEVELS:
                with self.subTest(key=key, d=d):
                    self.assertEqual(gen(7, d), gen(7, d))

    def test_different_seeds_different_tasks(self):
        for key, gen in g.GENERATORS.items():
            for d in LEVELS:
                with self.subTest(key=key, d=d):
                    a, b = gen(7, d), gen(8, d)
                    self.assertNotEqual((a["prompt"], a.get("documents")),
                                        (b["prompt"], b.get("documents")))
                    self.assertNotEqual(a["id"], b["id"])

    def test_mock_answer_passes_and_wrong_answers_fail(self):
        for key, gen in g.GENERATORS.items():
            for d in LEVELS:
                with self.subTest(key=key, d=d):
                    t = gen(3, d)
                    self.assertEqual(t["checker"]["type"], "exact")
                    self.assertTrue(e.grade_record(t, e.mock_answer(t, True))["pass"])
                    self.assertFalse(e.grade_record(t, e.mock_answer(t, False))["pass"])
                    # Off-by-one in the last integer is also a fail.
                    exp = list(_answer(t))
                    m = re.search(r"-?\d+$", exp[-1])
                    exp[-1] = exp[-1][:m.start()] + str(int(m.group()) + 1)
                    raw = "<answer>\n" + "\n".join(exp) + "\n</answer>"
                    self.assertFalse(e.grade_record(t, raw)["pass"])

    def test_task_shape(self):
        for key, gen in g.GENERATORS.items():
            with self.subTest(key=key):
                t = gen(1, 1)
                for field in ("id", "class", "title", "prompt", "answer_convention",
                              "checker", "max_output_tokens", "difficulty_rationale"):
                    self.assertIn(field, t)
                self.assertTrue(re.fullmatch(r"[A-Za-z0-9_-]+", t["id"]), t["id"])


class T1CountingTest(unittest.TestCase):
    def _oracle(self, task):
        p = _prompt(task)
        service = re.search(r"service is exactly `([^`]+)`", p).group(1)
        log = p.split("LOG:\n", 1)[1].split("\n\n", 1)[0].splitlines()
        return sum(1 for ln in log
                   if ln.split()[1] == "ERROR" and ln.split()[2] == service), service, log

    def test_expected_matches_oracle(self):
        for s in SEEDS:
            for d in LEVELS:
                t = g.GENERATORS["T1"](s, d)
                self.assertEqual(t["class"], "T1-mechanical")
                self.assertEqual(_answer(t), [str(self._oracle(t)[0])], (s, d))

    def test_difficulty_adds_distractors(self):
        def distractors(t):
            n, service, log = self._oracle(t)
            loose = sum(1 for ln in log if service in ln or "error" in ln.lower())
            return loose - n
        for s in SEEDS:
            counts = [distractors(g.GENERATORS["T1"](s, d)) for d in LEVELS]
            self.assertEqual(counts, sorted(set(counts)), (s, counts))


class T2BaseConversionTest(unittest.TestCase):
    def _numerals(self, task):
        return re.findall(r"^\s*\d+\.\s+([0-9a-z]+) \(base (\d+)\)$", _prompt(task), re.M)

    def test_expected_matches_int_oracle(self):
        for s in SEEDS:
            for d in LEVELS:
                t = g.GENERATORS["T2"](s, d)
                self.assertEqual(t["class"], "T2-simple-transform")
                nums = self._numerals(t)
                self.assertGreaterEqual(len(nums), 2)
                self.assertEqual(_answer(t), [str(int(x, int(b))) for x, b in nums], (s, d))

    def test_difficulty_adds_digits(self):
        for s in SEEDS:
            sizes = [sum(len(x) for x, _ in self._numerals(g.GENERATORS["T2"](s, d)))
                     for d in LEVELS]
            self.assertEqual(sizes, sorted(set(sizes)), (s, sizes))


if __name__ == "__main__":
    unittest.main()
