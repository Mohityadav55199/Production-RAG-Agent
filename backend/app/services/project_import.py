"""
Project import: turn a GitHub repository or a .zip archive into a list of
(filename, bytes) pairs that the normal document pipeline can ingest.

Each source file becomes one document whose filename is its path inside the
project (e.g. "my-repo/src/app/main.py"), so answers can cite exact files.
A generated PROJECT_OVERVIEW.md with the directory tree is added as well,
which lets the LLM answer "how is this project structured?" questions.
"""

import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import httpx

from app.utils.logging import get_logger

logger = get_logger(__name__)

# ── Limits (protect Render memory and the embedding quota) ─────────────────────
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024        # compressed zip / GitHub download
MAX_TOTAL_UNCOMPRESSED = 100 * 1024 * 1024  # zip-bomb guard
MAX_FILE_BYTES = 200 * 1024                 # skip generated/minified giants
MAX_PROJECT_FILES = 200
MIN_FILE_BYTES = 20

CODE_EXTENSIONS = {
    "py", "js", "jsx", "ts", "tsx", "mjs", "cjs", "java", "kt", "kts", "go", "rs",
    "rb", "php", "cs", "c", "h", "cpp", "cc", "hpp", "swift", "scala", "dart",
    "vue", "svelte", "html", "css", "scss", "sass", "less", "sql", "sh", "bash",
    "ps1", "yaml", "yml", "toml", "ini", "cfg", "conf", "gradle", "prisma",
    "graphql", "gql", "proto", "tf", "r", "lua", "ex", "exs", "erl", "clj",
}
DOC_EXTENSIONS = {"md", "markdown", "txt", "rst", "json"}
SPECIAL_FILENAMES = {
    "dockerfile", "makefile", "procfile", "gemfile", "rakefile", "jenkinsfile",
    ".env.example", ".gitignore", ".dockerignore", "readme", "license",
}

SKIP_DIRS = {
    "node_modules", ".git", ".next", ".nuxt", "dist", "build", "out", "target",
    "vendor", "__pycache__", ".venv", "venv", "env", ".idea", ".vscode",
    "coverage", ".pytest_cache", ".mypy_cache", ".turbo", ".cache", "bin", "obj",
    ".gradle", "Pods", ".dart_tool", "qdrant_data",
}
SKIP_FILENAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "Cargo.lock", "composer.lock", "Gemfile.lock", "bun.lockb", ".env",
}

# Files that explain a project the most — indexed first if we hit the file cap
_PRIORITY_NAMES = {
    "readme.md", "readme", "readme.rst", "package.json", "pyproject.toml",
    "requirements.txt", "dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "go.mod", "cargo.toml", "pom.xml", "build.gradle", "main.py", "app.py",
    "index.ts", "index.js", "main.ts", "main.go", "render.yaml", "vercel.json",
}

_GITHUB_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/"
    r"(?P<owner>[A-Za-z0-9-]{1,39})/(?P<repo>[A-Za-z0-9._-]{1,100}?)(?:\.git)?"
    r"(?:/tree/(?P<branch>[^?#]+))?/?(?:[?#].*)?$"
)


@dataclass
class ProjectFiles:
    project_name: str
    files: list[tuple[str, bytes]] = field(default_factory=list)
    skipped: int = 0
    truncated: bool = False


def _is_indexable(path: PurePosixPath) -> bool:
    if any(part in SKIP_DIRS for part in path.parts[:-1]):
        return False
    name = path.name
    lower = name.lower()
    if name in SKIP_FILENAMES or lower.endswith((".min.js", ".min.css", ".map")):
        return False
    if lower in SPECIAL_FILENAMES:
        return True
    ext = lower.rsplit(".", 1)[-1] if "." in lower else ""
    return ext in CODE_EXTENSIONS or ext in DOC_EXTENSIONS


def _priority(path: str) -> tuple[int, int, str]:
    p = PurePosixPath(path)
    return (0 if p.name.lower() in _PRIORITY_NAMES else 1, len(p.parts), path)


def _looks_binary(data: bytes) -> bool:
    return b"\x00" in data[:4096]


def _build_tree(paths: list[str]) -> str:
    tree: dict = {}
    for path in sorted(paths):
        node = tree
        for part in path.split("/"):
            node = node.setdefault(part, {})

    lines: list[str] = []

    def walk(node: dict, depth: int) -> None:
        # Folders first, then files
        for name in sorted(node, key=lambda n: (not node[n], n.lower())):
            suffix = "/" if node[name] else ""
            lines.append(f"{'  ' * depth}- {name}{suffix}")
            walk(node[name], depth + 1)

    walk(tree, 0)
    return "\n".join(lines)


