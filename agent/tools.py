"""
The six discrete, loggable tools the agent uses. Every call is written to
the TrajectoryLogger by the orchestrator, not inside these functions --
that keeps the tools themselves simple, synchronous, and unit-testable.
"""
import subprocess
import time

from . import git_utils


def run_test(repo, sha, test_cmd, timeout=60):
    """Checks out `sha` into a disposable worktree and runs `test_cmd` there.
    Never mutates the caller's working tree. Returns pass/fail + captured output."""
    t0 = time.time()
    with git_utils.worktree(repo, sha) as wt:
        try:
            result = subprocess.run(test_cmd, cwd=wt, shell=True, capture_output=True,
                                     text=True, timeout=timeout)
            passed = result.returncode == 0
            output = (result.stdout + result.stderr)[-4000:]
        except subprocess.TimeoutExpired:
            passed = False
            output = f"TIMEOUT after {timeout}s"
    return {
        "sha": sha,
        "passed": passed,
        "output": output,
        "duration_s": round(time.time() - t0, 3),
    }


def get_diff(repo, sha):
    return {"sha": sha, "diff": git_utils.get_diff(repo, sha)}


def get_commit_message(repo, sha):
    return git_utils.get_commit_message(repo, sha)


def narrow_range(repo, good_sha, bad_sha):
    """The bisect step: given current good/bad boundaries, pick the midpoint
    commit of the commits strictly between them to test next. Returns None
    if the range is already down to adjacent commits (good's immediate
    successor is bad)."""
    candidates = git_utils.rev_list_between(repo, good_sha, bad_sha)
    # candidates excludes good_sha, includes bad_sha as the last element
    interior = candidates[:-1]  # exclude bad_sha itself, which is already known-bad
    if not interior:
        return None
    mid = interior[len(interior) // 2]
    return mid


def verify(repo, candidate_sha, test_cmd, reruns=3):
    """Re-runs run_test on the candidate breaking commit and its immediate
    parent, `reruns` times each, to confirm the pass(parent)->fail(candidate)
    flip is real and not a flaky false positive. Returns a verdict plus the
    raw per-run results."""
    parent_sha = git_utils.get_parent(repo, candidate_sha)

    candidate_runs = [run_test(repo, candidate_sha, test_cmd) for _ in range(reruns)]
    parent_runs = [run_test(repo, parent_sha, test_cmd) for _ in range(reruns)]

    candidate_fail_rate = sum(1 for r in candidate_runs if not r["passed"]) / reruns
    parent_pass_rate = sum(1 for r in parent_runs if r["passed"]) / reruns

    # Majority vote per side.
    candidate_majority_fail = candidate_fail_rate > 0.5
    parent_majority_pass = parent_pass_rate > 0.5

    confirmed = candidate_majority_fail and parent_majority_pass
    flaky = 0 < candidate_fail_rate < 1 or 0 < parent_pass_rate < 1

    return {
        "candidate_sha": candidate_sha,
        "parent_sha": parent_sha,
        "candidate_fail_rate": candidate_fail_rate,
        "parent_pass_rate": parent_pass_rate,
        "confirmed": confirmed,
        "flaky": flaky,
        "candidate_runs": candidate_runs,
        "parent_runs": parent_runs,
    }


def _diff_touched_files(diff_text):
    files = set()
    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            parts = line.split()
            if len(parts) >= 4:
                files.add(parts[2][2:])
                files.add(parts[3][2:])
    return files


def explain(client, model, diff_text, test_output, commit_message, max_tokens=700):
    """Calls the LLM to produce a root-cause explanation, grounded strictly
    in the diff and test output. Rather than a single flat sentence, asks
    for an explicit causal chain -- code change -> immediate effect ->
    propagation -> assertion failure -- so the explanation reflects how the
    breakage actually propagated, not just "commit X broke it". Post-hoc
    checks that any file the explanation claims to cite actually appears in
    the diff; if not, the explanation is flagged rather than trusted
    verbatim."""
    prompt = f"""You are explaining why a specific git commit broke a test. You must ground your explanation ONLY in the diff and test output below -- never invent a cause you cannot point to in the diff.

Commit message:
{commit_message}

Diff (commit vs its parent):
```diff
{diff_text}
```

Failing test output (captured from actually running the test suite at this commit):
```
{test_output}
```

Respond with ONLY a JSON object of this exact shape:
{{
  "causal_chain": ["<step 1>", "<step 2>", "...", "<final step>"],
  "summary": "<1-3 sentence plain-language root cause>"
}}

Rules for causal_chain:
- 3 to 7 short steps (each under 14 words), ordered from the literal code
  change to the observed test failure -- e.g. "changed line X" -> "immediate
  behavioral effect" -> "how that propagates" -> "which assertion fails and why".
- The FIRST step must describe the literal change from the diff (quote or
  closely paraphrase a specific changed line).
- The LAST step must describe the specific assertion/failure from the test
  output.
- Do not invent an intermediate step you can't ground in the diff or test
  output -- a shorter, honest chain beats a longer invented one.
- Do not reference any file or function that does not appear in the diff.
"""
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = resp.content[0].text

    import json
    import re
    causal_chain = []
    summary = raw_text
    try:
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        parsed = json.loads(match.group(0))
        causal_chain = [str(s).strip() for s in parsed.get("causal_chain", []) if str(s).strip()]
        summary = str(parsed.get("summary", "")).strip() or raw_text
    except Exception:
        pass  # fall back to raw_text as the summary, empty chain

    combined_text = summary + "\n" + "\n".join(causal_chain)

    touched_files = _diff_touched_files(diff_text)
    ungrounded = False
    flag_reason = None
    # crude grounding check: if the explanation mentions a "file.py"-shaped
    # token that never appears in the diff's touched files, flag it.
    mentioned = set(re.findall(r"\b([\w./-]+\.py)\b", combined_text))
    bogus = {m for m in mentioned if not any(m in f or f.endswith(m) for f in touched_files)}
    if not causal_chain:
        ungrounded = True
        flag_reason = "model did not return a parseable causal_chain"
    elif bogus:
        ungrounded = True
        flag_reason = f"explanation references file(s) not present in the diff: {bogus}"

    return {
        "explanation": summary,
        "causal_chain": causal_chain,
        "raw_response": raw_text,
        "ungrounded": ungrounded,
        "flag_reason": flag_reason,
        "touched_files": list(touched_files),
        "usage": {
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
        },
    }


def render_causal_chain(causal_chain):
    """Renders a causal chain as an arrow diagram, e.g.:

        Changed default include_empty=True in normalize_response()
           |
           v
        API response now contains empty fields
           |
           v
        test_user_response expects previous schema
           |
           v
        Assertion fails: AssertionError: {'a': None} != {'a': 1}
    """
    if not causal_chain:
        return "(no causal chain available)"
    lines = []
    for i, step in enumerate(causal_chain):
        lines.append(step)
        if i < len(causal_chain) - 1:
            lines.append("   |")
            lines.append("   v")
    return "\n".join(lines)
