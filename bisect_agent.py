#!/usr/bin/env python3
"""
Bisect Agent CLI.

    bisect_agent.py run --repo <path> --good <sha> --bad <sha> --test-cmd "..." [--test-name ...]
    bisect_agent.py baseline --repo <path> --good <sha> --bad <sha> --test-name ...
    bisect_agent.py eval [--stage all|baseline|linear|binary|verify|final]
"""
import argparse
import json
import sys
from pathlib import Path

from agent import git_utils
from agent.llm import get_client, DEFAULT_MODEL
from agent.orchestrator import run_agent
from agent.baseline import run_baseline
from agent.trajectory import TrajectoryLogger

ROOT = Path(__file__).parent


def cmd_run(args):
    client = get_client()
    repo_path = Path(args.repo).resolve()
    label = repo_path.parent.name if repo_path.name == "repo" else repo_path.name
    log_path = ROOT / "trajectories" / f"run_{label}_{args.good[:8]}_{args.bad[:8]}.jsonl"
    logger = TrajectoryLogger(log_path)
    try:
        result = run_agent(
            client, args.repo, args.good, args.bad, args.test_cmd, logger,
            strategy=args.strategy, do_verify=not args.no_verify, do_explain=not args.no_explain,
            model=args.model,
        )
    finally:
        logger.close()

    print(json.dumps({k: v for k, v in result.items() if k not in ("verify_result", "explain_result")}, indent=2))
    if result["explain_result"]:
        from agent.tools import render_causal_chain
        print("\n--- chain of failure ---")
        print(render_causal_chain(result["explain_result"]["causal_chain"]))
        print("\n--- summary ---")
        print(result["explain_result"]["explanation"])
        if result["explain_result"]["ungrounded"]:
            print(f"\n[FLAGGED UNGROUNDED] {result['explain_result']['flag_reason']}")
    print(f"\ntrajectory written to {log_path}")
    md_path = log_path.with_suffix(".md")
    md_path.write_text(logger.render_markdown())
    print(f"human-readable trajectory written to {md_path}")


def cmd_baseline(args):
    client = get_client()
    result = run_baseline(client, args.repo, args.good, args.bad, args.test_name, model=args.model)
    print(json.dumps(result, indent=2))


def cmd_eval(args):
    from eval.run_eval import main as eval_main
    eval_main(stage=args.stage, model=args.model)


def main():
    parser = argparse.ArgumentParser(description="Bisect Agent: automated git bisect with root-cause explanation.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run the agent on a single repo/range.")
    p_run.add_argument("--repo", required=True)
    p_run.add_argument("--good", required=True)
    p_run.add_argument("--bad", required=True)
    p_run.add_argument("--test-cmd", required=True)
    p_run.add_argument("--strategy", choices=["linear", "binary"], default="binary")
    p_run.add_argument("--no-verify", action="store_true")
    p_run.add_argument("--no-explain", action="store_true")
    p_run.add_argument("--model", default=DEFAULT_MODEL)
    p_run.set_defaults(func=cmd_run)

    p_base = sub.add_parser("baseline", help="Run the single-prompt commit-message baseline.")
    p_base.add_argument("--repo", required=True)
    p_base.add_argument("--good", required=True)
    p_base.add_argument("--bad", required=True)
    p_base.add_argument("--test-name", required=True)
    p_base.add_argument("--model", default=DEFAULT_MODEL)
    p_base.set_defaults(func=cmd_baseline)

    p_eval = sub.add_parser("eval", help="Run the full fixture suite and emit eval/results.md.")
    p_eval.add_argument("--stage", default="all",
                         choices=["all", "baseline", "linear", "binary", "verify", "final"])
    p_eval.add_argument("--model", default=DEFAULT_MODEL)
    p_eval.set_defaults(func=cmd_eval)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
