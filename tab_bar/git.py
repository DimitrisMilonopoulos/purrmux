from pathlib import Path

from . import config

_git_dir_cache: dict[Path, Path | None] = {}
_branch_cache: dict[Path, tuple[int, str | None]] = {}


def get_git_dir(path: Path) -> Path | None:
    for candidate in [path, *path.parents]:
        dotgit = candidate / ".git"
        if dotgit.is_dir():
            return dotgit
        if not dotgit.is_file():
            continue

        try:
            gitdir = dotgit.read_text(encoding="utf-8").strip()
        except OSError:
            return None

        prefix, _, value = gitdir.partition(":")
        if prefix != "gitdir" or not value.strip():
            return None

        git_path = Path(value.strip())
        if not git_path.is_absolute():
            git_path = candidate / git_path
        return git_path

    return None


def get_git_dir_cached(path: Path) -> Path | None:
    if path in _git_dir_cache:
        return _git_dir_cache[path]

    git_dir = get_git_dir(path)
    _git_dir_cache[path] = git_dir
    return git_dir


def get_git_branch(path: Path) -> str | None:
    git_dir = get_git_dir_cached(path)
    if git_dir is None:
        return None

    head_path = git_dir / "HEAD"

    try:
        mtime_ns = head_path.stat().st_mtime_ns
    except OSError:
        return None

    cached = _branch_cache.get(git_dir)
    if cached is not None:
        cached_mtime_ns, branch = cached
        if cached_mtime_ns == mtime_ns:
            return branch

    try:
        head = head_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    prefix = "ref: refs/heads/"
    branch = head.removeprefix(prefix) if head.startswith(prefix) else None
    _branch_cache[git_dir] = (mtime_ns, branch)

    return branch


def shorten_branch(branch: str, max_size: int) -> str | None:
    parts = branch.split("/")
    if len(parts) > 1:
        branch = "/".join([part[:1] for part in parts[:-1]] + [parts[-1]])

    limit = min(max_size, config.MAX_LENGTH_BRANCH)
    if len(branch) <= limit:
        return branch
    if limit >= 3:
        return branch[: limit - 1] + "…"
    return None
