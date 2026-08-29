#!/usr/bin/env python3
"""
Builds the throwaway fixture git repos under fixtures/cases/<name>/repo/
from the declarative definitions in case_defs.py, and writes
fixtures/cases/<name>/meta.json with ground truth (the injected bug SHA,
good/bad boundary SHAs, difficulty, test command).

Safe to re-run: each case's repo dir is wiped and rebuilt from scratch.
This never touches any repo outside fixtures/cases/.
"""
import json
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from case_defs import CASES

FIXTURES_DIR = Path(__file__).parent
CASES_DIR = FIXTURES_DIR / "cases"

BASE_DATE = datetime(2025, 1, 1, 9, 0, 0)


def run(cmd, cwd, env=None):
    result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"command failed: {cmd}\nstdout={result.stdout}\nstderr={result.stderr}")
    return result.stdout.strip()


def build_case(case):
    repo_dir = CASES_DIR / case.name / "repo"
    if repo_dir.exists():
        shutil.rmtree(repo_dir)
    repo_dir.mkdir(parents=True)

    run(["git", "init", "-q"], cwd=repo_dir)
    run(["git", "config", "user.email", "fixture@example.com"], cwd=repo_dir)
    run(["git", "config", "user.name", "Fixture Author"], cwd=repo_dir)

    shas = []
    for i, commit in enumerate(case.commits):
        (repo_dir / "module.py").write_text(commit.module_py)
        (repo_dir / "test_module.py").write_text(commit.test_py)
        run(["git", "add", "-A"], cwd=repo_dir)

        commit_date = (BASE_DATE + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%S")
        import os
        env = dict(**{**subprocess.os.environ} if False else os.environ)
        env["GIT_AUTHOR_DATE"] = commit_date
        env["GIT_COMMITTER_DATE"] = commit_date
        run(["git", "commit", "-q", "-m", commit.message], cwd=repo_dir, env=env)
        sha = run(["git", "rev-parse", "HEAD"], cwd=repo_dir)
        shas.append(sha)

    good_sha = shas[case.good_index]
    bad_sha = shas[-1]
    bug_sha = shas[case.bug_index]
    bug_parent_sha = shas[case.bug_index - 1]

    meta = {
        "name": case.name,
        "difficulty": case.difficulty,
        "description": case.description,
        "notes": case.notes,
        "test_cmd": case.test_cmd,
        "good_sha": good_sha,
        "bad_sha": bad_sha,
        "ground_truth_bug_sha": bug_sha,
        "ground_truth_bug_parent_sha": bug_parent_sha,
        "all_shas_in_order": shas,
        "commit_messages": [c.message for c in case.commits],
    }
    (CASES_DIR / case.name / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def main():
    CASES_DIR.mkdir(exist_ok=True)
    all_meta = []
    for case in CASES:
        meta = build_case(case)
        all_meta.append(meta)
        print(f"built {case.name:28s} difficulty={case.difficulty:6s} "
              f"bug_sha={meta['ground_truth_bug_sha'][:8]} "
              f"range={meta['good_sha'][:8]}..{meta['bad_sha'][:8]}")
    (CASES_DIR / "index.json").write_text(json.dumps(
        [{"name": m["name"], "difficulty": m["difficulty"]} for m in all_meta], indent=2))
    print(f"\n{len(CASES)} fixture cases built under {CASES_DIR}")


if __name__ == "__main__":
    main()