def _overview_document(project: ProjectFiles, all_paths: list[str]) -> tuple[str, bytes]:
    exts: dict[str, int] = {}
    for path in all_paths:
        name = path.rsplit("/", 1)[-1]
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else name.lower()
        exts[ext] = exts.get(ext, 0) + 1
    top_exts = ", ".join(f".{e} ({n})" for e, n in sorted(exts.items(), key=lambda x: -x[1])[:10])

    text = (
        f"# Project overview: {project.project_name}\n\n"
        f"This document describes the structure of the code project "
        f"'{project.project_name}'. It contains {len(all_paths)} source files.\n\n"
        f"Most common file types: {top_exts}\n\n"
        f"## Directory structure\n\n{_build_tree(all_paths)}\n"
    )
    return f"{project.project_name}/PROJECT_OVERVIEW.md", text.encode("utf-8")


def extract_project_from_zip(archive: bytes, project_name: str | None = None) -> ProjectFiles:
    """Read indexable source files out of a zip archive, entirely in memory."""
    if len(archive) > MAX_ARCHIVE_BYTES:
        raise ValueError(f"Archive is larger than {MAX_ARCHIVE_BYTES // (1024 * 1024)} MB.")

    try:
        zf = zipfile.ZipFile(io.BytesIO(archive))
    except zipfile.BadZipFile as exc:
        raise ValueError("The uploaded file is not a valid .zip archive.") from exc

    entries = [i for i in zf.infolist() if not i.is_dir()]
    if sum(i.file_size for i in entries) > MAX_TOTAL_UNCOMPRESSED:
        raise ValueError("Archive is too large once extracted (over 100 MB).")

    # GitHub zipballs and most "Compress folder" zips wrap everything in one top folder
    top_levels = {i.filename.replace("\\", "/").split("/", 1)[0] for i in entries}
    strip_root = len(top_levels) == 1 and all("/" in i.filename.replace("\\", "/") for i in entries)
    root_name = next(iter(top_levels)) if strip_root else None
    project = ProjectFiles(project_name=project_name or root_name or "project")

    candidates: list[tuple[str, zipfile.ZipInfo]] = []
    for info in entries:
        raw = info.filename.replace("\\", "/")
        rel = raw.split("/", 1)[1] if strip_root else raw
        path = PurePosixPath(rel)
        # Never trust archive paths: reject absolute paths and traversal
        if not rel or path.is_absolute() or ".." in path.parts:
            project.skipped += 1
            continue
        if not _is_indexable(path) or not (MIN_FILE_BYTES <= info.file_size <= MAX_FILE_BYTES):
            project.skipped += 1
            continue
        candidates.append((rel, info))

    candidates.sort(key=lambda c: _priority(c[0]))
    if len(candidates) > MAX_PROJECT_FILES:
        project.skipped += len(candidates) - MAX_PROJECT_FILES
        project.truncated = True
        candidates = candidates[:MAX_PROJECT_FILES]

    for rel, info in candidates:
        data = zf.read(info)
        if _looks_binary(data):
            project.skipped += 1
            continue
        project.files.append((f"{project.project_name}/{rel}", data))

    if not project.files:
        raise ValueError("No supported source or documentation files were found in the project.")

    all_paths = [name.split("/", 1)[1] for name, _ in project.files]
    project.files.insert(0, _overview_document(project, all_paths))
    logger.info(
        "Project '%s': %d files to index, %d skipped%s",
        project.project_name, len(project.files), project.skipped,
        " (file cap reached)" if project.truncated else "",
    )
    return project


def parse_github_url(url: str) -> tuple[str, str, str | None]:
    """Return (owner, repo, branch) or raise ValueError for anything that is not a github.com repo URL."""
    match = _GITHUB_URL_RE.match(url.strip())
    if not match:
        raise ValueError("Enter a GitHub repository URL like https://github.com/owner/repo")
    return match["owner"], match["repo"], match["branch"]


async def fetch_github_project(url: str, token: str | None = None) -> ProjectFiles:
    """Download a repository zipball from the GitHub API and extract it."""
    owner, repo, branch = parse_github_url(url)
    # Host is fixed to api.github.com, so user input can't redirect us elsewhere (SSRF)
    api_url = f"https://api.github.com/repos/{owner}/{repo}/zipball" + (f"/{branch}" if branch else "")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "production-rag-agent"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(follow_redirects=True, timeout=120) as client:
        async with client.stream("GET", api_url, headers=headers) as resp:
            if resp.status_code == 404:
                raise ValueError(
                    f"Repository '{owner}/{repo}' was not found. It may be private — "
                    "only public repos work unless GITHUB_TOKEN is set on the server."
                )
            if resp.status_code == 403:
                raise ValueError("GitHub rate limit reached. Try again later or set GITHUB_TOKEN on the server.")
            resp.raise_for_status()

            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > MAX_ARCHIVE_BYTES:
                    raise ValueError("Repository download is larger than 50 MB.")

    return extract_project_from_zip(bytes(buf), project_name=repo)
