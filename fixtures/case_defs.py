"""
Declarative definitions of the fixture cases used by generate_fixtures.py.

Each case is a linear sequence of commits applied to a throwaway git repo.
Every commit fully rewrites module.py and test_module.py to their state
after that commit (simplest way to express a commit sequence declaratively).
`bug_index` marks which commit (0-based, into `commits`) first introduces
the regression that the test suite detects -- this is the ground-truth
answer the eval harness checks against.

`good_index` is normally 0 (the very first commit); it's the commit git
bisect is told is "known good".
"""

from dataclasses import dataclass, field


@dataclass
class Commit:
    message: str
    module_py: str
    test_py: str


@dataclass
class Case:
    name: str
    difficulty: str  # "easy" | "medium" | "hard"
    description: str
    commits: list
    bug_index: int  # index into commits[] of the first commit where the test starts failing
    test_cmd: str = "python -m pytest -q test_module.py"
    good_index: int = 0
    notes: str = ""


TEST_ADD = '''
from module import add

def test_add():
    assert add(2, 3) == 5
'''

CASES = []

# ---------------------------------------------------------------------------
# EASY 1: bug lives directly in the diff of the tested function
# ---------------------------------------------------------------------------
CASES.append(Case(
    name="easy_syntax_bug",
    difficulty="easy",
    description="A commit flips a `+` to a `-` in the exact function under test.",
    bug_index=3,
    commits=[
        Commit("initial commit: add() helper", "def add(a, b):\n    return a + b\n", TEST_ADD),
        Commit("docs: add module docstring", '"""Simple arithmetic helpers."""\n\n\ndef add(a, b):\n    return a + b\n', TEST_ADD),
        Commit("style: rename args for clarity", '"""Simple arithmetic helpers."""\n\n\ndef add(x, y):\n    return x + y\n', TEST_ADD),
        Commit("fix: correct sign handling in add()", '"""Simple arithmetic helpers."""\n\n\ndef add(x, y):\n    return x - y\n', TEST_ADD),
        Commit("chore: add multiply() helper", '"""Simple arithmetic helpers."""\n\n\ndef add(x, y):\n    return x - y\n\n\ndef multiply(x, y):\n    return x * y\n', TEST_ADD),
        Commit("chore: add subtract() helper", '"""Simple arithmetic helpers."""\n\n\ndef add(x, y):\n    return x - y\n\n\ndef multiply(x, y):\n    return x * y\n\n\ndef subtract(x, y):\n    return x - y\n', TEST_ADD),
    ],
))

# ---------------------------------------------------------------------------
# EASY 2: off-by-one slice bound
# ---------------------------------------------------------------------------
TEST_SUM_FIRST_N = '''
from module import sum_first_n

def test_sum_first_n():
    assert sum_first_n([1, 2, 3, 4], 3) == 6
'''
CASES.append(Case(
    name="easy_off_by_one",
    difficulty="easy",
    description="A commit narrows a slice bound by one, an off-by-one bug.",
    bug_index=2,
    commits=[
        Commit("initial commit: sum_first_n()", "def sum_first_n(items, n):\n    return sum(items[:n])\n", TEST_SUM_FIRST_N),
        Commit("docs: add type hints", "def sum_first_n(items: list, n: int) -> int:\n    return sum(items[:n])\n", TEST_SUM_FIRST_N),
        Commit("perf: avoid summing the trailing element twice (off-by-one)", "def sum_first_n(items: list, n: int) -> int:\n    return sum(items[:n - 1])\n", TEST_SUM_FIRST_N),
        Commit("docs: clarify function purpose", "def sum_first_n(items: list, n: int) -> int:\n    \"\"\"Sum the first n items.\"\"\"\n    return sum(items[:n - 1])\n", TEST_SUM_FIRST_N),
        Commit("chore: add avg_first_n()", "def sum_first_n(items: list, n: int) -> int:\n    \"\"\"Sum the first n items.\"\"\"\n    return sum(items[:n - 1])\n\n\ndef avg_first_n(items: list, n: int) -> float:\n    return sum_first_n(items, n) / n\n", TEST_SUM_FIRST_N),
    ],
))

# ---------------------------------------------------------------------------
# EASY 3: flipped modulo comparison
# ---------------------------------------------------------------------------
TEST_IS_EVEN = '''
from module import is_even

def test_is_even():
    assert is_even(4) is True
'''
CASES.append(Case(
    name="easy_wrong_return",
    difficulty="easy",
    description="A commit flips `== 0` to `== 1` in a parity check.",
    bug_index=2,
    commits=[
        Commit("initial commit: is_even()", "def is_even(x):\n    return x % 2 == 0\n", TEST_IS_EVEN),
        Commit("style: minor formatting pass", "def is_even(x):\n    return (x % 2) == 0\n", TEST_IS_EVEN),
        Commit("fix: correct parity check edge case", "def is_even(x):\n    return (x % 2) == 1\n", TEST_IS_EVEN),
        Commit("docs: add docstring", "def is_even(x):\n    \"\"\"Return True if x is even.\"\"\"\n    return (x % 2) == 1\n", TEST_IS_EVEN),
    ],
))

