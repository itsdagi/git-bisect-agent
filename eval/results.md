# Evaluation Results

Fixture suite: 10 cases (5 easy, 3 medium, 2 hard).

## Baseline vs. agent (primary comparison)

| Metric | Simple baseline | Agent solution | Change |
|---|---|---|---|
| Primary outcome (exact-SHA accuracy) | 60% (6/10) | 100% (10/10) | +40 points |
| Human time per task | N/A -- fully automated, no human runs either path | N/A -- fully automated | not applicable; test executions (0 -> 12.3 avg/case) is the closest proxy for effort spent |
| Cost per task | $0.00007 (one short prompt, no diff/test data) | $0.00022 (narrowing + verify make 0 LLM calls; cost is entirely the one explain() call) | +$0.00015, and buys a correct, grounded, causally-explained answer instead of a guess |

*(Format per the hackathon brief's evaluation guide. "Human time per task" doesn't apply here -- both the baseline and the agent are fully automated end to end, which is the point: nobody is bisecting by hand either way. Test executions and wall time are the more meaningful effort proxy, reported in full below.)*

## Summary

| Stage | Accuracy | Avg test executions | Avg wall time (s) | Avg LLM cost/case ($) |
|---|---|---|---|---|
| baseline | 60% (6/10) | 0.0 | 1.87 | 0.0001 |
| linear | 100% (10/10) | 4.4 | 2.28 | 0.0000 |
| binary | 90% (9/10) | 3.9 | 1.99 | 0.0000 |
| verify | 90% (9/10) | 9.9 | 5.06 | 0.0000 |
| final | 100% (10/10) | 12.3 | 8.33 | 0.0002 |

## Per-case detail

| Case | Difficulty | baseline correct | linear correct | binary correct | verify correct | final correct |
|---|---|---|---|---|---|---|
| easy_logic_flip | easy | no | YES | YES | YES | YES |
| easy_off_by_one | easy | YES | YES | YES | YES | YES |
| easy_removed_check | easy | YES | YES | YES | YES | YES |
| easy_syntax_bug | easy | YES | YES | YES | YES | YES |
| easy_wrong_return | easy | YES | YES | YES | YES | YES |
| hard_flaky_verify | hard | YES | YES | no | no | YES |
| hard_misleading_message | hard | no | YES | YES | YES | YES |
| medium_changed_default | medium | no | YES | YES | YES | YES |
| medium_config_change | medium | no | YES | YES | YES | YES |
| medium_shared_helper | medium | YES | YES | YES | YES | YES |

## Explaining the chain of failure, not just the commit

`explain()` doesn't return a single flat sentence ("commit X broke it"). It
asks the model for a structured causal chain -- code change -> immediate
effect -> propagation -> assertion failure -- each step grounded in the
diff or the captured test output, with the same post-hoc ungrounded-file
check applied to the whole chain. `agent/tools.render_causal_chain()`
renders it as an arrow diagram; both `bisect_agent.py run` and every saved
trajectory in `trajectories/` show it.

Real example, from `medium_shared_helper` -- a case picked specifically
because the bug is in a helper (`clamp()`) the tested function
(`format_price()`) calls, not in `format_price()`'s own diff:

```
Removed the `if x < lo: return lo` branch from clamp()
   |
   v
clamp() now returns x unchanged when x is below lo
   |
   v
format_price(-10) calls clamp(-10, 0, 100) and gets -10
   |
   v
format_price returns '$-10.00' instead of '$0.00'
   |
   v
test_format_price_clamps_low asserts '$0.00' but receives '$-10.00'
```

That's the difference between "a Git tool" and a debugging tool: the first
three steps are exactly the reasoning a developer has to reconstruct by
hand when the diff that broke a test doesn't visibly touch the function the
failing assertion calls. See any file in `trajectories/` for the full
JSON-backed version (`causal_chain` + `summary` + grounding flags), or
regenerate: `python3 bisect_agent.py run --repo <case>/repo --good <sha>
--bad <sha> --test-cmd "..."`.

## The hard case: `hard_flaky_verify`

**Setup**: the regressing commit shortens a thread-join timeout below a
jittered worker sleep duration, so the test at and after the bug fails only
~50-60% of the time -- a real, deliberately-injected flaky test, not a bug
in the fixture. `fixtures/verify_fixtures.py` samples it 8x to confirm this
is a genuine ~50% flip rate, not a fluke of one run.

**What it revealed, in two layers:**

1. **Binary search itself can be fooled.** A single test run per candidate
   means a flaky "pass" on the true breaking commit can push the good
   boundary right past it, landing the search on the wrong commit.

2. **The first version of `verify()` caught this and then ignored itself.**
   `verify()` re-ran the wrong candidate and its parent 3x each and
   correctly reported `confirmed: false, flaky: true` -- the signal was
   right there in the trajectory log. But the orchestrator's first
   implementation only *logged* that as a warning and still returned the
   unconfirmed candidate as the final answer. Confirmed-wrong, reported
   anyway.

**The fix** (documented in `CHANGELOG.md`, Iteration 3 revision): when
`verify()` can't confirm and the parent commit is *also* failing more often
than not under resampling, back up one more commit and resample harder
(more reruns), up to 3 backtracks. `trajectories/hard_flaky_verify.md`
shows a representative run: the search lands on the wrong candidate, the
first verify pass at 3 reruns can't confirm and sees the parent also
failing, backtracks and resamples at 5 reruns (still inconclusive), then
7 reruns -- at which point the majority vote is unambiguous and the answer
flips to the true culprit. That's real cost, paid visibly: this single case
can need 30+ test executions, an order of magnitude more than a
deterministic fixture of the same size, and the trajectory shows exactly
where each extra execution went.

This case does not converge to the right answer 100% of the time even with
the fix -- across independent runs of the eval harness, `hard_flaky_verify`
alone is the one fixture whose per-stage correctness varies run to run (see
`eval/raw_results.json` for the exact history), because 3 backtracks with
bounded resampling is a mitigation, not a guarantee, against a coin-flip
test. Widening the backtrack budget or the reruns-per-attempt would push
the odds further but never to certainty -- which is itself the honest
lesson of a deliberately flaky fixture.

## Hot take

An ungrounded agent will confidently name a plausible-looking commit even
when it never ran the test -- that's the baseline, and it's right 60% of
the time for the wrong reason: commit messages correlate with behavior
often enough to look competent, right up until a commit is mislabeled
(`hard_misleading_message`, where the real bug hides behind "refactor:
extract email parts for readability (no behavior change)" while a scarier
"WIP: rewrite validation logic, might be buggy" commit next to it is
harmless -- baseline picks the scary one, confidently, wrong). But the more
interesting failure mode showed up one layer deeper, inside the agent
itself: *forcing execution isn't sufficient either if you don't act on what
the execution tells you.* `verify()` correctly detected its own candidate
was unconfirmed and got ignored by the orchestrator that called it. The fix
wasn't a smarter prompt or a smarter model -- it was making the control flow
actually branch on `confirmed: false` instead of just logging it next to a
wrong answer. Grounding isn't a property of a single tool call; it's a
property of whether the orchestrator is willing to change its answer when a
tool tells it to. The causal-chain explanation pushes the same principle
one step further: a debugging tool that can only say *which* commit is
still asking the developer to do the reasoning; naming *why*, one traceable
step at a time, is the part that's actually hard to fake convincingly if
you didn't run the code.
