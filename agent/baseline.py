"""
Baseline: "guess from vibes". A single LLM prompt given the commit range,
every commit message in it, and the failing test name -- and NOTHING else.
No diff, no test execution, no tools. This is the comparison point the
agent is measured against.
"""
import json
import re
import time

from . import git_utils
from .llm import DEFAULT_MODEL, cost_usd


def run_baseline(client, repo, good_sha, bad_sha, test_name, model=DEFAULT_MODEL):
    shas = git_utils.rev_list_between(repo, good_sha, bad_sha)
    messages = []
    for sha in shas:
        info = git_utils.get_commit_message(repo, sha)
        messages.append(f"{sha[:10]}  {info['subject']}")

    prompt = f"""A test named `{test_name}` used to pass and is now failing somewhere in this range of commits. You do NOT have access to the diffs or the ability to run the test -- only the commit messages below, oldest first. Guess which single commit introduced the bug.

Commits (oldest first):
{chr(10).join(messages)}

Respond with ONLY a JSON object: {{"sha": "<full 40-char sha or the closest prefix you were given>", "reasoning": "<one sentence>"}}
"""
    t0 = time.time()
    resp = client.messages.create(
        model=model,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    duration = time.time() - t0
    text = resp.content[0].text

    guess_sha = None
    reasoning = None
    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        parsed = json.loads(match.group(0))
        guess_prefix = parsed.get("sha", "").strip()
        reasoning = parsed.get("reasoning")
        for sha in shas:
            if sha.startswith(guess_prefix) or guess_prefix.startswith(sha[:10]):
                guess_sha = sha
                break
    except Exception:
        pass

    return {
        "guess_sha": guess_sha,
        "reasoning": reasoning,
        "raw_response": text,
        "duration_s": round(duration, 3),
        "usage": {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens},
        "cost_usd": cost_usd(model, resp.usage.input_tokens, resp.usage.output_tokens),
        "test_executions": 0,
    }
