# Reproducing this from a clean clone

## Setup

```bash
git clone <this-repo> git-bisect-agent
cd git-bisect-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` lists just what's imported: `anthropic` (only used if you
have an `ANTHROPIC_API_KEY` instead of DeepSeek — see below).

Set your API key. This project prefers a DeepSeek key (what it was built and
measured with); it falls back to a real Anthropic key if that's what you
have:

```bash
export DEEPSEEK_API_KEY=sk-...
# or:
export ANTHROPIC_API_KEY=sk-ant-...
```

## Generate the fixtures

`fixtures/cases/*/repo/` are real git repos, generated (not committed --
nested `.git` directories don't survive a clone as plain files; git would
either refuse them or silently record them as broken gitlinks). Generation
is deterministic (fixed commit dates and author identity), so the same SHAs
come out every time:

```bash
cd fixtures && python3 generate_fixtures.py && cd ..
```

Expected: 10 lines like `built easy_syntax_bug ... bug_sha=d9e9c22a
range=3b875576..0ecff45d`, then `10 fixture cases built under
.../fixtures/cases`.

Then sanity-check ground truth by actually running pytest at every
boundary commit (takes ~15s, makes zero LLM calls):

```bash
python3 fixtures/verify_fixtures.py
```

Expected: every case prints `-> OK`; exit code 0.

## Run the baseline on one case

```bash
python3 bisect_agent.py baseline \
  --repo fixtures/cases/hard_misleading_message/repo \
  --good $(python3 -c "import json;print(json.load(open('fixtures/cases/hard_misleading_message/meta.json'))['good_sha'])") \
  --bad  $(python3 -c "import json;print(json.load(open('fixtures/cases/hard_misleading_message/meta.json'))['bad_sha'])") \
  --test-name test_validate_email
```

Expected: a JSON blob with a `guess_sha` — for this specific case, expect it
to guess the *wrong* commit (that's the point of this fixture; the real bug
is disguised as a harmless refactor).

Runtime: ~2s. Cost: <$0.001 (single short prompt, no diff/test data sent).

## Run the full agent on one case

```bash
python3 bisect_agent.py run \
  --repo fixtures/cases/easy_syntax_bug/repo \
  --good $(python3 -c "import json;print(json.load(open('fixtures/cases/easy_syntax_bug/meta.json'))['good_sha'])") \
  --bad  $(python3 -c "import json;print(json.load(open('fixtures/cases/easy_syntax_bug/meta.json'))['bad_sha'])") \
  --test-cmd "python -m pytest -q test_module.py"
```

Expected: JSON summary with `identified_sha` matching
`fixtures/cases/easy_syntax_bug/meta.json`'s `ground_truth_bug_sha`, plus a
printed root-cause explanation. Writes a trajectory to
`trajectories/run_easy_syntax_bug_<good8>_<bad8>.jsonl` and `.md`.

Runtime: ~5-8s per case (dominated by test executions + one `explain()`
call). Cost: ~$0.0002/case with `explain()` enabled, effectively $0 without
(`--no-explain`) since the narrowing/verify loop makes zero LLM calls.

Flags:
- `--strategy linear|binary` (default `binary`)
- `--no-verify` / `--no-explain` to isolate earlier pipeline stages
- `--model <name>` to override the model (default `deepseek-chat`)

## Run the full eval harness (all 10 fixtures x all 5 stages)

```bash
python3 bisect_agent.py eval --stage all
```

Writes `eval/raw_results.json` (machine-readable) and `eval/results.md`
(the comparison table + hard-case writeup), and (re)writes representative
trajectories to `trajectories/` for the easy/medium/hard cases named in
`eval/run_eval.py`'s `save_trajectories_for`.

