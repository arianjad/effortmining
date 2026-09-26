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

import argparse
import json
import os
import random
import sys

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


# --------------------------------------------------------------------------- #
# T2: base conversion                                                          #
# --------------------------------------------------------------------------- #
_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"
_BASES = [2, 3, 5, 7, 8, 12, 16, 20, 36]


def gen_t2_base_conversion(seed: int, difficulty: int = 1) -> dict:
    rng = random.Random(f"T2|{seed}|{difficulty}")
    d = difficulty
    length = 2 + d  # digits per numeral: the difficulty knob
    items, values = [], []
    for _ in range(3):
        b = rng.choice(_BASES)
        digits = [rng.randrange(1, b)] + [rng.randrange(b) for _ in range(length - 1)]
        value = 0
        for x in digits:
            value = value * b + x
        items.append(("".join(_DIGITS[x] for x in digits), b))
        values.append(str(value))
    prompt = [
        "Convert each numeral below to base 10. Digits above 9 are the letters a..z",
        "(a = 10, b = 11, ..., z = 35).",
        "",
        *[f"  {i}. {s} (base {b})" for i, (s, b) in enumerate(items, 1)],
        "",
        "Output one base-10 integer per line, in the same order, with no other text.",
        ANSWER_TAIL.format(what="result lines"),
    ]
    return _task("T2", "T2-simple-transform", seed, d, "Convert numerals to base 10",
                 prompt, values, 600,
                 f"Positional-notation transform of three {length}-digit numerals in mixed "
                 "bases; digit count grows with difficulty.")


# --------------------------------------------------------------------------- #
# T3: program tracing (the T3c stack machine, extended with swap and multiply) #
# --------------------------------------------------------------------------- #
_T3_PROGRAM = [
    "def process(seq):",
    "    stack = []",
    "    for x in seq:",
    "        if x == 'D' and stack:",
    "            stack.pop()",
    "        elif x == 'X' and stack:",
    "            stack[-1] += 1",
    "        elif x == 'S' and len(stack) >= 2:",
    "            stack[-1], stack[-2] = stack[-2], stack[-1]",
    "        elif x == 'M' and len(stack) >= 2:",
    "            stack.append(stack.pop() * stack.pop())",
    "        else:",
    "            stack.append(1)",
    "    return sum((i + 1) * v for i, v in enumerate(stack))",
]


def _t3_run(seq: str) -> int:
    stack = []
    for x in seq:
        if x == "D" and stack:
            stack.pop()
        elif x == "X" and stack:
            stack[-1] += 1
        elif x == "S" and len(stack) >= 2:
            stack[-1], stack[-2] = stack[-2], stack[-1]
        elif x == "M" and len(stack) >= 2:
            stack.append(stack.pop() * stack.pop())
        else:
            stack.append(1)
    return sum((i + 1) * v for i, v in enumerate(stack))


def gen_t3_program_tracing(seed: int, difficulty: int = 1) -> dict:
    rng = random.Random(f"T3|{seed}|{difficulty}")
    d = difficulty
    seq = "".join(rng.choice("AABDXXSM") for _ in range(4 + 4 * d))
    prompt = [
        "The Python program below processes a string of opcodes with a list used as a",
        "stack. Determine exactly what it prints.",
        "",
        *["    " + ln for ln in _T3_PROGRAM],
        "",
        f"    print(process('{seq}'))",
        "",
        "Trace the execution by hand and give the printed value.",
        "",
        ANSWER_TAIL.format(what="printed value"),
    ]
    return _task("T3", "T3-moderate-reasoning", seed, d, "Trace an extended stack-machine program",
                 prompt, [str(_t3_run(seq))], 600 + 150 * d,
                 f"State tracking over {len(seq)} opcodes with guarded pop/increment/swap/"
                 "multiply branches and a position-weighted sum; one slip changes the integer.")


# --------------------------------------------------------------------------- #
# T4: constrained counting (T4b's no-long-run count plus a forbidden word)     #
# --------------------------------------------------------------------------- #
_T4_SHAPE = {1: (2, 7), 2: (2, 9), 3: (3, 7), 4: (3, 8), 5: (3, 10)}  # d -> (k, n)
_T4_RUN = 3


def _t4_count(n: int, alphabet: list, r: int, w: str) -> int:
    """Suffix-state DP (not enumeration): keep the last max(r, |w|) - 1 chars."""
    keep = max(r, len(w)) - 1
    counts = {"": 1}
    for _ in range(n):
        nxt: dict = {}
        for suf, c in counts.items():
            for ch in alphabet:
                s = suf + ch
                if s.endswith(ch * r) or s.endswith(w):
                    continue
                nxt[s[-keep:]] = nxt.get(s[-keep:], 0) + c
        counts = nxt
    return sum(counts.values())