# ---------------------------------------------------------------------------
# EASY 4: flipped comparison operator
# ---------------------------------------------------------------------------
TEST_MAX_OF = '''
from module import max_of

def test_max_of():
    assert max_of(3, 7) == 7
'''
CASES.append(Case(
    name="easy_logic_flip",
    difficulty="easy",
    description="A commit flips `>` to `<` in a max() implementation.",
    bug_index=3,
    commits=[
        Commit("initial commit: max_of()", "def max_of(a, b):\n    return a if a > b else b\n", TEST_MAX_OF),
        Commit("docs: add module docstring", '"""Comparison helpers."""\n\n\ndef max_of(a, b):\n    return a if a > b else b\n', TEST_MAX_OF),
        Commit("chore: add min_of()", '"""Comparison helpers."""\n\n\ndef max_of(a, b):\n    return a if a > b else b\n\n\ndef min_of(a, b):\n    return a if a < b else b\n', TEST_MAX_OF),
        Commit("refactor: simplify max_of using min_of pattern", '"""Comparison helpers."""\n\n\ndef max_of(a, b):\n    return a if a < b else b\n\n\ndef min_of(a, b):\n    return a if a < b else b\n', TEST_MAX_OF),
        Commit("docs: document both helpers", '"""Comparison helpers."""\n\n\ndef max_of(a, b):\n    """Return the larger of a and b."""\n    return a if a < b else b\n\n\ndef min_of(a, b):\n    """Return the smaller of a and b."""\n    return a if a < b else b\n', TEST_MAX_OF),
    ],
))

# ---------------------------------------------------------------------------
# EASY 5: removed guard clause
# ---------------------------------------------------------------------------
TEST_SAFE_DIVIDE = '''
from module import safe_divide

def test_safe_divide_by_zero():
    assert safe_divide(10, 0) is None

def test_safe_divide_normal():
    assert safe_divide(10, 2) == 5
'''
CASES.append(Case(
    name="easy_removed_check",
    difficulty="easy",
    description="A commit removes the b==0 guard clause, so division by zero raises instead of returning None.",
    bug_index=2,
    commits=[
        Commit("initial commit: safe_divide()", "def safe_divide(a, b):\n    if b == 0:\n        return None\n    return a / b\n", TEST_SAFE_DIVIDE),
        Commit("style: formatting pass", "def safe_divide(a, b):\n    # guard against division by zero\n    if b == 0:\n        return None\n    return a / b\n", TEST_SAFE_DIVIDE),
        Commit("refactor: simplify safe_divide control flow", "def safe_divide(a, b):\n    return a / b\n", TEST_SAFE_DIVIDE),
        Commit("docs: add docstring", "def safe_divide(a, b):\n    \"\"\"Divide a by b.\"\"\"\n    return a / b\n", TEST_SAFE_DIVIDE),
    ],
))

# ---------------------------------------------------------------------------
# MEDIUM 1: bug lives in a shared helper, not the tested function itself
# ---------------------------------------------------------------------------
TEST_FORMAT_PRICE = '''
from module import format_price

def test_format_price_clamps_high():
    assert format_price(150) == "$100.00"

def test_format_price_clamps_low():
    assert format_price(-10) == "$0.00"

def test_format_price_normal():
    assert format_price(42) == "$42.00"
'''
CASES.append(Case(
    name="medium_shared_helper",
    difficulty="medium",
    description="format_price() is tested directly, but the bug is injected into clamp(), a helper it calls -- the diff never touches format_price's own body.",
    bug_index=3,
    notes="Baseline commit-message guessing has no way to know clamp() feeds format_price().",
    commits=[
        Commit(
            "initial commit: clamp() + format_price()",
            "def clamp(x, lo, hi):\n    if x < lo:\n        return lo\n    if x > hi:\n        return hi\n    return x\n\n\ndef format_price(x):\n    return f\"${clamp(x, 0, 100):.2f}\"\n",
            TEST_FORMAT_PRICE,
        ),
        Commit(
            "docs: add module docstring",
            "\"\"\"Pricing helpers.\"\"\"\n\n\ndef clamp(x, lo, hi):\n    if x < lo:\n        return lo\n    if x > hi:\n        return hi\n    return x\n\n\ndef format_price(x):\n    return f\"${clamp(x, 0, 100):.2f}\"\n",
            TEST_FORMAT_PRICE,
        ),
        Commit(
            "chore: add clamp_percent() convenience wrapper",
            "\"\"\"Pricing helpers.\"\"\"\n\n\ndef clamp(x, lo, hi):\n    if x < lo:\n        return lo\n    if x > hi:\n        return hi\n    return x\n\n\ndef clamp_percent(x):\n    return clamp(x, 0, 100)\n\n\ndef format_price(x):\n    return f\"${clamp(x, 0, 100):.2f}\"\n",
            TEST_FORMAT_PRICE,
        ),
        Commit(
            "perf: short-circuit clamp() for the common case",
            "\"\"\"Pricing helpers.\"\"\"\n\n\ndef clamp(x, lo, hi):\n    if x > hi:\n        return hi\n    return x\n",
            TEST_FORMAT_PRICE.replace("from module import format_price", "from module import clamp\n\ndef format_price(x):\n    return f\"${clamp(x, 0, 100):.2f}\""),
        ),
        Commit(
            "docs: clamp() docstring",
            "\"\"\"Pricing helpers.\"\"\"\n\n\ndef clamp(x, lo, hi):\n    \"\"\"Clamp x into [lo, hi].\"\"\"\n    if x > hi:\n        return hi\n    return x\n",
            TEST_FORMAT_PRICE.replace("from module import format_price", "from module import clamp\n\ndef format_price(x):\n    return f\"${clamp(x, 0, 100):.2f}\""),
        ),
    ],
))

