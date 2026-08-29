# Evaluation Results

Fixture suite: 10 cases (5 easy, 3 medium, 2 hard). Ground truth for every
case is the known injected-bug commit SHA baked into `fixtures/cases/*/meta.json`
by `fixtures/generate_fixtures.py`, and independently sanity-checked by
`fixtures/verify_fixtures.py`, which actually runs pytest at every boundary
commit before any agent code touches the repos.

Model: `deepseek-chat` (see README.md's "stack deviation" note — the brief's
preferred Anthropic API wasn't available as a key in this environment;
DeepSeek's OpenAI-compatible Chat Completions API was substituted 1:1
behind the same client interface).

Regenerate this table with:
```bash
export DEEPSEEK_API_KEY=sk-...
python3 bisect_agent.py eval --stage all
```

## Summary — primary outcome, test executions, wall time, cost

| Stage | Accuracy | Avg test executions/case | Avg wall time/case (s) | Avg LLM cost/case ($) |
|---|---|---|---|---|
| baseline (guess from vibes) | 60% (6/10) | 0.0 | 1.92 | 0.00007 |
| iteration 1: linear scan | 90% (9/10) | 4.5 | 1.63 | 0.00000 |
| iteration 2: binary search | 100% (10/10) | 4.0 | 1.39 | 0.00000 |
| iteration 3: + verify() | 100% (10/10) | 12.3 | 4.36 | 0.00000 |
| final: + explain() | 100% (10/10) | 12.4 | 7.30 | 0.00018 |

**Primary outcome**: the agent (final pipeline) exactly matches ground
truth on 10/10 fixtures; the baseline matches on 6/10. All of the
baseline's misses are cases where the honest culprit's commit message
doesn't sound suspicious, or a neighboring commit's message sounds *more*
suspicious than the real one (see "hard case" below).

**Test executions**: baseline runs the test suite zero times, by design —
that's the whole point of the comparison. The agent's binary-search stage
needs ~4 test runs per case to isolate a candidate on these short (4-6
commit) fixtures; `verify()`'s resampling roughly triples that to buy
confidence against flakiness.

**Cost**: tool-only stages (linear/binary/verify) make zero LLM calls — the
narrowing loop and verification are pure git + subprocess, no model in the
loop at all. Cost only appears at the baseline (one guess prompt) and the
final stage (one `explain()` call per case), both a fraction of a cent.

## Per-case detail

| Case | Difficulty | baseline | linear | binary | verify | final |
|---|---|---|---|---|---|---|
| easy_logic_flip | easy | no | YES | YES | YES | YES |
| easy_off_by_one | easy | YES | YES | YES | YES | YES |
| easy_removed_check | easy | YES | YES | YES | YES | YES |
| easy_syntax_bug | easy | YES | YES | YES | YES | YES |
| easy_wrong_return | easy | YES | YES | YES | YES | YES |
| hard_flaky_verify | hard | YES* | no | YES** | YES | YES |
| hard_misleading_message | hard | no | YES | YES | YES | YES |
| medium_changed_default | medium | no | YES | YES | YES | YES |
| medium_config_change | medium | no | YES | YES | YES | YES |
| medium_shared_helper | medium | YES | YES | YES | YES | YES |

\* the baseline got `hard_flaky_verify` right by coincidence — it never runs
the test, so it can't know the failure is flaky; it just happened to name
the right commit from the message alone.

\*\* binary search landed on the true culprit in this run, but is not
reliably immune to the flakiness — see below for a run where it wasn't,
and why `verify()` matters regardless of whether binary search gets lucky.

---

## The hard case: `hard_flaky_verify`

**Setup**: the regressing commit shortens a thread-join timeout below a
jittered worker sleep duration, so the test at and after the bug fails only
~50-60% of the time — a real, deliberately-injected flaky test, not a bug
in the fixture. `fixtures/verify_fixtures.py` samples it 8x to confirm this
is a genuine ~50% flip rate, not a fluke of one run.

**What it revealed, in two layers:**

1. **Binary search itself can be fooled.** A single test run per candidate
   means a flaky "pass" on the true breaking commit can push the good
   boundary right past it. In one observed run, the search landed on
   `b4508bf2` (the last commit in the range) as its candidate instead of
   the true culprit `f8db8df5`, purely because the midpoint sample of
   `f8db8df5` happened to pass.

2. **The first version of `verify()` caught this and then ignored itself.**
   `verify()` re-ran the wrong candidate and its parent 3x each and
   correctly reported `confirmed: false, flaky: true` — the signal was
   right there in the trajectory log. But the orchestrator's first
   implementation only *logged* that as a warning and still returned the
   unconfirmed candidate as the final answer. Confirmed-wrong, reported
   anyway. That's `eval/raw_results.json` before the fix: `hard_flaky_verify`
   wrong at every tool-using stage, baseline right by luck.

**The fix** (documented in `CHANGELOG.md`, Iteration 3 revision): when
`verify()` can't confirm and the parent commit is *also* failing more often
than not under resampling, back up one more commit and resample harder
(more reruns), up to 3 backtracks. Re-run after the fix: `hard_flaky_verify`
now resolves correctly, and a representative trajectory
(`trajectories/hard_flaky_verify.md`) shows the agent needing 3 escalating
resample rounds (3, 5, then 7 reruns) before the majority vote flips from
"can't confirm" to "confirmed: `f8db8df5` is the breaking commit" — 34 test
executions total for that one case, versus 4 for a deterministic fixture of
the same size. The cost of correctness under flakiness is explicit and
visible in the trajectory, not hidden in a retry loop.

## Hot take

An ungrounded agent will confidently name a plausible-looking commit even
when it never ran the test — that's the baseline, and it's right 60% of
the time for the wrong reason: commit messages correlate with behavior
often enough to look competent, right up until a commit is mislabeled
(`hard_misleading_message`, where the real bug hides behind "refactor:
extract email parts for readability (no behavior change)" while a scarier
"WIP: rewrite validation logic, might be buggy" commit next to it is
harmless — baseline picks the scary one, confidently, wrong). But the more
interesting failure mode showed up one layer deeper, inside the agent
itself: *forcing execution isn't sufficient either if you don't act on what
the execution tells you.* `verify()` correctly detected its own candidate
was unconfirmed and got ignored by the orchestrator that called it. The fix
wasn't a smarter prompt or a smarter model — it was making the control flow
actually branch on `confirmed: false` instead of just logging it next to a
wrong answer. Grounding isn't a property of a single tool call; it's a
property of whether the orchestrator is willing to change its answer when a
tool tells it to.
