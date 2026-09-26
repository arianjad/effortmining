#!/usr/bin/env python3
"""generators.py — seeded procedural task generators for effortmining (stdlib only).

Each generator is `gen(seed, difficulty=1) -> task dict` in the bench/tasks JSON shape
(exact checker, <answer> sentinel tags). Same seed -> identical task; the difficulty
knob (1..5) strictly grows a structural measure (distractors, digits, program length,
search space, hops). Write a set for `effort.py --tasks-dir`:

    python bench/generators.py OUT_DIR [--seed 1] [--n 3] [--difficulty 2]

Difficulty is structural only; it is not tuned against real runs (that is a pilot).
"""
from __future__ import annotations

import random

EXACT_CANON = "strip_outer_ws;rstrip_each_line"
ANSWER_TAIL = "Output ONLY the {what} between <answer> and </answer> tags."


def _task(key, cls, seed, d, title, prompt, expected, max_out, rationale, documents=None):
    t = {"id": f"G{key}-{seed}-d{d}", "class": cls, "title": title, "prompt": prompt}
    if documents:
        t["documents"] = documents
    t.update({
        "answer_convention": "sentinel-tags",
        "checker": {"type": "exact", "expected": expected, "canonicalize": EXACT_CANON},
        "max_output_tokens": max_out,
        "difficulty_rationale": rationale,
        "generator": {"name": key, "seed": seed, "difficulty": d},
    })
    return t


# --------------------------------------------------------------------------- #
# T1: counting with distractors                                                #
# --------------------------------------------------------------------------- #
_SERVICES = ["billing-svc", "auth-svc", "ledger-svc", "search-svc", "notify-svc", "cart-svc"]
_CALM = ["request ok", "cache warm", "slow response", "user login ok", "retry scheduled",
         "config reloaded", "health check ok"]
_FAIL = ["charge failed code=5012", "write conflict code=4090", "timeout code=504",
         "bad token code=401"]


def gen_t1_counting(seed: int, difficulty: int = 1) -> dict:
    rng = random.Random(f"T1|{seed}|{difficulty}")
    d = difficulty
    target = rng.choice(_SERVICES)
    others = [s for s in _SERVICES if s != target]
    n_match = rng.randint(1, 2 + d)
    rows = [("ERROR", target, rng.choice(_FAIL)) for _ in range(n_match)]
    # Distractors: each contains the target service name or the word error but is
    # not a match. 2d or 2d+1 of them, so the count strictly grows with d.
    kinds = [
        lambda: ("ERROR", rng.choice(others), rng.choice(_FAIL)),
        lambda: ("ERROR", target + "-canary", rng.choice(_FAIL)),
        lambda: ("WARN", target, "upstream reported ERROR, retrying"),
        lambda: ("error", target, rng.choice(_FAIL)),
        lambda: ("INFO", target, rng.choice(_CALM)),
    ]
    rows += [rng.choice(kinds)() for _ in range(2 * d + rng.randint(0, 1))]
    rows += [(rng.choice(["INFO", "WARN", "DEBUG"]), rng.choice(others), rng.choice(_CALM))
             for _ in range(4 + 2 * d)]
    rng.shuffle(rows)
    log = [f"2026-03-01T08:{12 + i // 60:02d}:{i % 60:02d}Z {lvl:<5} {svc:<17} {msg}"
           for i, (lvl, svc, msg) in enumerate(rows)]
    prompt = [
        "You are given server log lines. Each line has the form:",
        "  <timestamp> <LEVEL> <service> <message>",
        "",
        f"Count the lines whose level is exactly ERROR (uppercase) and whose service is exactly `{target}`.",
        "The service must match the whole third token; the level must match the whole second token.",
        "",
        "LOG:",
        *log,
        "",
        ANSWER_TAIL.format(what="count, as a single integer,"),
    ]
    return _task("T1", "T1-mechanical", seed, d, "Count exact ERROR lines among distractors",
                 prompt, [str(n_match)], 300,
                 f"Mechanical filter-and-count over {len(log)} lines; near-miss distractors "
                 "(canary services, ERROR inside messages, lowercase levels) grow with difficulty.")


GENERATORS = {
    "T1": gen_t1_counting,
}
