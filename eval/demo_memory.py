#!/usr/bin/env python3
"""
Runs the agent twice, with --memory equivalent (do_memory=True), over the
two ranges in fixtures/cases/memory_repeat_bug/ -- the fixture built
specifically to demo cross-run memory (see fixtures/memory_case.py).

Run 1 finds the first "missing null guard" regression (get_user_email) with
a cold history file. Run 2 finds the second, unrelated-looking regression
(get_user_phone) -- but by the time it runs, run 1's result is already in
`.bisect-agent/history.jsonl`, so query_history() finds it (same file,
module.py) and explain() gets a chance to reference it.

Writes eval/memory_demo.md with both runs' full output side by side, and
prints a pass/fail check for whether run 2's explanation actually mentions
the prior regression (a simple keyword heuristic -- the real evidence is
the printed text itself, for a human to read).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from agent.llm import get_client, DEFAULT_MODEL
from agent.orchestrator import run_agent
from agent.tools import render_causal_chain
from agent.trajectory import TrajectoryLogger
from agent import memory as memory_mod

CASE_DIR = ROOT / "fixtures" / "cases" / "memory_repeat_bug"
REPO = CASE_DIR / "repo"
OUT_MD = ROOT / "eval" / "memory_demo.md"

def run_one(client, label, good_sha, bad_sha, model):
    logger = TrajectoryLogger(f"/tmp/memory_demo_{label}.jsonl")
    try:
        result = run_agent(
            client, REPO, good_sha, bad_sha, "python -m pytest -q test_module.py", logger,
            strategy="binary", do_verify=True, do_explain=True, do_memory=True, model=model,
        )
    finally:
        logger.close()
    return result


def main(model=DEFAULT_MODEL):
    # Fresh start: this demo's whole point is showing history accumulate
    # across these two specific runs, so clear any stale file first.
    history_path = REPO / ".bisect-agent" / "history.jsonl"
    if history_path.exists():
        history_path.unlink()

    meta = json.loads((CASE_DIR / "meta.json").read_text())
    client = get_client()

    print("=== Run 1: get_user_email() regression (cold history) ===")
    r1 = run_one(client, "run1", meta["range_1"]["good_sha"], meta["range_1"]["bad_sha"], model)
    print(f"identified: {r1['identified_sha'][:10]} (ground truth: {meta['range_1']['ground_truth_bug_sha'][:10]})")
    print(f"root_cause_tag: {r1['explain_result']['root_cause_tag']}")
    print(r1["explain_result"]["explanation"])

    print("\n=== Run 2: get_user_phone() regression (history from run 1 present) ===")
    r2 = run_one(client, "run2", meta["range_2"]["good_sha"], meta["range_2"]["bad_sha"], model)
    print(f"identified: {r2['identified_sha'][:10]} (ground truth: {meta['range_2']['ground_truth_bug_sha'][:10]})")
    print(f"root_cause_tag: {r2['explain_result']['root_cause_tag']}")
    print(r2["explain_result"]["explanation"])

    run1_correct = r1["identified_sha"] == meta["range_1"]["ground_truth_bug_sha"]
    run2_correct = r2["identified_sha"] == meta["range_2"]["ground_truth_bug_sha"]
    references_history = bool(r2["explain_result"].get("history_note"))

    lines = [
        "# Memory demo: two runs, same repo, same bug class",
        "",
        "Fixture: `fixtures/cases/memory_repeat_bug/` -- one repo, two separate "
        "regressions of the same class (\"missing-null-check\") introduced at two "
        "different points in its history, in two different functions. Both runs "
        "below use `do_memory=True` (`bisect_agent.py run --memory`) against the "
        "SAME repo, so run 2 sees run 1's recorded entry in "
        "`.bisect-agent/history.jsonl`.",
        "",
        f"Run 1 identified correct commit: **{run1_correct}**  |  "
        f"Run 2 identified correct commit: **{run2_correct}**",
        f"Run 2's explanation references the prior regression: **{references_history}**",
        "",
        "## Run 1 -- cold history",
        "",
        f"Identified: `{r1['identified_sha'][:10]}` (ground truth: `{meta['range_1']['ground_truth_bug_sha'][:10]}`)",
        f"Confidence: {r1['confidence']}  |  Root cause tag: `{r1['explain_result']['root_cause_tag']}`",
        "",
        "### Chain of failure",
        "```",
        render_causal_chain(r1["explain_result"]["causal_chain"]),
        "```",
        "",
        "### Summary",
        r1["explain_result"]["explanation"],
        "",
        "## Run 2 -- with run 1's history present",
        "",
        f"Identified: `{r2['identified_sha'][:10]}` (ground truth: `{meta['range_2']['ground_truth_bug_sha'][:10]}`)",
        f"Confidence: {r2['confidence']}  |  Root cause tag: `{r2['explain_result']['root_cause_tag']}`",
        "",
        "### Chain of failure",
        "```",
        render_causal_chain(r2["explain_result"]["causal_chain"]),
        "```",
        "",
        "### Summary",
        r2["explain_result"]["explanation"],
        "",
        f"**History note:** {r2['explain_result'].get('history_note') or '(none)'}",
        "",
        "## History file after both runs",
        "",
        "```json",
        history_path.read_text().strip(),
        "```",
        "",
        "## What this demonstrates",
        "",
        "Run 2's diagnosis (*which* commit) came from the same run_test/narrow_range/"
        "verify() pipeline as run 1 -- memory played no part in identifying "
        "`get_user_phone`'s regressing commit. What memory changed is *how the "
        "explanation is framed*: run 2's `explain()` call received run 1's recorded "
        "entry (matched on `files_touched: [\"module.py\"]`) as context, and could "
        "reference the earlier `missing-null-check` regression instead of narrating "
        "the second bug as if it were the first time this pattern occurred in the repo.",
    ]
    OUT_MD.write_text("\n".join(lines) + "\n")
    print(f"\nwrote {OUT_MD}")
    print(f"run1_correct={run1_correct} run2_correct={run2_correct} references_history={references_history}")


if __name__ == "__main__":
    main()
