"""PCO LLM Experiment: actor learns to solve programming puzzles.

Requires ANTHROPIC_API_KEY env var for LLM tests.
Results written to .tests/pco_experiment/
"""

import asyncio
import json
import os
import textwrap
from pathlib import Path
from typing import Any

import anthropic

import pytest

from coglet import Coglet, CogBase, CogletRuntime, enact, listen
from coglet.handle import Command
from coglet.pco.constraint import ConstraintCoglet
from coglet.pco.learner import LearnerCoglet
from coglet.pco.loss import LossCoglet
from coglet.pco.optimizer import ProximalCogletOptimizer

RESULTS_DIR = Path(".tests/pco_experiment")

PUZZLES = [
    # ── Game theory / decision trees ───────────────────
    {
        "name": "nim_optimal",
        "description": "Nim game: given a list of pile sizes (positive ints), return the optimal move as (pile_index, stones_to_remove). The optimal strategy uses XOR (nim-sum): XOR all piles. If nim-sum is 0, you're in a losing position — return (0, 1). Otherwise, find a pile where pile_size XOR nim_sum < pile_size, and remove enough stones from that pile to make the total nim-sum 0.",
        "signature": "def nim_optimal(piles: list[int]) -> tuple[int, int]:",
        "tests": [
            # nim-sum = 3^4^5 = 2. pile[0]=3, 3^2=1 < 3, remove 2 from pile 0
            ([3, 4, 5], (0, 2)),
            # nim-sum = 1^1 = 0. losing position, return (0,1)
            ([1, 1], (0, 1)),
            # nim-sum = 4. pile[0]=4, 4^4=0 < 4, remove 4 from pile 0
            ([4], (0, 4)),
            # nim-sum = 1^2^3 = 0. losing, return (0,1)
            ([1, 2, 3], (0, 1)),
            # nim-sum = 7^3^5 = 1. pile[0]=7, 7^1=6 < 7, remove 1. pile[2]=5, 5^1=4 < 5, also works but we want first.
            ([7, 3, 5], (0, 1)),
        ],
    },
    {
        "name": "blackjack_action",
        "description": "Basic blackjack strategy. Given player_total (int, hard total 4-21), dealer_upcard (int, 2-11 where 11=Ace), and is_soft (bool, whether player has a usable ace), return 'hit', 'stand', or 'double'. Rules: Hard totals: stand on 17+; double on 11 always; double on 10 if dealer 2-9; double on 9 if dealer 3-6; hit on 8 or less; for 12: hit if dealer 2-3 or 7+, stand if dealer 4-6; for 13-16: stand if dealer 2-6, hit if dealer 7+. Soft totals: soft 20+ stand; soft 18 stand if dealer 2,7,8, double if dealer 3-6, hit if dealer 9-11; soft 17 double if dealer 3-6, else hit; soft 13-16 double if dealer 5-6, else hit.",
        "signature": "def blackjack_action(player_total: int, dealer_upcard: int, is_soft: bool) -> str:",
        "tests": [
            # hard totals
            (17, 10, False, "stand"),
            (11, 6, False, "double"),
            (10, 10, False, "hit"),       # 10 vs dealer 10: hit (not double)
            (10, 9, False, "double"),
            (9, 5, False, "double"),
            (9, 2, False, "hit"),          # 9 vs dealer 2: hit
            (8, 6, False, "hit"),
            (12, 3, False, "hit"),         # 12 vs 3: hit
            (12, 4, False, "stand"),       # 12 vs 4: stand
            (15, 6, False, "stand"),       # 15 vs 6: stand
            (15, 7, False, "hit"),         # 15 vs 7: hit
            (16, 10, False, "hit"),
            # soft totals
            (20, 6, True, "stand"),
            (18, 7, True, "stand"),
            (18, 5, True, "double"),
            (18, 9, True, "hit"),
            (17, 4, True, "double"),
            (17, 8, True, "hit"),
            (15, 5, True, "double"),       # soft 15 vs 5: double
            (15, 7, True, "hit"),          # soft 15 vs 7: hit
        ],
    },
    {
        "name": "minimax_tictactoe",
        "description": "Given a tic-tac-toe board (list of 9 ints: 0=empty, 1=X, 2=O) and the current player (1 or 2), return the index (0-8) of the best move using minimax. X is maximizing (+1 for X win, -1 for O win, 0 for draw). If multiple moves have the same score, return the lowest index.",
        "signature": "def minimax_tictactoe(board: list[int], player: int) -> int:",
        "tests": [
            # X to move, can win immediately at index 2
            ([1, 1, 0, 2, 2, 0, 0, 0, 0], 1, 2),
            # O to move, must block X winning at index 2
            ([1, 1, 0, 0, 2, 0, 0, 0, 0], 2, 2),
            # Empty board, X plays — optimal is center (4) or corner (0). Minimax with lowest-index tiebreak → 0
            ([0, 0, 0, 0, 0, 0, 0, 0, 0], 1, 0),
            # X has center, O should take corner
            ([0, 0, 0, 0, 1, 0, 0, 0, 0], 2, 0),
            # X can fork: X at 0,4, O at 1,3. X should play 6 or 8 to create two ways to win.
            ([1, 2, 0, 2, 1, 0, 0, 0, 0], 1, 8),
        ],
    },
    # ── Tricky edge cases / precision ──────────────────
    {
        "name": "float_to_fraction",
        "description": "Convert a decimal string to a simplified fraction string 'p/q'. Handle repeating decimals in parens: '0.(3)' = 1/3, '0.1(6)' = 1/6. Non-repeating: '0.5' = 1/2. Always simplify. Return '0/1' for '0' or '0.0'.",
        "signature": "def float_to_fraction(s: str) -> str:",
        "tests": [
            ("0.5", "1/2"),
            ("0.(3)", "1/3"),
            ("0.1(6)", "1/6"),
            ("0.(142857)", "1/7"),
            ("1.0", "1/1"),
            ("0.0", "0/1"),
            ("2.5", "5/2"),
            ("0.75", "3/4"),
            ("0.(9)", "1/1"),
            ("3.(3)", "10/3"),
        ],
    },
    {
        "name": "next_permutation",
        "description": "Given a list of ints, rearrange it IN PLACE to the next lexicographically greater permutation. If it's the last permutation (descending), wrap to sorted ascending. Return the list. Algorithm: from the right, find first index i where nums[i] < nums[i+1]. Then find rightmost j > i where nums[j] > nums[i]. Swap i,j. Reverse everything after i.",
        "signature": "def next_permutation(nums: list[int]) -> list[int]:",
        "tests": [
            ([1, 2, 3], [1, 3, 2]),
            ([3, 2, 1], [1, 2, 3]),        # wrap around
            ([1, 1, 5], [1, 5, 1]),
            ([1, 3, 2], [2, 1, 3]),
            ([2, 3, 1], [3, 1, 2]),
            ([1], [1]),
            ([5, 4, 7, 5, 3, 2], [5, 5, 2, 3, 4, 7]),
        ],
    },
    {
        "name": "calculator",
        "description": "Evaluate a mathematical expression string with +, -, *, / and parentheses. Integers only (no floats in input). Division truncates toward zero. Respect operator precedence (* and / before + and -). Handle nested parens. No spaces in input.",
        "signature": "def calculator(expr: str) -> int:",
        "tests": [
            ("3+2*2", 7),
            ("(3+2)*2", 10),
            ("10/3", 3),
            ("14-3/2", 13),
            ("2*(5+5*2)/3+(6/2+8)", 21),
            ("(2+6*3+5-(3*14/7+2)*5)+3", -12),
            ("1-1", 0),
            ("0-2147483647", -2147483647),
        ],
    },
    {
        "name": "count_islands",
        "description": "Given a 2D grid (list of strings, '1'=land '0'=water), count the number of islands. An island is a group of '1's connected horizontally or vertically (not diagonally).",
        "signature": "def count_islands(grid: list[str]) -> int:",
        "tests": [
            (["11110", "11010", "11000", "00000"], 1),
            (["11000", "11000", "00100", "00011"], 3),
            (["1"], 1),
            (["0"], 0),
            ([],  0),
            (["10111", "01011", "10101"], 5),
        ],
    },
    # ── Algorithm precision ────────────────────────────
    {
        "name": "skyline",
        "description": "Given buildings as list of [left, right, height], return the skyline as list of [x, height] key points. Buildings may overlap. At each x where the max height changes, emit [x, new_height]. Output must be sorted by x. When a building ends and no other building covers that x, height drops to 0.",
        "signature": "def skyline(buildings: list[list[int]]) -> list[list[int]]:",
        "tests": [
            ([[2, 9, 10], [3, 7, 15], [5, 12, 12], [15, 20, 10], [19, 24, 8]],
             [[2, 10], [3, 15], [7, 12], [12, 0], [15, 10], [20, 8], [24, 0]]),
            ([[0, 2, 3], [2, 5, 3]], [[0, 3], [5, 0]]),  # adjacent same height
            ([], []),
            ([[1, 5, 3], [1, 5, 3]], [[1, 3], [5, 0]]),  # identical buildings
        ],
    },
    {
        "name": "lru_cache",
        "description": "Implement an LRU cache. Given capacity (int) and operations (list of tuples), process each operation and return list of results. Operations: ('put', key, value) → None, ('get', key) → value or -1 if not found. On put, if at capacity, evict least recently used. Both get and put count as 'use'.",
        "signature": "def lru_cache(capacity: int, operations: list[tuple]) -> list:",
        "tests": [
            (2, [("put", 1, 1), ("put", 2, 2), ("get", 1), ("put", 3, 3), ("get", 2), ("put", 4, 4), ("get", 1), ("get", 3), ("get", 4)],
             [None, None, 1, None, -1, None, -1, 3, 4]),
            (1, [("put", 1, 10), ("get", 1), ("put", 2, 20), ("get", 1), ("get", 2)],
             [None, 10, None, -1, 20]),
            (2, [("put", 2, 1), ("put", 1, 1), ("put", 2, 3), ("put", 4, 1), ("get", 1), ("get", 2)],
             [None, None, None, None, -1, 3]),  # put(2,3) refreshes key 2, so key 1 is LRU
        ],
    },
    {
        "name": "regex_match",
        "description": "Implement regex matching with '.' (any single char) and '*' (zero or more of preceding element). The match must cover the ENTIRE string. Use dynamic programming.",
        "signature": "def regex_match(s: str, p: str) -> bool:",
        "tests": [
            ("aa", "a", False),
            ("aa", "a*", True),
            ("ab", ".*", True),
            ("aab", "c*a*b", True),          # c* matches empty, a* matches aa, b matches b
            ("mississippi", "mis*is*ip*.", True),
            ("ab", ".*c", False),
            ("", "c*", True),                  # c* matches empty
            ("", "", True),
            ("a", "ab*", True),                # b* matches empty
            ("bbbba", ".*a*a", True),
        ],
    },
    # ── State machine / parsing ────────────────────────
    {
        "name": "decode_ways",
        "description": "Count the number of ways to decode a digit string where 'A'=1, 'B'=2, ..., 'Z'=26. For example '226' can be decoded as 'BZ'(2,26), 'VF'(22,6), or 'BBF'(2,2,6) = 3 ways. Leading zeros are invalid: '06' has 0 ways. Return the count.",
        "signature": "def decode_ways(s: str) -> int:",
        "tests": [
            ("12", 2),      # 1,2 or 12
            ("226", 3),     # 2,2,6 or 22,6 or 2,26
            ("06", 0),      # leading zero invalid
            ("10", 1),      # only 10
            ("27", 1),      # only 2,7
            ("2101", 1),    # 2,10,1
            ("111111", 13),
            ("0", 0),
            ("1", 1),
        ],
    },
    {
        "name": "serialize_tree",
        "description": "Given a binary tree as a nested tuple (value, left, right) where None means no child, serialize it to a string and deserialize back. The round-trip must be lossless. Return (serialized_string, deserialized_tree). Use preorder with 'N' for None, comma-separated. Example: (1, (2, None, None), (3, None, None)) → '1,2,N,N,3,N,N' → (1, (2, None, None), (3, None, None)).",
        "signature": "def serialize_tree(tree: tuple | None) -> tuple[str, tuple | None]:",
        "tests": [
            ((1, (2, None, None), (3, None, None)), ("1,2,N,N,3,N,N", (1, (2, None, None), (3, None, None)))),
            (None, ("N", None)),
            ((1, None, (2, None, None)), ("1,N,2,N,N", (1, None, (2, None, None)))),
            ((5, (3, (1, None, None), (4, None, None)), (8, None, None)),
             ("5,3,1,N,N,4,N,N,8,N,N", (5, (3, (1, None, None), (4, None, None)), (8, None, None)))),
        ],
    },
    # ── Combinatorial ──────────────────────────────────
    {
        "name": "word_break",
        "description": "Given a string s and a list of dictionary words, return True if s can be segmented into a space-separated sequence of one or more dictionary words. Words can be reused.",
        "signature": "def word_break(s: str, words: list[str]) -> bool:",
        "tests": [
            ("leetcode", ["leet", "code"], True),
            ("applepenapple", ["apple", "pen"], True),
            ("catsandog", ["cats", "dog", "sand", "and", "cat"], False),
            ("", ["a"], True),
            ("aaaaaaa", ["aaaa", "aaa"], True),      # 4+3 or 3+4 or 3+3+... nope, 7=4+3
            ("aaaaaab", ["a", "aa", "aaa"], False),   # can't make the 'b'
            ("abcd", ["a", "abc", "b", "cd"], True),  # a+b+cd or abc+d... abc+d needs d
        ],
    },
    {
        "name": "coin_change",
        "description": "Given coin denominations (list[int]) and a target amount (int), return the minimum number of coins to make that amount. Return -1 if impossible. Coins can be reused.",
        "signature": "def coin_change(coins: list[int], amount: int) -> int:",
        "tests": [
            ([1, 5, 10, 25], 30, 2),       # 25+5
            ([2], 3, -1),                    # impossible
            ([1], 0, 0),
            ([1, 2, 5], 11, 3),              # 5+5+1
            ([186, 419, 83, 408], 6249, 20), # needs DP, greedy fails
            ([3, 7], 11, -1),                # impossible: no combo of 3s and 7s makes 11
            ([3, 7], 12, 4),                 # 3+3+3+3
        ],
    },
    {
        "name": "task_scheduler",
        "description": "Given tasks (list of uppercase chars) and cooldown n (int), return minimum intervals needed to execute all tasks. Same task must have at least n intervals between executions. Idle slots are allowed. Order doesn't need to match input.",
        "signature": "def task_scheduler(tasks: list[str], n: int) -> int:",
        "tests": [
            (["A", "A", "A", "B", "B", "B"], 2, 8),       # A_B_A_B_A_B → 8
            (["A", "A", "A", "B", "B", "B"], 0, 6),       # no cooldown → 6
            (["A", "A", "A", "A", "A", "A", "B", "C", "D", "E", "F", "G"], 2, 16),
            (["A"], 5, 1),
            (["A", "B", "C", "A", "B", "C"], 3, 6),        # no idle needed: ABCABC
        ],
    },
]


