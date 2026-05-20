"""
GitHub REST API client — no AI, no CrewAI.
All repository data fetching lives here so you can test and debug it independently.
"""
from __future__ import annotations

import os
import re
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

GITHUB_TOKEN = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", "")
HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

REPO_URL_PATTERN = re.compile(
    r"^https?://(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)/?$",
    re.IGNORECASE,
)


class GitHubAPIError(Exception):
    """Raised when the GitHub API returns an error or the URL is invalid."""


def parse_repo_url(repo_url: str) -> tuple[str, str]:
    match = REPO_URL_PATTERN.match(repo_url.strip())
    if not match:
        raise GitHubAPIError(
            "Invalid URL. Use format: https://github.com/owner/repository"
        )
    owner, repo = match.group(1), match.group(2)
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    return session


def _get(path: str, params: dict | None = None) -> Any:
    session = _session()
    response = session.get(
        f"https://api.github.com{path}",
        headers=HEADERS,
        params=params or {},
        timeout=20,
    )
    if response.status_code == 404:
        raise GitHubAPIError("Repository not found. Check the URL or repo visibility.")
    if response.status_code == 403:
        raise GitHubAPIError(
            "GitHub API rate limit or forbidden. Add GITHUB_PERSONAL_ACCESS_TOKEN to .env."
        )
    if not response.ok:
        raise GitHubAPIError(f"GitHub API error ({response.status_code}): {response.text[:200]}")
    return response.json()


_snapshot_cache: dict[str, dict[str, Any]] = {}


def clear_snapshot_cache() -> None:
    _snapshot_cache.clear()


def fetch_repo_snapshot(repo_url: str) -> dict[str, Any]:
    """Fetch metadata, root files, issues, PRs, and branches in one call."""
    key = repo_url.strip()
    if key in _snapshot_cache:
        return _snapshot_cache[key]

    owner, repo = parse_repo_url(repo_url)
    base = f"/repos/{owner}/{repo}"

    meta = _get(base)
    contents = _get(f"{base}/contents/")
    issues_raw = _get(f"{base}/issues", {"state": "open", "per_page": 30})
    prs_raw = _get(f"{base}/pulls", {"state": "open", "per_page": 30})
    branches_raw = _get(f"{base}/branches", {"per_page": 30})

    files = (
        [{"name": item["name"], "type": item["type"]} for item in contents]
        if isinstance(contents, list)
        else []
    )
    issue_base = f"https://github.com/{owner}/{repo}/issues"
    pr_base = f"https://github.com/{owner}/{repo}/pull"
    issues = [
        {
            "number": issue.get("number"),
            "title": issue.get("title"),
            "labels": [label["name"] for label in issue.get("labels", [])],
            "author": issue.get("user", {}).get("login"),
            "created_at": issue.get("created_at"),
            "url": issue.get("html_url") or f"{issue_base}/{issue.get('number')}",
            "comments": issue.get("comments", 0),
        }
        for issue in (issues_raw if isinstance(issues_raw, list) else [])
        if "pull_request" not in issue
    ]
    pull_requests = [
        {
            "number": pr.get("number"),
            "title": pr.get("title"),
            "author": pr.get("user", {}).get("login"),
            "head": pr.get("head", {}).get("ref"),
            "base": pr.get("base", {}).get("ref"),
            "created_at": pr.get("created_at"),
            "url": pr.get("html_url") or f"{pr_base}/{pr.get('number')}",
            "draft": pr.get("draft", False),
        }
        for pr in (prs_raw if isinstance(prs_raw, list) else [])
    ]
    branches = [
        {
            "name": branch["name"],
            "protected": branch.get("protected", False),
        }
        for branch in (branches_raw if isinstance(branches_raw, list) else [])
    ]

    snapshot = {
        "repo_url": repo_url.strip(),
        "owner": owner,
        "repo": repo,
        "meta": {
            "name": meta.get("name"),
            "full_name": meta.get("full_name"),
            "description": meta.get("description"),
            "language": meta.get("language"),
            "stars": meta.get("stargazers_count"),
            "forks": meta.get("forks_count"),
            "open_issues_count": meta.get("open_issues_count"),
            "default_branch": meta.get("default_branch"),
            "topics": meta.get("topics", []),
            "license": (meta.get("license") or {}).get("spdx_id"),
            "created_at": meta.get("created_at"),
            "updated_at": meta.get("updated_at"),
        },
        "files": files,
        "issues": issues,
        "pull_requests": pull_requests,
        "branches": branches,
    }
    _snapshot_cache[key] = snapshot
    return snapshot
