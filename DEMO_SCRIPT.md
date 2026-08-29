# Demo video script

Target: ~3 minutes. Every beat below points at something real that already
happened — no staged screen recording of a fake result, no "imagine this
worked." Links and numbers are live as of this build.

## Beat 1 — The problem (15s)

Cold open on a terminal: `git log --oneline` showing a range of commits, a
failing test. Voiceover: "A test used to pass, now it doesn't, somewhere
across a dozen commits. `git bisect` can find it, but you have to babysit
it — and most people just guess from commit messages instead."

## Beat 2 — Baseline vs. agent, side by side (30s)

Show `eval/results.md`'s summary table on screen:

| Stage | Accuracy |
|---|---|
| baseline (guess from vibes) | 60% (6/10) |
| final agent | 100% (10/10) |

Zoom into `hard_misleading_message`: the baseline picks a commit labeled
"WIP: rewrite validation logic, might be buggy" — confidently, wrong. The
real bug hides behind "refactor: extract email parts for readability (no
behavior change)." The agent gets it right because it actually runs the
test.

## Beat 3 — Open on a real PR with a failing check (30s)

Navigate to
[itsdagi/bisect-agent-ci-demo#1](https://github.com/itsdagi/bisect-agent-ci-demo/pull/1)
in a browser. Show the `Tests` check: red X, failed. Show the Actions tab:
`Bisect Agent` firing automatically off that failure (`workflow_run`
trigger) — no human ran a CLI command.

## Beat 4 — Watch the comment land (30s)

Refresh the PR. The comment appears:
[the real comment](https://github.com/itsdagi/bisect-agent-ci-demo/pull/1#issuecomment-5461903445) —
culprit commit linked, **High** confidence, the causal chain rendered as an
arrow diagram, the collapsed trajectory log. Expand the trajectory section
live to show it's not decoration — every `run_test`/`narrow_range`/`verify`
call is really there with real pytest output.

Mention in voiceover: this workflow's permissions are read + comment only —
it can't push, merge, or modify the PR even if it wanted to. That's not a
policy, it's what the token can do.

## Beat 5 — Zoom into memory (45s)

Cut to terminal. Show `eval/memory_demo.md`: one repo, the same
"missing-null-check" bug introduced twice, in two different functions, at
two different points in history.

Show run 1's explanation (cold history, no callback). Then show run 2's:

> "This is the second missing-null-check regression in this repo; the
> first was in get_user_email."

Voiceover: "Diagnosis didn't change — same pipeline, same verify() step,
both runs land on the right commit independently. What changed is the
explanation: it knows this has happened before, because it's checking a
local history file, but only *after* verification confirmed the answer —
memory never gets a vote in which commit is guilty."

## Beat 6 — The hot take (30s)

Show `eval/results.md`'s hot-take paragraph on screen, read the key line:

> "An ungrounded agent will confidently name a plausible-looking commit
> even when it never ran the test — the fix isn't a smarter prompt, it's
> forcing execution before any claim."

Add the CI-specific corollary discovered while building this: even a tool
that *does* execute the test isn't safe from confidently reporting the
wrong thing — the first live CI run correctly-but-uselessly diagnosed a
missing `pytest` install as the "culprit" because nothing had verified the
test environment itself was sound. Grounding has to cover the whole
pipeline, not just the diagnosis step.

## Beat 7 — Close (10s)

"Everything in this video is reproducible from `REPRODUCE.md` — same repo,
same demo PR, same fixtures, real API calls throughout."