Runtime: ~2-3 minutes total (50 stage-runs, each making 0-10 test executions
and 0-1 LLM calls). Total LLM cost for a full `--stage all` run: well under
$0.02 (see `eval/raw_results.json` for the exact per-case costs from the
run this repo's numbers came from).

Run a single stage in isolation (useful for iterating without waiting on
the full suite):

```bash
python3 bisect_agent.py eval --stage binary
```

Stages: `baseline`, `linear`, `binary`, `verify`, `final`.

## What "correct" means

Every fixture's ground truth is the exact commit SHA
`fixtures/generate_fixtures.py` injected the bug at
(`meta.json`'s `ground_truth_bug_sha`). Scoring is exact SHA match — no
subjective judgment.

## CI integration: see a real PR comment

`.github/workflows/bisect-agent.yml` fires automatically whenever a repo's
own test workflow fails on a PR, or manually via `workflow_dispatch`. Live
demo, reproducible by a judge without needing to set anything up:

**Fastest path — read the existing live demo:**
[itsdagi/bisect-agent-ci-demo#1](https://github.com/itsdagi/bisect-agent-ci-demo/pull/1)
is a real, already-open PR with an injected bug (`clamp()` loses its
lower-bound check). Its `Tests` check failed, which triggered
`Bisect Agent` automatically, which posted a real comment on the PR —
culprit commit, confidence, causal chain of failure, and a collapsed
trajectory log. No setup required, just open the PR and read the comment.

**Reproduce it yourself from a clean fork:**

```bash
gh repo fork itsdagi/bisect-agent-ci-demo --clone
cd bisect-agent-ci-demo
gh secret set DEEPSEEK_API_KEY   # paste your own key (or ANTHROPIC_API_KEY)
```

Then either:
- **Automatic path**: open a PR from `add-perf-tweak` into `main` in your
  fork (`gh pr create --base main --head add-perf-tweak`). The `Tests`
  workflow fails on the injected bug, which triggers `Bisect Agent`
  automatically -- watch the Actions tab, then check the PR for the
  comment (usually posts within ~30-60s of the test failure).
- **Manual path** (what judges should use to reproduce without waiting on
  a real failure): from the Actions tab, run `Bisect Agent` ->
  `Run workflow`, filling in:
  - `base_sha`: the `main` branch tip (a passing commit)
  - `head_sha`: the `add-perf-tweak` branch tip (the injected bug)
  - `pr_number`: leave blank for a dry run (results computed and uploaded
    as a workflow artifact, no comment posted), or fill in an open PR
    number to post/update a real comment

Expected: within ~1-2 minutes, a comment appears (or updates in place, if
one already exists on that PR — reruns don't stack duplicates) naming the
`perf: short-circuit clamp() for the common case` commit as the culprit,
High confidence, a 4-5 step causal chain showing the removed lower-bound
check propagating to the specific failing assertion, and a collapsed
trajectory log. The full trajectory JSON is also uploaded as a workflow
artifact (`bisect-agent-trajectory`) on that run.

**Copying this into your own repo:** copy `.github/workflows/bisect-agent.yml`
and add a `.bisect-agent.yml` at your repo root:

```yaml
test_cmd: "python -m pytest -q"
setup_cmd: "pip install -r requirements.txt"   # optional: installs YOUR test deps
path_filters:                                    # optional
  - "src/**"
```

You do not need to vendor `agent/` or `ci/` — the workflow's second
checkout step pulls those from `itsdagi/git-bisect-agent` at run time,
pinned to `BISECT_AGENT_REF` (default `main`) at the top of the workflow
file. Also rename `workflows: ["Tests"]` in the `workflow_run:` trigger to
match your own test workflow's `name:`.

Runtime: ~1-2 min per run (checkout + narrowing + verify + explain).
Cost: same as a local `run` — a few hundredths of a cent per PR.

## Cross-run memory demo

```bash
cd fixtures && python3 generate_memory_fixture.py && cd ..
python3 eval/demo_memory.py
```

Expected: prints both runs' identification + explanation, writes
`eval/memory_demo.md`, and ends with `run1_correct=True run2_correct=True
references_history=True`. Run 2's printed explanation should name the prior
regression explicitly (e.g. "This is the second missing-null-check
regression..."). Runtime: ~15-20s, two `explain()` calls (~$0.0005 total).

To try it manually against your own repo: `bisect_agent.py run --memory`
enables the same behavior against any repo/range.
