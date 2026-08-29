# Improvement Changelog

Every entry below reflects a real run against the 10-case fixture suite
(`fixtures/cases/`) via `python3 bisect_agent.py eval`. Numbers are pulled
directly from `eval/raw_results.json` produced by those runs, not estimated
after the fact.

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
