"""Thin, read-only-ish git plumbing wrappers.

Every mutating operation here is either a `git worktree add/remove` against
a disposable temp directory, or a read (`log`, `show`, `rev-list`). Nothing
in this module ever touches the caller's working tree, resets branches, or
force-pushes anything.
"""
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path


class GitError(RuntimeError):
    pass


def _run(cmd, cwd, timeout=None):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise GitError(f"git command failed: {cmd}\nstdout={result.stdout}\nstderr={result.stderr}")
    return result.stdout


def rev_list_between(repo, good_sha, bad_sha):
    """Commits strictly after good_sha up to and including bad_sha, oldest first."""
    out = _run(["git", "rev-list", "--reverse", f"{good_sha}..{bad_sha}"], cwd=repo)
    return [l for l in out.splitlines() if l.strip()]


def get_diff(repo, sha):
    """Diff of `sha` against its immediate parent."""
    return _run(["git", "show", "--format=", sha], cwd=repo)


def get_commit_message(repo, sha):
    out = _run(["git", "show", "-s", "--format=%H%n%an <%ae>%n%aI%n%s%n%n%b", sha], cwd=repo)
    lines = out.split("\n")
    return {
        "sha": lines[0],
        "author": lines[1],
        "date": lines[2],
        "subject": lines[3],
        "body": "\n".join(lines[5:]).strip(),
    }


def get_parent(repo, sha):
    return _run(["git", "rev-parse", f"{sha}^"], cwd=repo).strip()


@contextmanager
def worktree(repo, sha):
    """Checks out `sha` into a disposable temp directory as a git worktree,
    and always tears it down afterward. Never mutates the caller's checkout."""
    with tempfile.TemporaryDirectory(prefix="bisect-wt-") as wt_dir:
        _run(["git", "worktree", "add", "--detach", "-q", wt_dir, sha], cwd=repo)
        try:
            yield Path(wt_dir)
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", wt_dir],
                            cwd=repo, capture_output=True, text=True)
