"""
The agent orchestrator. Implements the bisect search loop explicitly (no
shelling out to `git bisect run`) so every step is inspectable and logged.

Supports two narrowing strategies, corresponding to the hackathon's build
order:
  - "linear": walk commits one at a time from good -> bad, stop at first
    failure. (Iteration 1.)
  - "binary": real binary-search narrowing via narrow_range(). (Iteration 2+.)

`do_verify` and `do_explain` gate iterations 3 and 4/5 respectively so the
eval harness can run every stage and compare them head to head.
"""
import time

from . import git_utils, tools
from .llm import DEFAULT_MODEL, cost_usd


def run_agent(
    client,
    repo,
    good_sha,
    bad_sha,
    test_cmd,
    logger,
    strategy="binary",
    do_verify=True,
    do_explain=True,
    model=DEFAULT_MODEL,
    verify_reruns=3,
):
    t_start = time.time()
    test_executions = 0
    llm_input_tokens = 0
    llm_output_tokens = 0

    def call_tool(name, fn, **kwargs):
        nonlocal test_executions
        logger.log("tool_call_start", tool=name, input=kwargs)
        result = fn(**kwargs)
        if name == "run_test":
            test_executions += 1
        logger.log("tool_call", tool=name, input=kwargs, result=result)
        return result

    # Sanity: confirm the given boundaries actually bracket the regression.
    good_result = call_tool("run_test", tools.run_test, repo=repo, sha=good_sha, test_cmd=test_cmd)
    bad_result = call_tool("run_test", tools.run_test, repo=repo, sha=bad_sha, test_cmd=test_cmd)
    logger.log("decision", note=(
        f"boundary check: good_sha passed={good_result['passed']}, "
        f"bad_sha passed={bad_result['passed']}"
    ))

    candidate_sha = None

    if strategy == "linear":
        commits = git_utils.rev_list_between(repo, good_sha, bad_sha)
        logger.log("info", note=f"linear scan over {len(commits)} candidate commits")
        for sha in commits:
            r = call_tool("run_test", tools.run_test, repo=repo, sha=sha, test_cmd=test_cmd)
            if not r["passed"]:
                candidate_sha = sha
                logger.log("decision", note=f"linear scan: first failing commit is {sha[:10]}, stopping")
                break
        if candidate_sha is None:
            candidate_sha = bad_sha

    elif strategy == "binary":
        lo, hi = good_sha, bad_sha
        logger.log("info", note=f"binary search narrowing between {lo[:10]} (good) and {hi[:10]} (bad)")
        while True:
            mid = call_tool("narrow_range", tools.narrow_range, repo=repo, good_sha=lo, bad_sha=hi)
            if mid is None:
                candidate_sha = hi
                logger.log("decision", note=f"range exhausted: candidate breaking commit is {hi[:10]}")
                break
            r = call_tool("run_test", tools.run_test, repo=repo, sha=mid, test_cmd=test_cmd)
            if r["passed"]:
                logger.log("decision", note=f"{mid[:10]} passes -> move good boundary forward")
                lo = mid
            else:
                logger.log("decision", note=f"{mid[:10]} fails -> move bad boundary back")
                hi = mid
    else:
        raise ValueError(f"unknown strategy: {strategy}")

    verify_result = None
    final_sha = candidate_sha
    max_backtrack = 3
    if do_verify:
        current = candidate_sha
        reruns = verify_reruns
        for attempt in range(max_backtrack + 1):
            verify_result = call_tool("verify", tools.verify, repo=repo, candidate_sha=current,
                                       test_cmd=test_cmd, reruns=reruns)
            test_executions += reruns * 2  # verify() internally runs candidate + parent, `reruns` times each
            if verify_result["flaky"]:
                logger.log("decision", note=(
                    f"verify() saw inconsistent results for {current[:10]} (candidate_fail_rate="
                    f"{verify_result['candidate_fail_rate']:.2f}, parent_pass_rate="
                    f"{verify_result['parent_pass_rate']:.2f}) across {reruns} reruns each"
                ))
            if verify_result["confirmed"]:
                logger.log("decision", note=f"verify() confirmed {current[:10]} as the breaking commit")
                final_sha = current
                break
            # Not confirmed: if the parent itself looks like it's still failing more often
            # than not, the true flip point is further back than the search landed on.
            # Backtrack to the parent and resample harder, rather than silently reporting
            # a candidate verify() just said it couldn't confirm.
            if verify_result["parent_pass_rate"] < 0.5:
                logger.log("decision", note=(
                    f"verify() could NOT confirm {current[:10]} and its parent "
                    f"{verify_result['parent_sha'][:10]} also fails under resampling -- "
                    f"backtracking one commit and resampling harder (attempt {attempt + 1}/{max_backtrack})"
                ))
                current = verify_result["parent_sha"]
                reruns += 2
            else:
                logger.log("decision", note=(
                    f"verify() could NOT confirm {current[:10]} by majority vote across "
                    f"{reruns} reruns, and its parent looks good -- resampling harder on the "
                    f"same candidate (attempt {attempt + 1}/{max_backtrack})"
                ))
                reruns += 2
        else:
            logger.log("decision", note=(
                f"exhausted {max_backtrack} backtrack/resample attempts without a confirmed "
                f"flip; reporting best candidate {current[:10]} with confirmed=False"
            ))
            final_sha = current

    explain_result = None
    if do_explain:
        diff = call_tool("get_diff", tools.get_diff, repo=repo, sha=final_sha)
        commit_msg = call_tool("get_commit_message", tools.get_commit_message, repo=repo, sha=final_sha)
        test_output = ""
        if verify_result:
            failing_runs = [r for r in verify_result["candidate_runs"] if not r["passed"]]
            test_output = failing_runs[0]["output"] if failing_runs else verify_result["candidate_runs"][0]["output"]
        else:
            r = call_tool("run_test", tools.run_test, repo=repo, sha=final_sha, test_cmd=test_cmd)
            test_output = r["output"]

        logger.log("tool_call_start", tool="explain", input={"sha": final_sha})
        explain_result = tools.explain(
            client, model, diff["diff"], test_output, commit_msg["subject"],
        )
        logger.log("tool_call", tool="explain", input={"sha": final_sha}, result=explain_result)
        llm_input_tokens += explain_result["usage"]["input_tokens"]
        llm_output_tokens += explain_result["usage"]["output_tokens"]
        if explain_result["ungrounded"]:
            logger.log("decision", note=f"explain() flagged as ungrounded: {explain_result['flag_reason']}")
        else:
            logger.log("decision", note=(
                "explain() produced a "
                f"{len(explain_result['causal_chain'])}-step grounded causal chain"
            ))

    duration = time.time() - t_start
    result = {
        "identified_sha": final_sha,
        "verify_result": verify_result,
        "explain_result": explain_result,
        "test_executions": test_executions,
        "duration_s": round(duration, 3),
        "llm_cost_usd": cost_usd(model, llm_input_tokens, llm_output_tokens) if llm_input_tokens else 0.0,
        "llm_input_tokens": llm_input_tokens,
        "llm_output_tokens": llm_output_tokens,
        "strategy": strategy,
        "do_verify": do_verify,
        "do_explain": do_explain,
    }
    logger.log("final", note=f"identified_sha={final_sha}, test_executions={test_executions}, "
                              f"duration_s={result['duration_s']}")
    return result
