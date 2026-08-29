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
