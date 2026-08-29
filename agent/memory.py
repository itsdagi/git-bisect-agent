"""
Cross-run memory: an append-only local log of past confirmed regressions in
a repo, used ONLY to make explain()'s narration richer ("this is the second
time this area has broken this way"). It is read AFTER verify() has already
confirmed the culprit commit, and it never feeds back into diagnosis --
narrow_range(), run_test(), and verify() have no knowledge this module
exists. If you're tempted to use history to pick a candidate, bias a
search, or skip verification for a "familiar" bug: don't. Diagnosis stays
100% grounded in actual test execution; memory is a narrative layer on top,
never a substitute for it.

Store: `<repo>/.bisect-agent/history.jsonl`, one JSON object per line per
completed run. Plain file next to `.git`, not a git object -- it survives
across CLI invocations on a persistent local clone, but (by design, see
CHANGELOG's "future work" note) does NOT persist across ephemeral CI
runners without extra wiring (actions/cache or a bot commit), which this
build deliberately does not add.
"""
import json
import time
from pathlib import Path

HISTORY_DIRNAME = ".bisect-agent"
HISTORY_FILENAME = "history.jsonl"


def _history_path(repo):
    return Path(repo) / HISTORY_DIRNAME / HISTORY_FILENAME


def load_history(repo):
    path = _history_path(repo)
    if not path.exists():
        return []
    entries = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def query_history(repo, files_touched):
    """Returns prior history entries whose files_touched overlaps with the
    given files, most recent first. Called by the orchestrator AFTER
    verify() has confirmed a culprit -- never before, and never used to
    influence which commit gets identified."""
    files_touched = set(files_touched or [])
    if not files_touched:
        return []
    matches = [
        e for e in load_history(repo)
        if set(e.get("files_touched", [])) & files_touched
    ]
    matches.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return matches


def record_history(repo, good_sha, bad_sha, culprit_sha, files_touched, root_cause_tag, summary):
    """Appends one completed-run record. Called only after a culprit has
    been identified (and ideally verified) -- this is a record of a
    diagnosis already made, not an input to making one."""
    path = _history_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "good_sha": good_sha,
        "bad_sha": bad_sha,
        "culprit_sha": culprit_sha,
        "files_touched": sorted(files_touched or []),
        "root_cause_tag": root_cause_tag or "unclassified",
        "summary": summary or "",
    }
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def format_history_context(matches, limit=3):
    """Renders matched history entries as short text for explain()'s prompt."""
    if not matches:
        return None
    lines = []
    for e in matches[:limit]:
        date = e.get("timestamp", "")[:10]
        lines.append(
            f"- {date}  commit {e.get('culprit_sha', '')[:10]}  "
            f"[{e.get('root_cause_tag', 'unclassified')}]  {e.get('summary', '')}"
        )
    if len(matches) > limit:
        lines.append(f"- ... and {len(matches) - limit} more prior entr{'y' if len(matches) - limit == 1 else 'ies'}")
    return "\n".join(lines)
