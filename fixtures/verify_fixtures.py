#!/usr/bin/env python3
"""Sanity-checks every fixture's ground truth by actually running pytest
at good_sha, bug_parent_sha, bug_sha, and bad_sha in disposable worktrees.
Expected: good_sha and bug_parent_sha PASS; bug_sha and bad_sha FAIL.
(hard_flaky_verify is exempt from a single deterministic check -- it's
sampled multiple times.)
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

CASES_DIR = Path(__file__).parent / "cases"


def run_test_at(repo_dir, sha, test_cmd, samples=1):
    results = []
    for _ in range(samples):
        with tempfile.TemporaryDirectory() as wt:
            subprocess.run(["git", "worktree", "add", "--detach", "-q", wt, sha],
                            cwd=repo_dir, capture_output=True, text=True, check=True)
            try:
                r = subprocess.run(test_cmd, cwd=wt, shell=True, capture_output=True, text=True, timeout=30)
                results.append(r.returncode == 0)
            finally:
                subprocess.run(["git", "worktree", "remove", "--force", wt],
                                cwd=repo_dir, capture_output=True, text=True)
    return results


def main():
    ok = True
    for meta_path in sorted(CASES_DIR.glob("*/meta.json")):
        meta = json.loads(meta_path.read_text())
        repo_dir = meta_path.parent / "repo"
        name = meta["name"]
        samples = 8 if name == "hard_flaky_verify" else 1

        good = run_test_at(repo_dir, meta["good_sha"], meta["test_cmd"])
        parent = run_test_at(repo_dir, meta["ground_truth_bug_parent_sha"], meta["test_cmd"])
        bug = run_test_at(repo_dir, meta["ground_truth_bug_sha"], meta["test_cmd"], samples=samples)
        bad = run_test_at(repo_dir, meta["bad_sha"], meta["test_cmd"], samples=samples)

        good_ok = all(good)
        parent_ok = all(parent)
        bug_fail_rate = 1 - (sum(bug) / len(bug))
        bad_fail_rate = 1 - (sum(bad) / len(bad))

        status = "OK"
        if not good_ok or not parent_ok:
            status = "BROKEN (good/parent should pass)"
            ok = False
        elif name == "hard_flaky_verify":
            if not (0.15 <= bug_fail_rate <= 0.9) or bad_fail_rate < 0.15:
                status = f"BROKEN (expected flaky failure, got bug_fail_rate={bug_fail_rate:.2f} bad_fail_rate={bad_fail_rate:.2f})"
                ok = False
        else:
            if bug_fail_rate < 1.0 or bad_fail_rate < 1.0:
                status = f"BROKEN (bug/bad should always fail, got bug_fail_rate={bug_fail_rate:.2f} bad_fail_rate={bad_fail_rate:.2f})"
                ok = False

        print(f"{name:28s} good={good_ok} parent={parent_ok} bug_fail_rate={bug_fail_rate:.2f} bad_fail_rate={bad_fail_rate:.2f}  -> {status}")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