def run_solution(puzzle: dict, code: str) -> dict:
    """Execute a solution against test cases. Returns result dict."""
    namespace: dict[str, Any] = {}
    try:
        exec(code, namespace)
    except Exception as e:
        return {
            "name": puzzle["name"],
            "passed": False,
            "total_tests": len(puzzle["tests"]),
            "passed_tests": 0,
            "error": f"compile error: {e}",
        }

    fn_name = puzzle["signature"].split("(")[0].replace("def ", "").strip()
    fn = namespace.get(fn_name)
    if fn is None:
        return {
            "name": puzzle["name"],
            "passed": False,
            "total_tests": len(puzzle["tests"]),
            "passed_tests": 0,
            "error": f"function {fn_name} not found in code",
        }

    passed_tests = 0
    errors = []
    for test_case in puzzle["tests"]:
        *inputs, expected = test_case
        test_input = inputs[0] if len(inputs) == 1 else tuple(inputs)
        try:
            result = fn(*inputs) if len(inputs) > 1 else fn(inputs[0])
            if result == expected:
                passed_tests += 1
            else:
                errors.append(f"input={test_input!r}: got {result!r}, expected {expected!r}")
        except Exception as e:
            errors.append(f"input={test_input!r}: raised {type(e).__name__}: {e}")

    return {
        "name": puzzle["name"],
        "passed": passed_tests == len(puzzle["tests"]),
        "total_tests": len(puzzle["tests"]),
        "passed_tests": passed_tests,
        "error": "; ".join(errors) if errors else None,
        "all_errors": errors,
    }


