#!/usr/bin/env python3
"""Tests for bench/generators.py: seeded procedural task generators.

Every expected answer is checked against an oracle written here, independent of the
generator's own computation: a re-parse of the prompt (T1), int(s, b) (T2), running
the printed program in a subprocess (T3), brute-force enumeration (T4), and a
multi-pass evaluator over the authoritative definitions (multi-hop).
"""
import itertools
import os
import re
import subprocess
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


class T3ProgramTracingTest(unittest.TestCase):
    def _program(self, task):
        lines = [ln[4:] for ln in task["prompt"] if ln.startswith("    ")]
        return "\n".join(lines) + "\n"

    def test_expected_matches_subprocess_execution(self):
        for s in range(1, 9):
            for d in LEVELS:
                t = g.GENERATORS["T3"](s, d)
                self.assertEqual(t["class"], "T3-moderate-reasoning")
                code = self._program(t)
                self.assertIn("print(process(", code)
                out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                     text=True, timeout=30)
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertEqual(_answer(t), [out.stdout.strip()], (s, d))

    def test_difficulty_lengthens_the_opcode_string(self):
        def length(t):
            return len(re.search(r"print\(process\('([A-Z]+)'\)\)", self._program(t)).group(1))
        for s in SEEDS:
            sizes = [length(g.GENERATORS["T3"](s, d)) for d in LEVELS]
            self.assertEqual(sizes, sorted(set(sizes)), (s, sizes))


class T4ConstrainedCountingTest(unittest.TestCase):
    def _params(self, task):
        p = _prompt(task)
        n = int(re.search(r"strings of length (\d+)", p).group(1))
        alphabet = re.search(r"alphabet \{([^}]*)\}", p).group(1).split(", ")
        r = int(re.search(r"run of (\d+) or more", p).group(1))
        w = re.search(r"substring '([^']+)'", p).group(1)
        return n, alphabet, r, w

    def test_expected_matches_brute_force(self):
        for s in SEEDS:
            for d in LEVELS:
                t = g.GENERATORS["T4"](s, d)
                self.assertEqual(t["class"], "T4-hard-reasoning")
                n, alphabet, r, w = self._params(t)
                run = re.compile(r"(.)\1{%d}" % (r - 1))
                count = sum(1 for tup in itertools.product(alphabet, repeat=n)
                            for st in ["".join(tup)]
                            if not run.search(st) and w not in st)
                self.assertEqual(_answer(t), [str(count)], (s, d))

    def test_difficulty_grows_search_space(self):
        for s in SEEDS:
            sizes = []
            for d in LEVELS:
                n, alphabet, _, _ = self._params(g.GENERATORS["T4"](s, d))
                sizes.append(len(alphabet) ** n)
            self.assertEqual(sizes, sorted(set(sizes)), (s, sizes))


if __name__ == "__main__":
    unittest.main()