# ---------------------------------------------------------------------------
# MEDIUM 2: bug is a changed default parameter
# ---------------------------------------------------------------------------
TEST_DISCOUNT = '''
from module import discount

def test_discount_default_rate():
    assert discount(100) == 90
'''
CASES.append(Case(
    name="medium_changed_default",
    difficulty="medium",
    description="A commit bumps a default keyword argument (promo rate 0.1 -> 0.2) buried in an unrelated-sounding commit.",
    bug_index=2,
    commits=[
        Commit("initial commit: discount()", "def discount(price, rate=0.1):\n    return price * (1 - rate)\n", TEST_DISCOUNT),
        Commit("docs: add module docstring", '"""Checkout pricing helpers."""\n\n\ndef discount(price, rate=0.1):\n    return price * (1 - rate)\n', TEST_DISCOUNT),
        Commit("promo: tune default discount rate for August campaign", '"""Checkout pricing helpers."""\n\n\ndef discount(price, rate=0.2):\n    return price * (1 - rate)\n', TEST_DISCOUNT),
        Commit("chore: add bulk_discount() wrapper", '"""Checkout pricing helpers."""\n\n\ndef discount(price, rate=0.2):\n    return price * (1 - rate)\n\n\ndef bulk_discount(price, qty):\n    return discount(price, rate=0.2) if qty >= 10 else price\n', TEST_DISCOUNT),
    ],
))

# ---------------------------------------------------------------------------
# MEDIUM 3: bug is a changed constant in a config-like section, diff doesn't
# touch the function under test.
# ---------------------------------------------------------------------------
TEST_TOTAL_WITH_TAX = '''
from module import total_with_tax

def test_total_with_tax():
    assert round(total_with_tax(100), 2) == 107.00
'''
CASES.append(Case(
    name="medium_config_change",
    difficulty="medium",
    description="TAX_RATE constant changes in isolation; total_with_tax()'s own body is untouched in every commit's diff.",
    bug_index=2,
    commits=[
        Commit("initial commit: TAX_RATE + total_with_tax()", "TAX_RATE = 0.07\n\n\ndef total_with_tax(price):\n    return price * (1 + TAX_RATE)\n", TEST_TOTAL_WITH_TAX),
        Commit("docs: add module docstring", '"""Checkout totals."""\n\nTAX_RATE = 0.07\n\n\ndef total_with_tax(price):\n    return price * (1 + TAX_RATE)\n', TEST_TOTAL_WITH_TAX),
        Commit("config: update TAX_RATE for new fiscal year", '"""Checkout totals."""\n\nTAX_RATE = 0.15\n\n\ndef total_with_tax(price):\n    return price * (1 + TAX_RATE)\n', TEST_TOTAL_WITH_TAX),
        Commit("chore: add total_with_tax_rounded()", '"""Checkout totals."""\n\nTAX_RATE = 0.15\n\n\ndef total_with_tax(price):\n    return price * (1 + TAX_RATE)\n\n\ndef total_with_tax_rounded(price):\n    return round(total_with_tax(price), 2)\n', TEST_TOTAL_WITH_TAX),
    ],
))

