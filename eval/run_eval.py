"""
Runs baseline + every agent iteration across all fixture cases and writes
eval/results.md with the comparison table the hackathon rubric asks for.

Stages:
  baseline - single-prompt commit-message guesser (iteration 0)
  linear   - agent with run_test, plain linear scan (iteration 1)
  binary   - agent with narrow_range binary search (iteration 2)
  verify   - binary + verify() (iteration 3)
  final    - binary + verify() + explain() (iteration 4/5, the shipped agent)
"""
import json
import time
from pathlib import Path

from agent.llm import get_client, DEFAULT_MODEL, cost_usd
from agent.baseline import run_baseline
from agent.orchestrator import run_agent
from agent.trajectory import TrajectoryLogger

ROOT = Path(__file__).parent.parent
CASES_DIR = ROOT / "fixtures" / "cases"
TRAJ_DIR = ROOT / "trajectories"
RESULTS_JSON = ROOT / "eval" / "raw_results.json"
RESULTS_MD = ROOT / "eval" / "results.md"
NARRATIVE_MD = ROOT / "eval" / "_narrative.md"

STAGE_CONFIG = {
    "linear": dict(strategy="linear", do_verify=False, do_explain=False),
    "binary": dict(strategy="binary", do_verify=False, do_explain=False),
    "verify": dict(strategy="binary", do_verify=True, do_explain=False),
    "final": dict(strategy="binary", do_verify=True, do_explain=True),
}


def load_cases():
    metas = []
    for meta_path in sorted(CASES_DIR.glob("*/meta.json")):
        metas.append(json.loads(meta_path.read_text()))
    return metas


def test_name_from_meta(meta):
    # first test function name referenced in the test command's file, good enough
    # for the baseline prompt which only needs a human label
    return meta["test_cmd"]


def run_stage(client, model, stage, meta, repo, keep_trajectory=False):
    if stage == "baseline":
        r = run_baseline(client, repo, meta["good_sha"], meta["bad_sha"],
                          test_name_from_meta(meta), model=model)
        return {
            "identified_sha": r["guess_sha"],
            "test_executions": 0,
            "duration_s": r["duration_s"],
            "llm_cost_usd": r["cost_usd"],
            "raw": r,
        }
    cfg = STAGE_CONFIG[stage]
    log_path = TRAJ_DIR / f"_scratch_{meta['name']}_{stage}.jsonl"
    logger = TrajectoryLogger(log_path)
    try:
        r = run_agent(client, repo, meta["good_sha"], meta["bad_sha"], meta["test_cmd"],
                       logger, model=model, **cfg)
    finally:
        logger.close()
    if keep_trajectory:
        dest = TRAJ_DIR / f"{meta['name']}_{stage}.md"
        dest.write_text(logger.render_markdown())
    else:
        log_path.unlink(missing_ok=True)
    return {
        "identified_sha": r["identified_sha"],
        "test_executions": r["test_executions"],
        "duration_s": r["duration_s"],
        "llm_cost_usd": r["llm_cost_usd"],
        "raw": r,
    }


def main(stage="all", model=DEFAULT_MODEL, save_trajectories_for=("easy_syntax_bug", "medium_shared_helper", "hard_flaky_verify", "hard_misleading_message")):
    client = get_client()
    cases = load_cases()
    stages = ["baseline", "linear", "binary", "verify", "final"] if stage == "all" else [stage]

    all_results = {}
    for st in stages:
        print(f"\n=== stage: {st} ===")
        stage_results = []
        for meta in cases:
            repo = CASES_DIR / meta["name"] / "repo"
            keep = meta["name"] in save_trajectories_for and st in ("linear", "final")
            t0 = time.time()
            try:
                r = run_stage(client, model, st, meta, repo, keep_trajectory=keep)
            except Exception as e:
                r = {"identified_sha": None, "test_executions": 0, "duration_s": time.time() - t0,
                     "llm_cost_usd": 0.0, "error": str(e)}
            correct = r["identified_sha"] == meta["ground_truth_bug_sha"]
            print(f"  {meta['name']:28s} correct={correct!s:5s} "
                  f"identified={str(r['identified_sha'])[:10]:10s} "
                  f"ground_truth={meta['ground_truth_bug_sha'][:10]:10s} "
                  f"test_execs={r['test_executions']:3d} "
                  f"time={r['duration_s']:.2f}s "
                  f"cost=${r['llm_cost_usd'] or 0:.4f}")
            stage_results.append({
                "case": meta["name"],
                "difficulty": meta["difficulty"],
                "correct": correct,
                "identified_sha": r["identified_sha"],
                "ground_truth_sha": meta["ground_truth_bug_sha"],
                "test_executions": r["test_executions"],
                "duration_s": r["duration_s"],
                "llm_cost_usd": r["llm_cost_usd"],
            })
        all_results[st] = stage_results

    RESULTS_JSON.write_text(json.dumps(all_results, indent=2))
    render_results_md(all_results, cases)
    print(f"\nwrote {RESULTS_JSON}\nwrote {RESULTS_MD}")


def render_results_md(all_results, cases):
    lines = ["# Evaluation Results\n"]
    lines.append(f"Fixture suite: {len(cases)} cases "
                  f"({sum(1 for c in cases if c['difficulty']=='easy')} easy, "
                  f"{sum(1 for c in cases if c['difficulty']=='medium')} medium, "
                  f"{sum(1 for c in cases if c['difficulty']=='hard')} hard).\n")

    lines.append("## Summary\n")
    lines.append("| Stage | Accuracy | Avg test executions | Avg wall time (s) | Avg LLM cost/case ($) |")
    lines.append("|---|---|---|---|---|")
    for st, results in all_results.items():
        n = len(results)
        acc = sum(1 for r in results if r["correct"]) / n * 100
        avg_execs = sum(r["test_executions"] for r in results) / n
        avg_time = sum(r["duration_s"] for r in results) / n
        avg_cost = sum(r["llm_cost_usd"] or 0 for r in results) / n
        lines.append(f"| {st} | {acc:.0f}% ({sum(1 for r in results if r['correct'])}/{n}) | "
                      f"{avg_execs:.1f} | {avg_time:.2f} | {avg_cost:.4f} |")

    lines.append("\n## Per-case detail\n")
    lines.append("| Case | Difficulty | " + " | ".join(f"{st} correct" for st in all_results) + " |")
    lines.append("|---|---|" + "---|" * len(all_results))
    for meta in cases:
        row = [meta["name"], meta["difficulty"]]
        for st in all_results:
            r = next(r for r in all_results[st] if r["case"] == meta["name"])
            row.append("YES" if r["correct"] else "no")
        lines.append("| " + " | ".join(row) + " |")

    if NARRATIVE_MD.exists():
        lines.append("")
        lines.append(NARRATIVE_MD.read_text().rstrip())

    RESULTS_MD.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
