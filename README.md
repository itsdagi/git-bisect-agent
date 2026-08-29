# Bisect Agent

An agent that automates `git bisect` and explains **why** the commit broke —
not just which one.

Built for the micro1 Agentic Workflows Hackathon.

## The problem

**Who has this:** a developer who knows a test used to pass and now fails,
somewhere across a range of commits, and has to find the exact breaking
change.

**The bottleneck:** manual `git bisect` requires writing a reliable
pass/fail check and babysitting a binary search across potentially dozens of
commits. In practice people often skip it and guess from commit messages or
recent diffs instead — faster to *try*, but frequently wrong on non-obvious
regressions (a bug in a shared helper three files away from the code you'd
guess, a changed default parameter buried in an unrelated-sounding commit,
a commit message that's actively misleading about what it changed).

**What this agent does differently from `git bisect run`:** it implements
the narrowing loop itself (no shelling out and calling it done), so every
step — which commit it picked, why, what the test said — is logged and
inspectable. It then re-verifies its own answer by re-running the candidate
and its parent multiple times before trusting a pass→fail flip, because a
single test run can lie if the test is flaky. Only then does it explain the
root cause, and that explanation is required to cite specific lines from
the actual diff — never a guess it can't point to.

Two extensions build on the same core loop without touching its logic: a
GitHub Action posts the result as a PR comment automatically (no human
invokes the CLI), and an optional cross-run memory layer lets explanations
reference prior regressions in the same repo — see "CI integration" and
"Cross-run memory" below.

**Four questions, answered up front:**

| | |
|---|---|
| **Who has this problem?** | A developer (or a CI bot acting on their behalf) who knows a test regressed somewhere in a commit range and has to find the exact breaking change. |
| **What bottleneck makes it worth solving?** | Manual `git bisect` requires babysitting a binary search and writing a reliable pass/fail check; most people skip it and guess from commit messages instead — fast, and wrong on any non-obvious regression (see `hard_misleading_message` below). |
| **Does the agent solve it well?** | 100% exact-commit accuracy vs. the baseline's 60% across 10 real fixture cases, verified live on a real GitHub PR — see "Results" and "CI integration" below. |
| **Can another person reproduce the result?** | Yes — [`REPRODUCE.md`](REPRODUCE.md) gives exact commands from a clean clone, plus a real already-open PR a judge can read without running anything. |

## Architecture

```
bisect_agent.py run --repo <path> --good <sha> --bad <sha> --test-cmd "..."
                                    |
                    agent/orchestrator.py  (the bisect loop, explicit)
                                    |
              +---------------------------------------------+
              |                agent/tools.py                |
              |  run_test | get_diff | get_commit_message    |
              |  narrow_range | verify | explain              |
              +---------------------------------------------+
                                    |
                    agent/git_utils.py  (git worktree plumbing)
                                    |
                    disposable `git worktree add` per test run
                    (the caller's checkout is never touched)
```

**The loop** (`agent/orchestrator.py`):
1. Confirm the given good/bad boundaries actually bracket a regression.
2. Narrow: either a plain linear scan (`--strategy linear`) or real binary
   search via `narrow_range` (`--strategy binary`, the default) — each step
   runs the test suite in a fresh disposable worktree via `run_test`.
3. Verify: re-run the candidate and its immediate parent multiple times each
   (`verify`). If the flip can't be confirmed and the parent itself looks
   inconsistent, **backtrack one commit and resample harder** — up to 3
   times — rather than reporting an unconfirmed answer as if it were
   confident. (This backtrack step is the one substantive fix that came out
   of running the hard fixture — see `CHANGELOG.md`.)
4. Explain: fetch the diff and commit message for the confirmed commit, ask
   the model for a **causal chain** — code change -> immediate effect ->
   propagation -> assertion failure — not just a flat "commit X broke it"
   sentence, grounded in that diff and the actual captured test output. A
   post-hoc check flags the whole chain if it references a file that never
   appears in the diff. Rendered as an arrow diagram in the CLI and every
   trajectory file, e.g. (from `medium_shared_helper`, where the bug is in
   a helper the tested function calls, not in its own diff):
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

Every tool call — input, result, and the orchestrator's next decision — is
logged to a structured JSONL file per run (`agent/trajectory.py`), rendered
to human-readable markdown in `trajectories/`.

**The baseline** (`agent/baseline.py`, `bisect_agent.py baseline`): a single
LLM prompt given the commit range, every commit message in it, and the
failing test name — no diff, no execution, no tools. This is the "guess
from vibes" comparison point.

**Where the instructions live:** every prompt that shapes the agent's
behavior is inline in source, not a separate config a reader has to hunt
for — the `explain()` prompt (causal chain + confidence + memory rules) is
in `agent/tools.py`, the baseline's guess-from-commit-messages prompt is in
`agent/baseline.py`.

## CI integration

`.github/workflows/bisect-agent.yml` runs the same pipeline automatically —
no human invokes the CLI. It fires on `workflow_run` (whenever the repo's
own test workflow completes with `conclusion: failure`) or on
`workflow_dispatch` (manual trigger, for demos and reproduction). It reuses
`agent.orchestrator.run_agent` directly (`ci/post_comment.py` imports and
calls it — no bisect logic is duplicated), then posts or updates a single
PR comment with the culprit commit (linked), confidence level, causal chain
of failure, and a collapsed trajectory log; the full trajectory JSON is
also uploaded as a workflow artifact. Reruns update the same comment in
place (a hidden HTML marker identifies it) rather than stacking duplicates.

**Ground rule compliance:** the workflow's `permissions:` block grants only
`contents: read`, `pull-requests: write`, `issues: write` — it can checkout
and post/edit one comment, and nothing else. It never pushes a commit,
merges, reverts, or modifies the PR in any way, which is what keeps this
outside the "consequential action needs human approval" concern: it's
informational only, by construction, not by convention.

**Live, real demo:** [itsdagi/bisect-agent-ci-demo#1](https://github.com/itsdagi/bisect-agent-ci-demo/pull/1)
is a real open PR (base `main`, head `add-perf-tweak`) with an injected bug
— `clamp()` silently loses its lower-bound check. Its `Tests` check fails,
which triggered `Bisect Agent` automatically, which posted a real comment:
[the actual comment](https://github.com/itsdagi/bisect-agent-ci-demo/pull/1#issuecomment-5461903445) —
culprit commit `0075704f` (correct), **High** confidence, a 5-step causal
chain, 9 test executions. See `REPRODUCE.md`'s CI section for exact steps
to reproduce this from a clean fork, including the `workflow_dispatch`
manual-trigger path a judge can use without waiting on a real failure.

Copy `.github/workflows/bisect-agent.yml` plus a `.bisect-agent.yml`
(`test_cmd`, optional `setup_cmd` for installing your test deps, optional
`path_filters`) into any repo to reuse this — the workflow pulls `agent/`
and `ci/` from this repo at run time (pinned via `BISECT_AGENT_REF`), so
you don't vendor anything.

## Cross-run memory

Optional (`bisect_agent.py run --memory`, off by default). `agent/memory.py`
keeps an append-only `.bisect-agent/history.jsonl` per repo. A new tool,
`query_history(files_touched)`, is called **only after `verify()` has
confirmed the culprit commit** — `narrow_range()`, `run_test()`, and
`verify()` have no knowledge this module exists, so diagnosis stays 100%
grounded in actual test execution; memory is a narrative layer applied
after the fact, never a substitute for verification. If a prior confirmed
regression touched the same file(s), `explain()` gets that context and can
name the repeat pattern in a discrete `history_note` field (not just prose
it might skip — see `CHANGELOG.md` for why that distinction mattered in
practice).

**Demo:** `fixtures/cases/memory_repeat_bug/` — one repo, the same
"missing-null-check" bug class introduced twice, at two different points in
its history, in two different functions. `eval/demo_memory.py` runs the
agent twice in sequence against it; run 2's explanation:

> "This is the second missing-null-check regression in this repo; the
> first was in get_user_email."

Full output for both runs: [`eval/memory_demo.md`](eval/memory_demo.md).

**Future work, explicitly not built:** persisting history across CI runs.
GitHub Actions runners are ephemeral, so `.bisect-agent/history.jsonl`
doesn't survive between workflow runs without extra wiring (a bot commit,
or `actions/cache`). The CI workflow runs with `do_memory=False` for this
reason — treated as a stretch goal rather than something rushed and left
half-working.

## What's original vs. a thin wrapper

- **Original**: the orchestrator and its bisect/backtrack control flow
  (`agent/orchestrator.py`), all tool implementations (`agent/tools.py`,
  `agent/memory.py`), the git worktree plumbing (`agent/git_utils.py`), the
  trajectory logger (`agent/trajectory.py`), the baseline guesser
  (`agent/baseline.py`), the LLM client adapter (`agent/llm.py`), the CI
  integration (`ci/config.py`, `ci/github_api.py`, `ci/post_comment.py`,
  `.github/workflows/bisect-agent.yml`), the fixture generator and its 11
  declarative bug-injection cases (`fixtures/case_defs.py`,
  `fixtures/memory_case.py`, `fixtures/generate_fixtures.py`,
  `fixtures/generate_memory_fixture.py`, `fixtures/verify_fixtures.py`),
  and the eval harness (`eval/run_eval.py`, `eval/demo_memory.py`).
- **Thin wrapper over existing tools**: `git` itself (via `subprocess` and
  `git worktree`), the LLM API (DeepSeek's OpenAI-compatible Chat
  Completions endpoint, called directly over HTTP — no agent framework),
  and the GitHub REST API (`ci/github_api.py`, also stdlib HTTP only).

## Stack deviation from the brief

The brief's stack preference is the Anthropic API. This environment had no
`ANTHROPIC_API_KEY` available, only a DeepSeek key. DeepSeek's API is
OpenAI-Chat-Completions-shaped; `agent/llm.py` wraps it behind an
Anthropic-Messages-shaped interface (`client.messages.create(...)` ->
`resp.content[0].text` / `resp.usage.input_tokens`), so the rest of the
codebase (`baseline.py`, `orchestrator.py`, `tools.py`) is written against
one interface and would work unchanged against the real Anthropic API by
swapping `get_client()`'s implementation — `anthropic.Anthropic(...)` is
already stubbed in as a fallback path if `ANTHROPIC_API_KEY` is set instead.
Model used for the numbers in this repo: `deepseek-chat`.

## Results

| Stage | Accuracy | Avg test executions/case | Avg wall time/case (s) | Avg LLM cost/case ($) |
|---|---|---|---|---|
| baseline (guess from vibes) | 60% (6/10) | 0.0 | 1.87 | 0.0001 |
| iteration 1: linear scan | 100% (10/10) | 4.4 | 2.28 | 0.0000 |
| iteration 2: binary search | 90% (9/10) | 3.9 | 1.99 | 0.0000 |
| iteration 3: + verify() | 90% (9/10) | 9.9 | 5.06 | 0.0000 |
| final: + explain() (causal chain) | 100% (10/10) | 12.3 | 8.33 | 0.0002 |

Per-stage accuracy on `hard_flaky_verify` (the deliberately flaky fixture)
varies a few points run to run by design — see `eval/results.md`'s hard-case
section for why that's the honest outcome of a coin-flip test and a bounded
mitigation, not a bug.

Full per-case breakdown, the hard-case writeup, and a hot take on what it
revealed: [`eval/results.md`](eval/results.md). Build-stage-by-stage
narrative with evidence: [`CHANGELOG.md`](CHANGELOG.md). Exact commands to
reproduce: [`REPRODUCE.md`](REPRODUCE.md). Demo video beats:
[`DEMO_SCRIPT.md`](DEMO_SCRIPT.md).

## How this maps to the judging rubric

| Criterion | Points | Where the evidence lives |
|---|---|---|
| Problem & User Value | 15 | "The problem" above; "Four questions" table |
| Agent Solution & Engineering | 30 | "Architecture" above (explicit narrowing loop, verify+backtrack, grounded explain, memory gated after verification, CI reusing the same orchestrator with zero duplicated logic) |
| End to End Quality | 20 | Live posted PR comment ([itsdagi/bisect-agent-ci-demo#1](https://github.com/itsdagi/bisect-agent-ci-demo/pull/1)); real trajectories in `trajectories/`; nothing here is a mockup or a simulated result |
| Measured Improvement | 15 | `eval/results.md`'s baseline-vs-agent table (60% → 100%, primary-metric format); `CHANGELOG.md`'s stage-by-stage table with real evidence per row |
| Reproducibility | 15 | `REPRODUCE.md` — exact commands, expected output, runtime, cost, for the solution, the baseline, the eval harness, and the live CI path |
| Hot Take / Insights | 5 | `CHANGELOG.md`'s "Main failure mode" + "Hot take" sections |

## Ground rules this build follows

Numbered to match the hackathon brief's own list:

1. Built with known, ordinary tools — `git`, Python `subprocess`, a plain
   HTTP call to an LLM API. No unfamiliar or opaque components.
2. What existed before this project: nothing — `git`, DeepSeek/Anthropic's
   APIs, and GitHub's API are the only external dependencies (see "What's
   original vs. a thin wrapper" below for the precise line).
3. `git`, DeepSeek, GitHub Actions, and the GitHub REST API are all used
   within their documented, intended usage (read/checkout/test-run for git;
   standard chat-completion calls; standard Action triggers and comment
   endpoints for GitHub).
4. **Consequential actions are sandboxed, and the one automated action that
   exists needs no separate approval gate because it cannot be
   consequential by construction:** the CI workflow's `permissions:` block
   grants only `contents: read`, `pull-requests: write`, `issues: write` —
   it can checkout and post/edit one comment, nothing else. It never
   pushes, merges, reverts, or modifies any code or branch. Locally, every
   test execution runs in a disposable `git worktree` (`agent/git_utils.py`)
   torn down immediately after; the caller's working tree is never touched,
   and there is no code path that resets, force-pushes, or deletes anything.
5. The agent's output is explicitly advisory — a PR comment naming a likely
   culprit with a stated confidence level, not an automatic fix, revert, or
   merge. A human decides what to do with it.
6. Use case (finding a regressing commit in one's own codebase) is
   unambiguously legal and ethical; nothing here processes personal data.
7. All fixture data is synthetic, generated by `fixtures/generate_fixtures.py`
   and `fixtures/generate_memory_fixture.py` from declarative definitions in
   `fixtures/case_defs.py` / `fixtures/memory_case.py` — no real codebases,
   no real people, no scraped data anywhere in this project.
8. No credentials or private data anywhere in the repo — verified by
   grepping the full working tree and git history before submission.
   `.gitignore` excludes `.env`; API keys are read from environment
   variables (`agent/llm.py`) or GitHub Actions secrets (`ci/post_comment.py`),
   never hardcoded.
9. Every accuracy, cost, and timing number in `README.md`, `CHANGELOG.md`,
   and `eval/results.md` is pulled directly from `eval/raw_results.json` or
   a linked live artifact (a real posted PR comment, a real workflow run) —
   nothing is estimated or asserted without a file or link backing it.
10. `REPRODUCE.md` gives exact commands from a clean clone for the baseline,
    the agent, the full eval harness, and the live CI path; the demo PR
    ([itsdagi/bisect-agent-ci-demo#1](https://github.com/itsdagi/bisect-agent-ci-demo/pull/1))
    is public and requires no setup to read.

## Layout

```
bisect_agent.py          CLI entrypoint (run / baseline / eval)
agent/
  orchestrator.py         the bisect loop, verify/backtrack, explain, memory wiring
  tools.py                run_test/get_diff/get_commit_message/narrow_range/verify/explain
                           + query_history/record_history wrappers
  memory.py                cross-run memory store (constraint documented at the top)
  git_utils.py            worktree + git plumbing
  trajectory.py           structured JSONL logger + markdown renderer
  baseline.py             single-prompt commit-message guesser
  llm.py                  LLM client adapter (DeepSeek, Anthropic fallback)
ci/
  post_comment.py          CI entrypoint: runs run_agent(), renders/upserts the PR comment
  config.py                 loads .bisect-agent.yml (test_cmd, setup_cmd, path_filters)
  github_api.py             stdlib-only GitHub REST client (comment upsert, PR lookup)
.github/workflows/
  bisect-agent.yml          the reusable GitHub Action (workflow_run + workflow_dispatch)
fixtures/
  case_defs.py             declarative definitions of the 10 accuracy-eval cases
  memory_case.py            declarative definition of the memory demo fixture
  generate_fixtures.py     builds the 10 throwaway git repos + meta.json
  generate_memory_fixture.py  builds the memory demo repo + its two-range meta.json
  verify_fixtures.py       sanity-checks ground truth by actually running pytest
  cases/<name>/repo/       generated git repos (gitignored, not committed --
                           nested .git dirs don't survive a clone as plain
                           files; regenerated deterministically instead, see
                           REPRODUCE.md)
  cases/<name>/meta.json   ground truth SHAs, difficulty, test command
eval/
  run_eval.py              drives every accuracy stage across all 10 fixtures
  demo_memory.py            runs the agent twice against memory_repeat_bug, writes memory_demo.md
  results.md               auto-generated tables + persisted narrative (below)
  _narrative.md            hard-case writeup + hot take, appended to results.md
                           on every eval run so it survives reruns
  memory_demo.md            real two-run output demonstrating memory's effect on explain()
  raw_results.json          machine-readable per-case results
trajectories/              one rendered trajectory per representative case,
                           plus ci_live_run.md -- a real trajectory pulled
                           from an actual GitHub Actions run's artifact
CHANGELOG.md               stage-by-stage build log with real evidence
REPRODUCE.md               exact setup + run commands from a clean clone, incl. CI
```
