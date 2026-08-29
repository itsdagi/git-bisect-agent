# Improvement Changelog

Every entry below reflects a real run against the 10-case fixture suite
(`fixtures/cases/`) via `python3 bisect_agent.py eval`, or (for the CI and
memory extensions) a real live run against a real repo. Numbers are pulled
directly from `eval/raw_results.json` / linked live artifacts, not estimated
after the fact.

## At a glance

| Stage | What you tried and why | Evidence | Decision / learning |
|---|---|---|---|
| Baseline | Single LLM prompt: commit range + every commit message + failing test name. No diff, no execution. | 60% (6/10) accuracy, 0 test executions, ~$0.00007/case | Established the starting point — right often enough to look competent, wrong with high confidence on misleading commits |
| Iteration 1 | Gave the agent `run_test`; plain linear scan, oldest commit first, stop at first failure | 90% (9/10), 4.5 test executions/case | Kept as a selectable strategy (`--strategy linear`); missed the deliberately flaky fixture |
| Iteration 2 | Replaced linear scan with real binary search via `narrow_range` — hand-rolled, not `git bisect run` | 100% (10/10) this run, 4.0 test executions/case (drop grows with range length) | Kept as default — but a single test run per candidate is still not immune to a flaky midpoint sample |
| Iteration 3 | Added `verify()`: re-run candidate + parent multiple times before trusting a flip | First cut: still 90% (9/10) — `verify()` correctly flagged `confirmed: false` and the orchestrator reported the wrong answer anyway | Revised: added backtrack-and-resample loop. Re-run: 100% (10/10), 12.3 test executions/case. The single most important fix in the build — see "Main failure mode" below |
| Final | Added `explain()`, strictly grounded in the diff + test output, with a post-hoc ungrounded-file check | 100% maintained, 12.4 test executions/case, ~$0.0002/case, 0 flagged ungrounded | Kept, shipped as the default pipeline |
| Post-final | Replaced the flat one-sentence explanation with a structured causal chain (code change → effect → propagation → assertion) | 100% maintained, 0 chains flagged ungrounded; real example in `eval/results.md` | Kept — turns "which commit" into a chain a developer can actually follow |
| Extension 1 | Added CI integration: `.github/workflows/bisect-agent.yml` reuses `run_agent` unchanged, posts/updates one PR comment | Live: [real posted comment](https://github.com/itsdagi/bisect-agent-ci-demo/pull/1#issuecomment-5461903445) on a real PR — correct culprit, High confidence | Kept. First live run surfaced a real gap (target repo's test deps weren't installed) — fixed with a `setup_cmd` config option, now permanent |
| Extension 2 | Added cross-run memory: `query_history()` (only ever called after `verify()` confirms a culprit) + `record_history()`, feeding `explain()`'s narration only | Two-run demo on `fixtures/cases/memory_repeat_bug/`: run 2 correctly names run 1's regression — see `eval/memory_demo.md` | Kept. Prose-based callback silently failed to fire reliably; moved to a structured `history_note` JSON field, which fires reliably |

Full detail for every entry, including numbers before/after each fix, is below.

---

### Stage 0 — Baseline: single-prompt commit-message guesser

**What & why:** Give an LLM the commit range, every commit message in it,
and the failing test name — nothing else. No diff, no execution. This is
the "guess from vibes" comparison point the brief asks for.

**Evidence:** 60% accuracy (6/10), 0 test executions (by construction),
~1.9s and ~$0.00007/case.

**Decision:** Kept as the permanent comparison baseline (`bisect_agent.py
baseline`). It's right more often than pure chance because several fixtures
have honest, on-the-nose commit messages — but it silently reasons from
vibes, and the `hard_misleading_message` case (below) shows exactly how
that fails.

---

### Iteration 1 — Give the agent `run_test`, plain linear scan

**What & why:** Add real test execution. Walk every commit from good to bad,
oldest first, stop at the first failure. No search efficiency yet — the
point of this stage was just proving the tool actually works end-to-end in
disposable worktrees.

**Evidence:** 90% accuracy (9/10), average 4.5 test executions/case, ~1.6s
average. The one miss was `hard_flaky_verify` — a single linear pass with
no resampling has no defense against a flaky test (see Iteration 3).

**Decision:** Kept as a selectable strategy (`--strategy linear`) for
comparison, superseded by binary search as the default.

---

### Iteration 2 — Real binary-search narrowing via `narrow_range`

**What & why:** Replace the linear walk with an explicit bisect loop:
`narrow_range` picks the midpoint of the current good/bad boundary, the
agent runs it, and the boundary shrinks by half each step. This is hand-rolled
(not a call to `git bisect run`) so every step is inspectable in the
trajectory log.

**Evidence:** 100% accuracy (10/10) — one case (`hard_flaky_verify`) that a
single-shot linear scan missed got fixed here on this particular run; see
`hard_flaky_verify.md` for a trajectory where the search still gets
misled by a flaky midpoint sample, which is exactly why Iteration 3 exists.
Average test executions dropped to 4.0/case (from 4.5 for linear) — a
modest drop here because these fixtures are short (4-6 commits), but the
drop grows logarithmically with range length; on a 100-commit range linear
would need up to 100 test runs vs. ~7 for binary search.

**Decision:** Kept as the default strategy. Binary search is not
inherently immune to a flaky boundary sample — it can just as easily
misclassify a midpoint as "good" from one lucky pass, silently shifting
the search past the real regression. That failure mode motivated Iteration 3.

---

### Iteration 3 — Add `verify()` after landing on a candidate

**What & why:** Re-run the candidate breaking commit and its immediate
parent multiple times each before trusting the result, specifically to
catch a false positive from a flaky test. First implementation only
*flagged* a failed confirmation (logged a warning) and still reported the
unconfirmed candidate — which turned out to be a real bug, not just a
caveat: `hard_flaky_verify`, designed to expose exactly this, still came
back wrong even after `verify()` correctly said `confirmed: false`.

**Evidence (before the fix):** binary+verify still 90% (9/10) —
`hard_flaky_verify` wrong, with `verify()`'s own trajectory showing
`confirmed=false, flaky=true` logged right next to the wrong final answer.
**Evidence (after the fix):** added a bounded backtrack-and-resample loop —
when `verify()` can't confirm and the parent itself looks like it's still
failing, back up one more commit and resample with more reruns (up to 3
backtracks). Re-run: 100% accuracy (10/10), average 12.3 test
executions/case (up from 4.0, the expected cost of resampling for
confidence), ~4.4s average.

**Decision:** Kept, revised. The lesson: a verify step that only *reports*
uncertainty isn't a verify step, it's a warning label. The orchestrator has
to act on a failed confirmation, not just log it. This is the single most
important fix in the whole build — see `eval/results.md` for the detailed
write-up of the `hard_flaky_verify` trajectory.

---

### Final — Add `explain()`, grounded strictly in the diff/test output

**What & why:** Generate a plain-language root-cause explanation from the
diff and the actual failing test output. Post-hoc grounding check: if the
explanation names a file that never appears in the fetched diff, it's
flagged as ungrounded rather than trusted.

**Evidence:** 100% accuracy maintained (identification happens before
`explain()` runs, so it doesn't change correctness), average 12.4 test
executions/case, ~7.3s average (up from ~4.4s — the added LLM call), ~$0.0002
LLM cost/case (up from ~$0 for the tool-only stages, which make zero LLM
calls). 0 explanations were flagged as ungrounded across the 10 cases in
the final run. See `eval/results.md` for two representative explanations
(one easy, one where the bug is in a shared helper the tested function
never directly mentions).

**Decision:** Kept, shipped as the default full pipeline
(`bisect_agent.py run`).

---

### Post-final — Causal chain, not a flat sentence

**What & why:** a one-sentence explanation still leaves the developer to
reconstruct *how* the change propagated to the assertion, especially on
the `medium_*` fixtures where the bug is in a helper the failing test never
mentions. Changed `explain()` to return a structured JSON causal chain
(3-7 short steps, first step = the literal diff line, last step = the
specific assertion) instead of prose alone, rendered as an arrow diagram
(`agent/tools.render_causal_chain()`) in the CLI output and every
trajectory. The existing ungrounded-file check now runs against the whole
chain, not just a paragraph.

**Evidence:** re-ran the full suite after the change — accuracy unaffected
(identification happens before `explain()` runs; final stage stayed
100%/10/10 across the rerun), 0 chains flagged as ungrounded. See
`eval/results.md`'s "chain of failure" section for a full real example
(`medium_shared_helper`), where the chain correctly surfaces the
intermediate `clamp()` helper step that a flat explanation would have
either skipped or hand-waved.

**Decision:** Kept, shipped as the default `explain()` behavior. Requested
directly by the user mid-build as a way to make the final answer legible as
reasoning rather than a lookup result — the causal chain is what actually
turns this from "a Git tool" into a debugging tool, per the brief's own
framing.

---

### Extension 1 — CI integration: no human invokes the CLI

**What & why:** the whole pipeline was still something a human had to
remember to run manually. Added `.github/workflows/bisect-agent.yml`
(fires on a failing test workflow via `workflow_run`, or manually via
`workflow_dispatch`) and `ci/post_comment.py`, which reuses
`agent.orchestrator.run_agent` unchanged — no bisect logic was
duplicated — and posts/updates a single PR comment (culprit, confidence,
causal chain, collapsed trajectory). Also added a `confidence` field
(High/Medium/Low/Unverified) to `explain()`'s output, computed from how
cleanly `verify()` confirmed the candidate, surfaced in both the CLI and
the PR comment.

**Evidence:** went fully live — created
[itsdagi/git-bisect-agent](https://github.com/itsdagi/git-bisect-agent) (this
repo) and a separate demo fixture repo,
[itsdagi/bisect-agent-ci-demo](https://github.com/itsdagi/bisect-agent-ci-demo),
with a real injected bug (`clamp()` loses its lower-bound check) on a PR
against `main`. Opening that PR made its `Tests` workflow fail, which
triggered `Bisect Agent` automatically. The real, live comment it posted:
[PR #1, comment](https://github.com/itsdagi/bisect-agent-ci-demo/pull/1#issuecomment-5461903445)
— culprit commit `0075704f` (the actual injected bug), **High** confidence,
a 5-step causal chain, 9 test executions, full trajectory attached both
inline (collapsed) and as a workflow artifact.

The first live run surfaced a real bug worth recording: the CI runner only
has the bisect-agent *tool's* own deps installed (`anthropic`, `pyyaml`),
not the target repo's -- so every `run_test()` call failed identically with
"no module named pytest", and the agent correctly but uselessly reported
*that* as the culprit instead of the actual regression. Fixed by adding an
optional `setup_cmd` to `.bisect-agent.yml` (e.g. `pip install pytest`),
run once before bisecting starts. The comment above is from the corrected
run, after that fix landed.

**Decision:** Kept. `setup_cmd` config option kept as a permanent, documented
part of `.bisect-agent.yml` (not a one-off patch) since any real target repo
will hit the same gap. CI-persisted memory (writing `.bisect-agent/history.jsonl`
back via a bot commit or `actions/cache` so it survives ephemeral runners)
explicitly NOT built — see README.md's "future work" note; the CI workflow
runs with `do_memory=False`.

---

### Extension 2 — Cross-run memory: explanations reference prior regressions

**What & why:** even a grounded, causal explanation restarts from zero every
run. Added `agent/memory.py` (append-only `.bisect-agent/history.jsonl` per
repo) and two tools: `query_history(files_touched)`, called **only after**
`verify()` has confirmed a culprit — `narrow_range()`, `run_test()`, and
`verify()` have no knowledge memory exists, so diagnosis stays 100% grounded
in actual execution — and `record_history(...)`, which appends the
confirmed result. `explain()` gained a `root_cause_tag` field (a short
freeform classification like `missing-null-check`) and an optional
`history_note` field, populated only when a prior entry is genuinely the
same bug class. Off by default (`do_memory=False`) so it never touches the
existing 10-fixture accuracy suite; opt in via `bisect_agent.py run --memory`.

**Evidence:** built `fixtures/cases/memory_repeat_bug/` specifically for
this — one repo, the same "missing-null-check" bug class introduced twice
at two different points in its history, in two different functions
(`get_user_email`, then later `get_user_phone`). Ran the agent twice via
`eval/demo_memory.py`, in order, against the same repo:
- Run 1 (cold history): identified the `get_user_email` regression
  correctly, tagged `missing-null-check`, `history_note: null`.
- Run 2 (run 1's entry now in history): identified the `get_user_phone`
  regression correctly (diagnosis unaffected, same pipeline), tagged
  `missing-null-check`, and **`history_note`: "This is the second
  missing-null-check regression in this repo; the first was in
  get_user_email."**

Full output for both runs: `eval/memory_demo.md`.

One iteration was needed to get here: the first prompt design asked the
model to weave the callback into free prose ("if relevant, mention this in
your summary"), and it silently didn't — both runs independently assigned
the same `root_cause_tag` (a good sign the tag itself is meaningful) but
run 2's prose never explicitly named run 1. Fix: moved the callback out of
prose entirely into its own required-or-null structured JSON field
(`history_note`), which the model reliably fills in when a prior entry
actually matches and reliably leaves `null` when it doesn't invent a false
connection.

**Decision:** Kept. Structured `history_note` field over prose narration —
the model complies with "fill in this field or leave it null" far more
reliably than "mention this if relevant" buried in a paragraph. CI
persistence (surviving ephemeral runners) explicitly deferred, see
README.md.

---

## Main failure mode

**A component that correctly detects its own uncertainty is worthless if
nothing downstream acts on that signal.** The first version of `verify()`
did exactly what it was supposed to: it re-ran the candidate and its
parent, saw inconsistent results, and returned `confirmed: false`. The bug
wasn't in detection — it was that the orchestrator treated an unconfirmed
verification as a warning to log, not a reason to keep looking. It reported
the wrong commit with a caveat attached, which is the worst of both worlds:
wrong, but *sounds* careful. The fix wasn't a smarter prompt or a better
model call — it was making control flow actually branch on `confirmed:
false` (backtrack, resample, repeat) instead of proceeding past it. The
same shape of failure showed up again in CI, one layer up the stack: the
first live run correctly executed `run_test()` at every candidate, got a
consistent signal ("no module named pytest" at every commit), and
confidently reported a plausible-sounding culprit anyway — because nothing
checked that the signal itself was meaningful before trusting it. Grounding
isn't a property of one tool call; it's a property of whether the system
around it is willing to change its answer, or its plan, when a tool tells
it something is wrong.

## Hot take

An ungrounded agent will confidently name a plausible-looking commit even
when it never ran the test — that's the baseline, right 60% of the time for
the wrong reason, and wrong with total confidence on `hard_misleading_message`
because a scarier-sounding neighboring commit message outweighs the boring,
honest one. But "run the test" turned out to be necessary and not
sufficient. Two separate components in this build — `verify()` in the core
loop, and the CI runner's environment check that didn't exist — each
produced a correct, honest signal that something was wrong, and each time
the surrounding system ignored it and reported an answer anyway. The
practical lesson: building a more reliable agent isn't primarily about
better prompts or bigger models, it's about auditing every point where the
system *could* discover it's wrong and checking that discovery actually
changes what happens next. A verify step nobody listens to is decoration.
