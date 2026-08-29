"""
Minimal GitHub REST API client, stdlib-only (urllib), no third-party HTTP
dependency. Used only for: listing/creating/updating a PR (issue) comment,
and looking up the PR associated with a `workflow_run` event's head SHA.

This module never calls any endpoint that mutates repo content, branches,
or PR state beyond posting/editing a single comment -- see
`.github/workflows/bisect-agent.yml`'s permissions block, which grants
exactly `pull-requests: write` / `issues: write` and nothing else.
"""
import json
import urllib.error
import urllib.request

API_ROOT = "https://api.github.com"
COMMENT_MARKER = "<!-- bisect-agent:auto-comment -->"


class GitHubAPIError(RuntimeError):
    pass


def _request(method, url, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raise GitHubAPIError(f"GitHub API {method} {url} -> {e.code}: {e.read().decode()}") from e


def list_issue_comments(repo_full_name, issue_number, token):
    return _request("GET", f"{API_ROOT}/repos/{repo_full_name}/issues/{issue_number}/comments", token)


def find_existing_bot_comment(repo_full_name, issue_number, token, marker=COMMENT_MARKER):
    for c in list_issue_comments(repo_full_name, issue_number, token):
        if marker in (c.get("body") or ""):
            return c["id"]
    return None


def create_comment(repo_full_name, issue_number, body, token):
    return _request("POST", f"{API_ROOT}/repos/{repo_full_name}/issues/{issue_number}/comments",
                     token, {"body": body})


def update_comment(repo_full_name, comment_id, body, token):
    return _request("PATCH", f"{API_ROOT}/repos/{repo_full_name}/issues/comments/{comment_id}",
                     token, {"body": body})


def upsert_pr_comment(repo_full_name, pr_number, body, token, marker=COMMENT_MARKER):
    """Creates a new comment, or edits the existing bisect-agent comment on
    this PR in place if one already exists (identified by a hidden HTML
    marker in the comment body) -- reruns update the same comment instead
    of stacking duplicates."""
    tagged_body = f"{marker}\n{body}"
    existing_id = find_existing_bot_comment(repo_full_name, pr_number, token, marker)
    if existing_id:
        return update_comment(repo_full_name, existing_id, tagged_body, token)
    return create_comment(repo_full_name, pr_number, tagged_body, token)


def get_pr_for_workflow_run(repo_full_name, workflow_run_payload, token):
    """Given a `workflow_run` event's `workflow_run` payload object, returns
    (pr_number, base_sha, head_sha), preferring the PR list embedded in the
    payload and falling back to the commit-search API if that's empty
    (can happen for runs triggered from a fork)."""
    prs = workflow_run_payload.get("pull_requests") or []
    if prs:
        pr = prs[0]
        return pr["number"], pr["base"]["sha"], pr["head"]["sha"]

    head_sha = workflow_run_payload["head_sha"]
    results = _request("GET", f"{API_ROOT}/repos/{repo_full_name}/commits/{head_sha}/pulls", token)
    if not results:
        return None, None, head_sha
    pr = results[0]
    return pr["number"], pr["base"]["sha"], head_sha


def changed_files(repo_full_name, base_sha, head_sha, token):
    """List of file paths changed between base_sha and head_sha, via the
    compare API (used for optional path_filters). Read-only."""
    data = _request("GET", f"{API_ROOT}/repos/{repo_full_name}/compare/{base_sha}...{head_sha}", token)
    return [f["filename"] for f in (data.get("files") or [])]