def gen_t4_constrained_counting(seed: int, difficulty: int = 1) -> dict:
    rng = random.Random(f"T4|{seed}|{difficulty}")
    d = difficulty
    k, n = _T4_SHAPE[d]
    alphabet = sorted(rng.sample("ABCDEFGHKMNPRSTUVWXYZ", k))
    while True:
        w = "".join(rng.choice(alphabet) for _ in range(3))
        if len(set(w)) > 1:  # an all-same word would duplicate the run rule
            break
    prompt = [
        f"Consider strings of length {n} over the alphabet {{{', '.join(alphabet)}}}.",
        "",
        f"Count how many such strings satisfy BOTH conditions:",
        f"  1. no run of {_T4_RUN} or more identical characters in a row appears anywhere;",
        f"  2. the substring '{w}' does not appear anywhere.",
        "",
        "Work out the exact count.",
        "",
        ANSWER_TAIL.format(what="single integer"),
    ]
    return _task("T4", "T4-hard-reasoning", seed, d, "Count strings avoiding long runs and a word",
                 prompt, [str(_t4_count(n, alphabet, _T4_RUN, w))], 900 + 300 * d,
                 f"{k}^{n} = {k ** n} strings: too many to list by hand, so it needs a "
                 "suffix-state recurrence that tracks runs and partial matches of the word.")


# --------------------------------------------------------------------------- #
# RH: multi-hop variable tracing across provided documents                     #
# Class R-research, exact-checked like the shipped R1/R4-R6: grading dispatches  #
# on checker type, so the label does not route it to the blind grader.          #
# --------------------------------------------------------------------------- #
_WORDS = ["ALPHA", "BRAVO", "CEDAR", "DELTA", "EMBER", "FJORD", "GAMMA", "HELIX",
          "IONIC", "JUNO", "KAPPA", "LUMEN", "MAPLE", "NOVA", "ORBIT", "PRISM"]


def gen_rh_multihop(seed: int, difficulty: int = 1) -> dict:
    rng = random.Random(f"RH|{seed}|{difficulty}")
    d = difficulty
    hops = 2 + d
    names = rng.sample(_WORDS, hops + 1)
    value = rng.randint(20, 60)
    values = {names[0]: value}
    defs = {names[0]: str(value)}
    for prev, name in zip(names, names[1:]):
        op = rng.choice("+-*" if value <= 200 else "+-")
        c = rng.randint(2, 3) if op == "*" else rng.randint(2, 9)
        value = value + c if op == "+" else value - c if op == "-" else value * c
        values[name], defs[name] = value, f"{prev} {op} {c}"
    docs = [f"Document status: AUTHORITATIVE\nDefinitions:\n  {n} = {defs[n]}\n"
            f"  {n}_MIN = {rng.randint(1, 9)}" for n in names]
    # Superseded drafts pin a chain name to a stale literal != its true value; every
    # op downstream is injective, so following any draft changes the final answer.
    for _ in range(d):
        n = rng.choice(names)
        stale = values[n] + rng.choice([-5, -4, -3, -2, -1, 1, 2, 3, 4, 5])
        docs.append(f"Document status: SUPERSEDED DRAFT (do not use)\nDefinitions:\n"
                    f"  {n} = {stale}")
    rng.shuffle(docs)
    documents = [{"title": f"config note {i}", "content": c} for i, c in enumerate(docs, 1)]
    target = names[-1]
    prompt = [
        f"You have been given {len(documents)} configuration notes (prepended above). Each",
        "note begins with a status line. Notes marked AUTHORITATIVE are current; notes",
        "marked SUPERSEDED are stale drafts and must be ignored. Each definition has the",
        "form NAME = expression, where an expression is an integer, or another NAME",
        "combined with an integer by +, - or *.",
        "",
        f"Using only the AUTHORITATIVE definitions, compute the value of {target}.",
        "",
        "Output exactly one line of the form:",
        "VALUE: <integer>",
        "",
        ANSWER_TAIL.format(what="line"),
    ]
    return _task("RH", "R-research", seed, d, "Trace a variable through multi-hop definitions",
                 prompt, [f"VALUE: {values[target]}"], 800 + 200 * d,
                 f"{hops} hops across separate notes with {d} superseded draft(s) that "
                 "redefine chain variables; following any draft changes the answer.",
                 documents=documents)


GENERATORS = {
    "T1": gen_t1_counting,
    "T2": gen_t2_base_conversion,
    "T3": gen_t3_program_tracing,
    "T4": gen_t4_constrained_counting,
    "RH": gen_rh_multihop,
}


def write_task_set(out_dir: str, seed: int = 1, n: int = 1, difficulty: int = 1,
                   keys=None) -> list[str]:
    """Write n tasks per generator (seeds seed..seed+n-1) as <id>.json into out_dir,
    a directory `effort.py --tasks-dir` can run. Returns the written paths."""
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for key in keys or GENERATORS:
        for s in range(seed, seed + n):
            t = GENERATORS[key](s, difficulty)
            path = os.path.join(out_dir, t["id"] + ".json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(t, f, indent=2)
                f.write("\n")
            paths.append(path)
    return paths


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="write a generated task set for --tasks-dir")
    p.add_argument("out_dir")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--n", type=int, default=1, help="tasks per generator")
    p.add_argument("--difficulty", type=int, default=1, choices=range(1, 6))
    p.add_argument("--only", default=None, help=f"comma-separated subset of {list(GENERATORS)}")
    a = p.parse_args(argv)
    keys = a.only.split(",") if a.only else None
    paths = write_task_set(a.out_dir, a.seed, a.n, a.difficulty, keys)
    print(f"[generators] wrote {len(paths)} task(s) to {a.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
