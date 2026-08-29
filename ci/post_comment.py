#!/usr/bin/env python3
"""
CI entrypoint: runs the existing Bisect Agent pipeline (agent/orchestrator.py
-- not reimplemented here) against a base/head commit range in the checked-
out repo, then posts (or updates) a single PR comment with the result.

Invoked by .github/workflows/bisect-agent.yml. Can also be run by hand for
local dry-run testing -- omit --pr-number and it prints the comment instead
of posting anything, so you can sanity-check output without a live PR.

This script only ever reads the repo and posts/edits one issue comment. It
never pushes a commit, merges, or touches PR/branch state -- see the
workflow's permissions block (`pull-requests: write`, `issues: write`,
nothing else).
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.llm import get_client, DEFAULT_MODEL
from agent.orchestrator import run_agent
from agent.tools import render_causal_chain
from agent.trajectory import TrajectoryLogger
from ci.config import load_config, changed_paths_match_filters, ConfigError
from ci.github_api import upsert_pr_comment, GitHubAPIError

CONFIDENCE_EMOJI = {"High": "\U0001F7E2", "Medium": "\U0001F7E1", "Low": "\U0001F534", "Unverified": "⚪"}
OUTPUT_DIR = Path("bisect-agent-output")
MAX_TRAJECTORY_CHARS = 40000


def local_changed_paths(repo, base_sha, head_sha):
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_sha}..{head_sha}"],
        cwd=repo, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def render_comment(result, repo_full_name, base_sha, head_sha, run_url, test_cmd):
    sha = result["identified_sha"]
    sha8 = sha[:8]
    commit_url = f"https://github.com/{repo_full_name}/commit/{sha}"
    confidence = result["confidence"]
    emoji = CONFIDENCE_EMOJI.get(confidence, "")
    explain_result = result.get("explain_result") or {}
    chain = render_causal_chain(explain_result.get("causal_chain", []))
    summary = explain_result.get("explanation", "(no explanation available)")

    ungrounded_note = ""
    if explain_result.get("ungrounded"):
        ungrounded_note = (
            f"\n> **Note:** this explanation was flagged as possibly ungrounded "
            f"({explain_result.get('flag_reason')}) -- treat the summary above with "
            f"extra skepticism and check the diff yourself.\n"
        )

    trajectory_md = result.get("trajectory_md", "")
    if len(trajectory_md) > MAX_TRAJECTORY_CHARS:
        trajectory_md = trajectory_md[:MAX_TRAJECTORY_CHARS] + "\n\n... (truncated, see the full trajectory artifact)"

    lines = [
        "## \U0001F50D Bisect Agent found the likely culprit",
        "",
        f"**Culprit commit:** [`{sha8}`]({commit_url})",
        f"**Confidence:** {emoji} {confidence}",
        f"**Test executions:** {result['test_executions']}  |  **Wall time:** {result['duration_s']}s",
        "",
        "### Chain of failure",
        "```",
        chain,
        "```",
        "",
        "### Summary",
        summary,
        ungrounded_note,
        "<details>",
        f"<summary>Full trajectory log ({result['test_executions']} test executions)</summary>",
        "",
        # trajectory_md already contains its own ``` fences per tool call --
        # do NOT wrap it in another outer fence, GitHub terminates a fenced
        # block at the first matching ``` it sees regardless of nesting.
        trajectory_md,
        "",
        "</details>",
        "",
        "---",
        f"Reproduce locally: `python3 bisect_agent.py run --repo . --good {base_sha[:10]} "
        f"--bad {head_sha[:10]} --test-cmd \"{test_cmd}\"`",
        f"Full trajectory JSON uploaded as a workflow artifact on [this run]({run_url})." if run_url else "",
        "",
        "*Posted automatically by [Bisect Agent](https://github.com/anthropics) "
        "-- comments only, never pushes, merges, or modifies this PR.*",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", default=".", help="Path to the checked-out repo (cwd by default)")
    parser.add_argument("--repo-full-name", required=True, help="owner/name, for links and the GitHub API")
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--pr-number", default=None, help="If set, posts/updates a comment on this PR")
    parser.add_argument("--run-url", default=None, help="Link to this workflow run, for the comment footer")
    parser.add_argument("--test-cmd-override", default=None)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    try:
        config = load_config(Path(args.repo_path) / ".bisect-agent.yml")
    except ConfigError as e:
        print(f"[bisect-agent] config error: {e}", file=sys.stderr)
        sys.exit(1)
    test_cmd = args.test_cmd_override or config["test_cmd"]

    if config["path_filters"]:
        changed = local_changed_paths(args.repo_path, args.base_sha, args.head_sha)
        if not changed_paths_match_filters(changed, config["path_filters"]):
            print(f"[bisect-agent] skipping: no changed path matches path_filters "
                  f"{config['path_filters']} (changed: {changed})")
            sys.exit(0)

    OUTPUT_DIR.mkdir(exist_ok=True)
    client = get_client()
    logger = TrajectoryLogger(OUTPUT_DIR / "trajectory.jsonl")
    try:
        # do_memory=False: GitHub Actions runners are ephemeral, so
        # .bisect-agent/history.jsonl wouldn't survive between runs without
        # extra wiring (actions/cache or a bot commit) -- deliberately not
        # built here, see README.md's "future work" note.
        result = run_agent(
            client, args.repo_path, args.base_sha, args.head_sha, test_cmd, logger,
            strategy="binary", do_verify=True, do_explain=True, do_memory=False, model=args.model,
        )
    finally:
        logger.close()

    trajectory_md = logger.render_markdown()
    (OUTPUT_DIR / "trajectory.md").write_text(trajectory_md)
    result["trajectory_md"] = trajectory_md

    comment_body = render_comment(result, args.repo_full_name, args.base_sha, args.head_sha,
                                   args.run_url, test_cmd)
    (OUTPUT_DIR / "comment.md").write_text(comment_body)

    print(f"[bisect-agent] identified_sha={result['identified_sha']} confidence={result['confidence']}")

    if args.pr_number:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            print("[bisect-agent] GITHUB_TOKEN not set, cannot post comment", file=sys.stderr)
            sys.exit(1)
        try:
            upsert_pr_comment(args.repo_full_name, args.pr_number, comment_body, token)
            print(f"[bisect-agent] posted/updated comment on PR #{args.pr_number}")
        except GitHubAPIError as e:
            print(f"[bisect-agent] failed to post comment: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print("[bisect-agent] no --pr-number given, dry run only. Comment body written to "
              f"{OUTPUT_DIR / 'comment.md'}")


if __name__ == "__main__":
    main()