# ---------------------------------------------------------------------------
# HARD 1: flaky failure -- the "bad" region only fails probabilistically,
# so a single test run per candidate can mis-narrow the search. verify()
# must rerun to catch this.
# ---------------------------------------------------------------------------
TEST_COMPUTE_ASYNC = '''
from module import compute_async

def test_compute_async():
    assert compute_async(5) == 10
'''
GOOD_ASYNC_BODY = (
    "import threading\nimport time\n\n\n"
    "def compute_async(x):\n"
    "    result = {}\n\n"
    "    def worker():\n"
    "        time.sleep(0.01)\n"
    "        result['value'] = x * 2\n\n"
    "    t = threading.Thread(target=worker)\n"
    "    t.start()\n"
    "    t.join(timeout=0.2)\n"
    "    return result.get('value')\n"
)
BAD_ASYNC_BODY = (
    "import random\nimport threading\nimport time\n\n\n"
    "def compute_async(x):\n"
    "    result = {}\n\n"
    "    def worker():\n"
    "        time.sleep(random.uniform(0.0, 0.05))\n"
    "        result['value'] = x * 2\n\n"
    "    t = threading.Thread(target=worker)\n"
    "    t.start()\n"
    "    t.join(timeout=0.025)\n"
    "    return result.get('value')\n"
)
CASES.append(Case(
    name="hard_flaky_verify",
    difficulty="hard",
    description="The regressing commit shortens a thread-join timeout below the (jittered) worker duration, so the test fails only ~60% of the time -- a single-shot bisect can land on the wrong commit; verify()'s repeated reruns are required to confirm the true flip point.",
    bug_index=2,
    notes="This is the case documented in eval/results.md as the deliberate 'hard' fixture.",
    commits=[
        Commit("initial commit: compute_async()", GOOD_ASYNC_BODY, TEST_COMPUTE_ASYNC),
        Commit("docs: add module docstring", '"""Async helpers."""\n\n' + GOOD_ASYNC_BODY, TEST_COMPUTE_ASYNC),
        Commit("perf: reduce worker join timeout, add jitter to avoid thundering herd", '"""Async helpers."""\n\n' + BAD_ASYNC_BODY, TEST_COMPUTE_ASYNC),
        Commit("docs: note the timeout tuning", '"""Async helpers. Timeout tuned for latency."""\n\n' + BAD_ASYNC_BODY, TEST_COMPUTE_ASYNC),
    ],
))

# ---------------------------------------------------------------------------
# HARD 2: actively misleading commit message. The real bug hides behind a
# boring "refactor" message; a scary-sounding neighboring commit is a red
# herring that changes nothing behaviorally.
# ---------------------------------------------------------------------------
TEST_VALIDATE_EMAIL = '''
from module import validate_email

def test_validate_email_valid():
    assert validate_email("user@example.com") is True

def test_validate_email_invalid():
    assert validate_email("not-an-email") is False
'''
CASES.append(Case(
    name="hard_misleading_message",
    difficulty="hard",
    description="The breaking commit is labeled a harmless no-op refactor; a scarier-sounding neighboring commit ('WIP: rewrite validation, might be buggy') is actually behavior-preserving. A commit-message-only baseline is led to the wrong SHA with high confidence.",
    bug_index=3,
    notes="Designed to make the baseline confidently wrong.",
    commits=[
        Commit(
            "initial commit: validate_email()",
            "def validate_email(s):\n    if \"@\" not in s:\n        return False\n    domain = s.split(\"@\")[1]\n    return \".\" in domain\n",
            TEST_VALIDATE_EMAIL,
        ),
        Commit(
            "docs: add module docstring",
            "\"\"\"Email validation helpers.\"\"\"\n\n\ndef validate_email(s):\n    if \"@\" not in s:\n        return False\n    domain = s.split(\"@\")[1]\n    return \".\" in domain\n",
            TEST_VALIDATE_EMAIL,
        ),
        Commit(
            "WIP: rewrite validation logic, might be buggy",
            "\"\"\"Email validation helpers.\"\"\"\n\n\ndef validate_email(s):\n    if \"@\" not in s:\n        return False\n    local, domain = s.split(\"@\", 1)\n    return \".\" in domain\n",
            TEST_VALIDATE_EMAIL,
        ),
        Commit(
            "refactor: extract email parts for readability (no behavior change)",
            "\"\"\"Email validation helpers.\"\"\"\n\n\ndef validate_email(s):\n    if \"@\" not in s:\n        return False\n    local, domain = s.split(\"@\", 1)\n    return \".\" in local\n",
            TEST_VALIDATE_EMAIL,
        ),
        Commit(
            "docs: minor comment cleanup",
            "\"\"\"Email validation helpers.\"\"\"\n\n\ndef validate_email(s):\n    # check the local part and domain part\n    if \"@\" not in s:\n        return False\n    local, domain = s.split(\"@\", 1)\n    return \".\" in local\n",
            TEST_VALIDATE_EMAIL,
        ),
    ],
))