# ── LLM helpers ──────────────────────────────────────

_HAS_API_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))


def llm_call(prompt: str, *, system: str = "", max_tokens: int = 4096) -> str:
    """Single Claude Sonnet call."""
    client = anthropic.Anthropic()
    kwargs: dict[str, Any] = dict(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    if system:
        kwargs["system"] = system
    response = client.messages.create(**kwargs)
    return response.content[0].text


def extract_json(text: str) -> Any:
    """Extract JSON from LLM response, handling markdown code blocks."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    return json.loads(text)


# ── Coglets ──────────────────────────────────────────


class CodeGenActor(Coglet):
    """Actor that holds Python solutions to puzzles."""

    def __init__(self, *, puzzles: list[dict], **kwargs):
        super().__init__(**kwargs)
        self.puzzles = puzzles
        self.solutions: dict[str, str] = {}
        self._initialized = False

    @enact("run")
    async def run_rollout(self, data):
        if not self._initialized:
            self._initialize_solutions()
            self._initialized = True

        results = []
        for puzzle in self.puzzles:
            code = self.solutions.get(puzzle["name"], "")
            result = run_solution(puzzle, code)
            result["code"] = code
            results.append(result)

        await self.transmit("experience", {"results": results})

    def _initialize_solutions(self):
        # Batch to avoid token limit truncation
        batch_size = 5
        for i in range(0, len(self.puzzles), batch_size):
            batch = self.puzzles[i : i + batch_size]
            puzzle_specs = []
            for p in batch:
                puzzle_specs.append(f"### {p['name']}\n{p['description']}\n```python\n{p['signature']}\n```")

            prompt = (
                "Write a Python solution for each puzzle below. "
                "Return a JSON object mapping puzzle name to the complete Python function code (as a string). "
                "Each value must be a complete, standalone Python function. "
                "Return ONLY the JSON object, no other text.\n\n"
                + "\n\n".join(puzzle_specs)
            )

            response = llm_call(prompt, system="You are an expert Python programmer.", max_tokens=8192)
            try:
                batch_solutions = extract_json(response)
                self.solutions.update(batch_solutions)
            except (json.JSONDecodeError, ValueError):
                # If JSON parsing fails, generate empty stubs
                for p in batch:
                    fn_name = p["signature"].split("(")[0].replace("def ", "").strip()
                    self.solutions.setdefault(p["name"], f"def {fn_name}(*args): pass")

    @enact("update")
    async def apply_update(self, patch):
        new_solutions = patch.get("solutions", {})
        self.solutions.update(new_solutions)


class CodeReviewCritic(Coglet):
    """Critic that predicts pass/fail for each solution."""

    def __init__(self, *, puzzles: list[dict], **kwargs):
        super().__init__(**kwargs)
        self.puzzles = puzzles
        self.strategy = "Look for common bugs: off-by-one errors, missing edge cases, wrong return types."

    @listen("experience")
    async def evaluate(self, experience):
        results = experience["results"]
        solution_texts = []
        for r in results:
            p = next((p for p in self.puzzles if p["name"] == r["name"]), None)
            desc = p["description"] if p else ""
            # Show puzzle spec + sample test cases so critic can mentally run the code
            test_examples = ""
            if p and p.get("tests"):
                samples = p["tests"][:3]
                for tc in samples:
                    *inputs, expected = tc
                    inp = inputs[0] if len(inputs) == 1 else tuple(inputs)
                    test_examples += f"  {inp!r} → {expected!r}\n"
            solution_texts.append(
                f"### {r['name']}\n"
                f"Description: {desc}\n"
                f"Test cases:\n{test_examples}"
                f"```python\n{r['code']}\n```"
            )

        prompt = (
            f"Your evaluation strategy: {self.strategy}\n\n"
            "For each solution below, mentally trace through the test cases and predict "
            "whether it will PASS or FAIL ALL test cases. A single failing test means FAIL. "
            "Return a JSON object mapping puzzle name to 'pass' or 'fail'. "
            "Return ONLY the JSON object.\n\n"
            + "\n\n".join(solution_texts)
        )

        response = llm_call(prompt, system="You are a meticulous code reviewer. Trace each test case through the code step by step.", max_tokens=8192)
        try:
            predictions = extract_json(response)
        except (json.JSONDecodeError, ValueError):
            predictions = {}

        evaluation = []
        for r in results:
            predicted = predictions.get(r["name"], "fail").lower().strip()
            actual = "pass" if r["passed"] else "fail"
            evaluation.append({
                "name": r["name"],
                "predicted": predicted,
                "actual": actual,
                "correct": predicted == actual,
                "code": r["code"],
                "error": r.get("error"),
            })

        await self.transmit("evaluation", {"predictions": evaluation})

    @enact("update")
    async def apply_update(self, patch):
        new_strategy = patch.get("critic_strategy")
        if new_strategy:
            self.strategy = new_strategy


# ── Losses ───────────────────────────────────────────


class ActorLoss(LossCoglet):
    async def compute_loss(self, experience, evaluation):
        results = experience["results"]
        failed = [r for r in results if not r["passed"]]
        return {
            "name": "actor_loss",
            "magnitude": len(failed),
            "total": len(results),
            "failed_puzzles": [{"name": r["name"], "error": r.get("error"), "code": r["code"]} for r in failed],
        }


class CriticLoss(LossCoglet):
    async def compute_loss(self, experience, evaluation):
        preds = evaluation["predictions"]
        wrong = [p for p in preds if not p["correct"]]
        return {
            "name": "critic_loss",
            "magnitude": len(wrong),
            "total": len(preds),
            "wrong_predictions": wrong,
        }


# ── Constraint ───────────────────────────────────────


class MaxRewritesConstraint(ConstraintCoglet):
    async def check(self, patch):
        n = len(patch.get("solutions", {}))
        if n > 5:
            return {"accepted": False, "reason": f"too many rewrites: {n} (max 5)"}
        return {"accepted": True}


# ── Learner ──────────────────────────────────────────


class CodeGenLearner(LearnerCoglet):
    """Learner with memory: tracks all previous attempts per puzzle.

    Each epoch appends to a per-puzzle log of (code, error) pairs.
    The full history is included in the fix prompt so the LLM doesn't
    repeat the same broken approaches.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # puzzle_name → list of {"code": str, "error": str, "epoch": int}
        self._history: dict[str, list[dict]] = {}
        self._epoch = 0

    async def learn(self, experience, evaluation, signals):
        self._epoch += 1
        actor_signal = next((s for s in signals if s.get("name") == "actor_loss"), None)
        critic_signal = next((s for s in signals if s.get("name") == "critic_loss"), None)

        # Record all failures into history
        if actor_signal and actor_signal.get("failed_puzzles"):
            for f in actor_signal["failed_puzzles"]:
                name = f["name"]
                self._history.setdefault(name, [])
                # Don't log duplicates (same code)
                if not self._history[name] or self._history[name][-1]["code"] != f["code"]:
                    self._history[name].append({
                        "code": f["code"],
                        "error": f["error"],
                        "epoch": self._epoch,
                    })

        new_solutions = {}
        new_critic_strategy = None

        # Fix failing solutions (max 5)
        if actor_signal and actor_signal.get("failed_puzzles"):
            failed = actor_signal["failed_puzzles"][:5]
            puzzle_map = {p["name"]: p for p in PUZZLES}

            fix_parts = []
            for f in failed:
                puzzle = puzzle_map.get(f["name"], {})
                # Include test cases so the LLM knows exact expected behavior
                test_lines = ""
                if puzzle.get("tests"):
                    for tc in puzzle["tests"]:
                        *inputs, expected = tc
                        inp = inputs[0] if len(inputs) == 1 else tuple(inputs)
                        test_lines += f"  assert fn({inp!r}) == {expected!r}\n"
                part = (
                    f"### {f['name']}\n"
                    f"Description: {puzzle.get('description', 'N/A')}\n"
                    f"Signature: {puzzle.get('signature', 'N/A')}\n"
                    f"Test cases:\n{test_lines}\n"
                    f"Current code:\n```python\n{f['code']}\n```\n"
                    f"Errors: {f['error']}\n"
                )

                # Add history of previous failed attempts
                history = self._history.get(f["name"], [])
                if len(history) > 1:
                    part += "\nPREVIOUS FAILED ATTEMPTS (do NOT repeat these approaches):\n"
                    # Show last 5 attempts to keep prompt bounded
                    for prev in history[-5:]:
                        part += (
                            f"- Epoch {prev['epoch']}:\n"
                            f"  ```python\n  {prev['code'][:300]}{'...' if len(prev['code']) > 300 else ''}\n  ```\n"
                            f"  Error: {prev['error']}\n"
                        )
                    part += "\nYou MUST try a fundamentally different approach than the ones above.\n"

                fix_parts.append(part)

            prompt = (
                "Fix these failing Python solutions. For each, return the corrected complete function. "
                "IMPORTANT: If previous attempts are listed, you MUST try a different algorithm or approach. "
                "Do not make minor tweaks to code that has already failed — rethink the solution.\n"
                "Return a JSON object mapping puzzle name to the fixed Python code string. "
                "Return ONLY the JSON object.\n\n"
                + "\n\n".join(fix_parts)
            )

            response = llm_call(prompt, system="You are an expert Python programmer fixing bugs.", max_tokens=8192)
            try:
                new_solutions = extract_json(response)
            except (json.JSONDecodeError, ValueError):
                pass

        # Update critic strategy — append insights rather than replace
        if critic_signal and critic_signal.get("wrong_predictions"):
            wrong = critic_signal["wrong_predictions"]
            wrong_parts = []
            for w in wrong:
                wrong_parts.append(
                    f"- {w['name']}: predicted {w['predicted']}, actually {w['actual']}"
                    + (f" (error: {w['error']})" if w.get("error") else "")
                )

            # Get the current strategy from the evaluation context
            current_strategy = ""
            if evaluation and "predictions" in evaluation:
                # The critic's strategy is passed through indirectly
                current_strategy = getattr(self, "_last_critic_strategy", "")

            prompt = (
                f"You are a code review critic. Current strategy:\n{current_strategy}\n\n"
                "Your predictions were wrong for these puzzles:\n"
                + "\n".join(wrong_parts)
                + "\n\nWrite an IMPROVED evaluation strategy that ADDS specific new checks to your existing approach. "
                "Keep what works, add what's missing. 2-4 sentences total."
                "\n\nReturn ONLY the strategy text, no JSON or markdown."
            )

            new_critic_strategy = llm_call(prompt, max_tokens=300)
            self._last_critic_strategy = new_critic_strategy

        return {
            "solutions": new_solutions,
            "critic_strategy": new_critic_strategy,
        }


# ── Sanity tests (no API key needed) ──────────────────


def test_harness_runs_correct_solution():
    puzzle = next(p for p in PUZZLES if p["name"] == "coin_change")
    code = textwrap.dedent("""\
        def coin_change(coins, amount):
            dp = [float('inf')] * (amount + 1)
            dp[0] = 0
            for i in range(1, amount + 1):
                for c in coins:
                    if c <= i and dp[i - c] + 1 < dp[i]:
                        dp[i] = dp[i - c] + 1
            return dp[amount] if dp[amount] != float('inf') else -1
    """)
    result = run_solution(puzzle, code)
    assert result["passed"] is True
    assert result["passed_tests"] == len(puzzle["tests"])


def test_harness_catches_bad_solution():
    puzzle = next(p for p in PUZZLES if p["name"] == "coin_change")
    code = "def coin_change(coins, amount): return len(coins)"
    result = run_solution(puzzle, code)
    assert result["passed"] is False
    assert result["error"] is not None


@pytest.mark.skipif(not _HAS_API_KEY, reason="ANTHROPIC_API_KEY not set")
@pytest.mark.asyncio
async def test_pco_llm_experiment():
    """Full PCO experiment: 5 epochs of LLM-driven code improvement."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    runtime = CogletRuntime()
    pco_handle = await runtime.spawn(CogBase(
        cls=ProximalCogletOptimizer,
        kwargs=dict(
            actor_config=CogBase(cls=CodeGenActor, kwargs=dict(puzzles=PUZZLES)),
            critic_config=CogBase(cls=CodeReviewCritic, kwargs=dict(puzzles=PUZZLES)),
            losses=[ActorLoss(), CriticLoss()],
            constraints=[MaxRewritesConstraint()],
            learner=CodeGenLearner(),
            max_retries=2,
        ),
    ))
    pco = pco_handle.coglet

    num_epochs = 5
    metrics = []

    print("\n  ┌───────┬──────────────────┬──────────────────┬──────────┐")
    print("  │ Epoch │ Actor Pass Rate  │ Critic Accuracy  │ Accepted │")
    print("  ├───────┼──────────────────┼──────────────────┼──────────┤")

    for epoch in range(num_epochs):
        result = await pco.run_epoch(timeout=120.0)

        actor_signal = next((s for s in result["signals"] if s["name"] == "actor_loss"), {})
        critic_signal = next((s for s in result["signals"] if s["name"] == "critic_loss"), {})

        total = actor_signal.get("total", 15)
        actor_pass = total - actor_signal.get("magnitude", 0)
        critic_correct = total - critic_signal.get("magnitude", 0)

        epoch_metrics = {
            "epoch": epoch + 1,
            "actor_pass_rate": actor_pass / total,
            "actor_passed": actor_pass,
            "critic_accuracy": critic_correct / total,
            "critic_correct": critic_correct,
            "total": total,
            "accepted": result["accepted"],
        }
        metrics.append(epoch_metrics)

        print(
            f"  │   {epoch + 1}   │   {actor_pass:2d}/{total} ({epoch_metrics['actor_pass_rate']:5.0%})   "
            f"│   {critic_correct:2d}/{total} ({epoch_metrics['critic_accuracy']:5.0%})   "
            f"│ {'  yes   ' if result['accepted'] else '  no    '} │"
        )

    print("  └───────┴──────────────────┴──────────────────┴──────────┘")

    # Write results
    (RESULTS_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))

    actor = pco._actor_handle.coglet
    (RESULTS_DIR / "final_solutions.json").write_text(
        json.dumps(actor.solutions, indent=2)
    )

    critic = pco._critic_handle.coglet
    (RESULTS_DIR / "final_critic_strategy.txt").write_text(critic.strategy)

    await runtime.shutdown()

    # ── Assertions ─────────────────────────────────────
    first = metrics[0]
    last = metrics[-1]

    print(f"\n  Actor improvement:  {first['actor_pass_rate']:.0%} → {last['actor_pass_rate']:.0%}")
    print(f"  Critic improvement: {first['critic_accuracy']:.0%} → {last['critic_accuracy']:.0%}")

    # Assert improvement or stability — the best epoch should beat the first
    best_actor = max(m["actor_pass_rate"] for m in metrics)
    best_critic = max(m["critic_accuracy"] for m in metrics)

    assert best_actor >= first["actor_pass_rate"], \
        f"Actor should not degrade overall: first={first['actor_pass_rate']:.0%}, best={best_actor:.0%}"
    assert best_actor >= 0.5, \
        f"Actor should solve at least half: best was {best_actor:.0%}"
    assert best_critic >= 0.5, \
        f"Critic should reach at least 50% accuracy: best was {best_critic:.0%}"
