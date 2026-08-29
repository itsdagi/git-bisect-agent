# Memory demo: two runs, same repo, same bug class

Fixture: `fixtures/cases/memory_repeat_bug/` -- one repo, two separate regressions of the same class ("missing-null-check") introduced at two different points in its history, in two different functions. Both runs below use `do_memory=True` (`bisect_agent.py run --memory`) against the SAME repo, so run 2 sees run 1's recorded entry in `.bisect-agent/history.jsonl`.

Run 1 identified correct commit: **True**  |  Run 2 identified correct commit: **True**
Run 2's explanation references the prior regression: **True**

## Run 1 -- cold history

Identified: `3091c4872c` (ground truth: `3091c4872c`)
Confidence: High  |  Root cause tag: `missing-null-check`

### Chain of failure
```
Removed the null check for user in get_user_email
   |
   v
get_user_email(None) now calls None.get('email')
   |
   v
Calling .get on None raises AttributeError
   |
   v
test_get_user_email_missing_user calls get_user_email(None)
   |
   v
Assertion expects None but AttributeError is raised, causing test failure
```

### Summary
The commit removed the null check for the user parameter, so calling get_user_email(None) now attempts to call .get on None and raises an AttributeError instead of returning None as the test expects.

## Run 2 -- with run 1's history present

Identified: `f28822c44e` (ground truth: `f28822c44e`)
Confidence: High  |  Root cause tag: `missing-null-check`

### Chain of failure
```
Removed the if not user: return None check in get_user_phone
   |
   v
Now get_user_phone(None) calls None.get("phone")
   |
   v
None has no get method, raising AttributeError
   |
   v
test_get_user_phone_missing_user asserts get_user_phone(None) is None, but gets AttributeError
```

### Summary
The commit removed the null check for the user parameter in get_user_phone, so calling it with None now raises an AttributeError instead of returning None. This breaks the test expecting None for a missing user.

**History note:** This is the second missing-null-check regression in this repo; the first was in get_user_email.

## History file after both runs

```json
{"timestamp": "2026-08-29T10:48:51Z", "good_sha": "595039e1949a3c0071c8174d32227c2ed1e76757", "bad_sha": "3091c4872cfd4556540569df1e28bb36f1e9692a", "culprit_sha": "3091c4872cfd4556540569df1e28bb36f1e9692a", "files_touched": ["module.py"], "root_cause_tag": "missing-null-check", "summary": "The commit removed the null check for the user parameter, so calling get_user_email(None) now attempts to call .get on None and raises an AttributeError instead of returning None as the test expects."}
{"timestamp": "2026-08-29T10:48:57Z", "good_sha": "2e2eb7bc32a0843a054ea18a506af891f733a30e", "bad_sha": "ba6dbdc8e2b701b5b048128e64a6706749596e4c", "culprit_sha": "f28822c44e231aeded68d4ef40b5f6843de7e427", "files_touched": ["module.py"], "root_cause_tag": "missing-null-check", "summary": "The commit removed the null check for the user parameter in get_user_phone, so calling it with None now raises an AttributeError instead of returning None. This breaks the test expecting None for a missing user."}
```

## What this demonstrates

Run 2's diagnosis (*which* commit) came from the same run_test/narrow_range/verify() pipeline as run 1 -- memory played no part in identifying `get_user_phone`'s regressing commit. What memory changed is *how the explanation is framed*: run 2's `explain()` call received run 1's recorded entry (matched on `files_touched: ["module.py"]`) as context, and could reference the earlier `missing-null-check` regression instead of narrating the second bug as if it were the first time this pattern occurred in the repo.
