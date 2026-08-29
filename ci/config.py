"""
Loads `.bisect-agent.yml` from a target repo's root. This is the only
per-repo configuration the CI integration needs.

Example:

    test_cmd: "python -m pytest -q"
    path_filters:
      - "src/**"
      - "lib/**"

`test_cmd` is required. `path_filters` is optional: a list of glob patterns
(matched with fnmatch against paths relative to the repo root). If present,
the CI workflow skips bisecting entirely when the PR's changed files don't
touch any of them -- a cheap way to avoid burning CI minutes bisecting a
failure that's unrelated to the paths this config cares about.
"""
import fnmatch
from pathlib import Path

DEFAULT_CONFIG_PATH = ".bisect-agent.yml"


class ConfigError(RuntimeError):
    pass


def load_config(path=DEFAULT_CONFIG_PATH):
    import yaml
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(
            f"{path} not found. Add one at the repo root with at least a "
            f"`test_cmd:` key -- see README.md's CI integration section."
        )
    data = yaml.safe_load(config_path.read_text()) or {}
    if "test_cmd" not in data or not str(data["test_cmd"]).strip():
        raise ConfigError(f"{path} must set a non-empty `test_cmd:`")
    return {
        "test_cmd": str(data["test_cmd"]),
        "path_filters": list(data.get("path_filters") or []),
    }


def changed_paths_match_filters(changed_paths, path_filters):
    """True if any changed path matches any glob filter, or if no filters
    are configured (no filter = always run)."""
    if not path_filters:
        return True
    return any(
        fnmatch.fnmatch(path, pattern)
        for path in changed_paths
        for pattern in path_filters
    )
