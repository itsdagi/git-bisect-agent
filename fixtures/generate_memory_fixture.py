#!/usr/bin/env python3
"""
Builds the repeat-bug-class memory demo fixture under
fixtures/cases/memory_repeat_bug/repo, and writes meta.json with TWO bisect
ranges (see memory_case.py's module docstring for why this fixture doesn't
fit the single good_sha/bad_sha schema the other 10 cases use).
"""
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from memory_case import COMMITS, TEST_CMD, RANGE_1, RANGE_2

FIXTURES_DIR = Path(__file__).parent
CASE_DIR = FIXTURES_DIR / "cases" / "memory_repeat_bug"
BASE_DATE = datetime(2025, 3, 1, 9, 0, 0)


def run(cmd, cwd, env=None):
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd}\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def main():
    repo_dir = CASE_DIR / "repo"
    if repo_dir.exists():
        shutil.rmtree(repo_dir)
    repo_dir.mkdir(parents=True)

    run(["git", "init", "-q"], cwd=repo_dir)
    run(["git", "config", "user.email", "fixture@example.com"], cwd=repo_dir)
    run(["git", "config", "user.name", "Fixture Author"], cwd=repo_dir)

    shas = []
    for i, commit in enumerate(COMMITS):
        (repo_dir / "module.py").write_text(commit.module_py)
        (repo_dir / "test_module.py").write_text(commit.test_py)
        run(["git", "add", "-A"], cwd=repo_dir)
        d = (BASE_DATE + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%S")
        env = dict(os.environ)
        env["GIT_AUTHOR_DATE"] = d
        env["GIT_COMMITTER_DATE"] = d
        run(["git", "commit", "-q", "-m", commit.message], cwd=repo_dir, env=env)
        shas.append(run(["git", "rev-parse", "HEAD"], cwd=repo_dir))

    meta = {
        "name": "memory_repeat_bug",
        "test_cmd": TEST_CMD,
        "all_shas_in_order": shas,
        "commit_messages": [c.message for c in COMMITS],
        "range_1": {
            "good_sha": shas[RANGE_1["good_index"]],
            "bad_sha": shas[RANGE_1["bad_index"]],
            "ground_truth_bug_sha": shas[RANGE_1["bug_index"]],
            "label": "get_user_email() loses its null guard",
        },
        "range_2": {
            "good_sha": shas[RANGE_2["good_index"]],
            "bad_sha": shas[RANGE_2["bad_index"]],
            "ground_truth_bug_sha": shas[RANGE_2["bug_index"]],
            "label": "get_user_phone() loses its null guard (same bug class, different function)",
        },
    }
    (CASE_DIR / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"built memory_repeat_bug at {repo_dir}")
    print(f"range_1: good={meta['range_1']['good_sha'][:8]} bad={meta['range_1']['bad_sha'][:8]} "
          f"bug={meta['range_1']['ground_truth_bug_sha'][:8]}")
    print(f"range_2: good={meta['range_2']['good_sha'][:8]} bad={meta['range_2']['bad_sha'][:8]} "
          f"bug={meta['range_2']['ground_truth_bug_sha'][:8]}")


if __name__ == "__main__":
    main()
