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
   the model for a plain-language root cause grounded in that diff and the
   actual captured test output. A post-hoc check flags the explanation if it
   references a file that never appears in the diff.

Every tool call — input, result, and the orchestrator's next decision — is
logged to a structured JSONL file per run (`agent/trajectory.py`), rendered
to human-readable markdown in `trajectories/`.

**The baseline** (`agent/baseline.py`, `bisect_agent.py baseline`): a single
LLM prompt given the commit range, every commit message in it, and the
failing test name — no diff, no execution, no tools. This is the "guess
from vibes" comparison point.

## What's original vs. a thin wrapper

- **Original**: the orchestrator and its bisect/backtrack control flow
  (`agent/orchestrator.py`), all six tool implementations
  (`agent/tools.py`), the git worktree plumbing (`agent/git_utils.py`), the
  trajectory logger (`agent/trajectory.py`), the baseline guesser
  (`agent/baseline.py`), the LLM client adapter (`agent/llm.py`), the
  fixture generator and its 10 declarative bug-injection cases
  (`fixtures/case_defs.py`, `fixtures/generate_fixtures.py`,
  `fixtures/verify_fixtures.py`), and the eval harness
  (`eval/run_eval.py`).
- **Thin wrapper over existing tools**: `git` itself (via `subprocess` and
  `git worktree`), and the LLM API (DeepSeek's OpenAI-compatible Chat
  Completions endpoint, called directly over HTTP — no agent framework).

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
| baseline (guess from vibes) | 60% (6/10) | 0.0 | 1.92 | 0.00007 |
| iteration 1: linear scan | 90% (9/10) | 4.5 | 1.63 | 0.00000 |
| iteration 2: binary search | 100% (10/10) | 4.0 | 1.39 | 0.00000 |
| iteration 3: + verify() | 100% (10/10) | 12.3 | 4.36 | 0.00000 |
| final: + explain() | 100% (10/10) | 12.4 | 7.30 | 0.00018 |

Full per-case breakdown, the hard-case writeup, and a hot take on what it
revealed: [`eval/results.md`](eval/results.md). Build-stage-by-stage
narrative with evidence: [`CHANGELOG.md`](CHANGELOG.md). Exact commands to
reproduce: [`REPRODUCE.md`](REPRODUCE.md).

## Ground rules this build follows

- Everything operates on throwaway fixture repos generated by
  `fixtures/generate_fixtures.py` (`fixtures/cases/*/repo`) or disposable
  `git worktree` checkouts torn down after every test run. No mutation of
  the caller's working tree, no force-push, no branch deletion, no
  destructive git operations anywhere in the codebase — read, checkout-to-
  worktree, and test-run only.
- No credentials or private data in the repo. Fixtures are synthetic
  (`fixtures/case_defs.py`); `.gitignore` excludes `.env`.
- MIT license (`LICENSE`).

## Layout

```
bisect_agent.py          CLI entrypoint (run / baseline / eval)
agent/
  orchestrator.py         the bisect loop, verify/backtrack, explain wiring
  tools.py                the six discrete tools
  git_utils.py            worktree + git plumbing
  trajectory.py           structured JSONL logger + markdown renderer
  baseline.py             single-prompt commit-message guesser
  llm.py                  LLM client adapter (DeepSeek, Anthropic fallback)
fixtures/
  case_defs.py             declarative definitions of the 10 fixture cases
  generate_fixtures.py     builds the throwaway git repos + meta.json
  verify_fixtures.py       sanity-checks ground truth by actually running pytest
  cases/<name>/repo/       generated git repos (gitignored, not committed --
                           nested .git dirs don't survive a clone as plain
                           files; regenerated deterministically instead, see
                           REPRODUCE.md)
  cases/<name>/meta.json   ground truth SHAs, difficulty, test command
eval/
  run_eval.py              drives every stage across all fixtures
  results.md               the comparison table + hard-case writeup
  raw_results.json          machine-readable per-case results
trajectories/              one rendered trajectory per representative case
CHANGELOG.md               stage-by-stage build log with real evidence
REPRODUCE.md               exact setup + run commands from a clean clone
```
