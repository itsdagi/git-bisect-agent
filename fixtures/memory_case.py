"""
Declarative definition of the one fixture built specifically for the
cross-run memory feature: a repo where the same bug *class*
("missing-null-check") is reintroduced twice, at two different points in
its history, in two different functions. Unlike the 10 cases in
case_defs.py (each a single good_sha..bad_sha range with one ground-truth
culprit), this fixture has TWO separate bisect ranges over one shared
commit history and one shared `.bisect-agent/history.jsonl` -- run the
agent over range 1 first, then range 2, and the second run's explain()
should reference the first (see eval/demo_memory.py).

Commit history (7 commits):
  0. initial commit -- get_user_email() and get_user_phone(), both guarded
     against a None user
  1. docs
  2. BUG 1: removes the null guard from get_user_email()          <- range 1 bad
  3. fix: restores the null guard in get_user_email()
  4. docs / unrelated change                                       <- range 2 good
  5. BUG 2: removes the null guard from get_user_phone() (same bug class,
     different function)
  6. docs                                                          <- range 2 bad
"""
from dataclasses import dataclass

from case_defs import Commit

TEST_MODULE = '''
from module import get_user_email, get_user_phone

def test_get_user_email_present():
    assert get_user_email({"email": "a@b.com"}) == "a@b.com"

def test_get_user_email_missing_user():
    assert get_user_email(None) is None

def test_get_user_phone_present():
    assert get_user_phone({"phone": "555-1234"}) == "555-1234"

def test_get_user_phone_missing_user():
    assert get_user_phone(None) is None
'''

GUARDED_BOTH = '''def get_user_email(user):
    if not user:
        return None
    return user.get("email")


def get_user_phone(user):
    if not user:
        return None
    return user.get("phone")
'''

UNGUARDED_EMAIL = '''def get_user_email(user):
    return user.get("email")


def get_user_phone(user):
    if not user:
        return None
    return user.get("phone")
'''

UNGUARDED_BOTH_PHONE = '''def get_user_email(user):
    if not user:
        return None
    return user.get("email")


def get_user_phone(user):
    return user.get("phone")
'''

COMMITS = [
    Commit("initial commit: get_user_email() and get_user_phone()", GUARDED_BOTH, TEST_MODULE),
    Commit("docs: add module docstring", '"""User field accessors."""\n\n\n' + GUARDED_BOTH, TEST_MODULE),
    Commit("refactor: simplify get_user_email", '"""User field accessors."""\n\n\n' + UNGUARDED_EMAIL, TEST_MODULE),
    Commit("fix: restore null guard in get_user_email", '"""User field accessors."""\n\n\n' + GUARDED_BOTH, TEST_MODULE),
    Commit("docs: note both accessors are null-safe", '"""User field accessors. Both null-safe."""\n\n\n' + GUARDED_BOTH, TEST_MODULE),
    Commit("refactor: simplify get_user_phone", '"""User field accessors. Both null-safe."""\n\n\n' + UNGUARDED_BOTH_PHONE, TEST_MODULE),
    Commit("docs: minor comment pass", '"""User field accessors. Both null-safe. See tests."""\n\n\n' + UNGUARDED_BOTH_PHONE, TEST_MODULE),
]

TEST_CMD = "python -m pytest -q test_module.py"

# Indices into COMMITS for each of the two bisect ranges.
RANGE_1 = {"good_index": 1, "bad_index": 2, "bug_index": 2}
RANGE_2 = {"good_index": 4, "bad_index": 6, "bug_index": 5}
