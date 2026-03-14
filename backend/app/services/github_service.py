import base64
import logging
from pathlib import Path
from typing import Dict, List, Tuple

import httpx

from ..config import get_settings


logger = logging.getLogger("dristi-scan")
settings = get_settings()

SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".java", ".go", ".php", ".rb", ".c", ".cpp"}


class GitHubClient:
    def __init__(self, token: str | None):
        if not token:
            logger.warning("GITHUB_TOKEN not configured; GitHub rate limits may apply.")
        self.token = token
        self.base_url = "https://api.github.com"

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def fetch_repo_default_branch(self, owner: str, repo: str) -> str:
        url = f"{self.base_url}/repos/{owner}/{repo}"
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            return data.get("default_branch", "main")

    async def fetch_tree(self, owner: str, repo: str, branch: str) -> List[Dict]:
        url = f"{self.base_url}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            return data.get("tree", [])

    async def fetch_blob(self, owner: str, repo: str, sha: str) -> bytes:
        url = f"{self.base_url}/repos/{owner}/{repo}/git/blobs/{sha}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            content = data.get("content", "")
            if data.get("encoding") == "base64":
                return base64.b64decode(content)
            return content.encode()


def parse_repo_url(url: str) -> Tuple[str, str, str | None]:
    """
    Parse URLs like https://github.com/owner/repo[.git][/#branch]
    Returns (owner, repo, branch_or_none)
    """
    trimmed = url.rstrip("/").replace(".git", "")
    parts = trimmed.split("/")
    if len(parts) < 2:
        raise ValueError("Invalid GitHub URL")
    owner, repo = parts[-2], parts[-1]
    branch = None
    if "#" in repo:
        repo, branch = repo.split("#", 1)
    return owner, repo, branch


async def fetch_repository_sources(url: str) -> List[Tuple[str, str]]:
    """
    Fetch supported code files from a GitHub repo.
    Returns list of (path, decoded_content) tuples.
    """
    owner, repo, branch_hint = parse_repo_url(url)
    client = GitHubClient(settings.github_token)
    branch = branch_hint or await client.fetch_repo_default_branch(owner, repo)
    tree = await client.fetch_tree(owner, repo, branch)
    files = []
    for node in tree:
        if node.get("type") != "blob":
            continue
        path = node.get("path", "")
        if Path(path).suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        try:
            blob_bytes = await client.fetch_blob(owner, repo, node["sha"])
            try:
                content = blob_bytes.decode("utf-8", errors="ignore")
            except Exception:
                continue
            files.append((path, content))
        except httpx.HTTPError as exc:
            logger.warning("Failed to fetch %s: %s", path, exc)
            continue
    return files
