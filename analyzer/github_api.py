"""
GitHub REST API client — no AI, no CrewAI.
All repository data fetching lives here so you can test and debug it independently.
"""
from __future__ import annotations

import base64
import os
import re
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

GITHUB_TOKEN = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", "")
API_PAGE_SIZE = 100
REPORT_SAMPLE_LIMIT = 50
BRANCH_DETAIL_LIMIT = 20
FILE_EVIDENCE_LIMIT = 8
DIRECTORY_EVIDENCE_LIMIT = 5
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


def _search_total_count(query: str) -> int | None:
    try:
        data = _get("/search/issues", {"q": query, "per_page": 1, "page": 1})
        if isinstance(data, dict):
            return data.get("total_count")
    except GitHubAPIError:
        return None
    return None


def _content_preview(item: dict) -> str:
    content = item.get("content")
    if not content or item.get("encoding") != "base64":
        return ""
    try:
        decoded = base64.b64decode(content).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""
    return decoded[:4000]


def _enrich_root_items(base: str, contents: list[dict]) -> list[dict]:
    files = [
        {
            "name": item.get("name", ""),
            "path": item.get("path", item.get("name", "")),
            "type": item.get("type", ""),
            "size": item.get("size", 0),
        }
        for item in contents
    ]

    evidence_names = {
        "readme.md", "pyproject.toml", "requirements.txt", "setup.py", "setup.cfg",
        "package.json", "tsconfig.json", "go.mod", "cargo.toml", "gemfile",
        "pom.xml", "build.gradle", "dockerfile", "compose.yml", "docker-compose.yml",
        "agents.md", "contributing.md", "architecture.md", "concepts.md",
    }
    evidence_files = [
        item for item in contents
        if item.get("type") == "file" and item.get("name", "").lower() in evidence_names
    ][:FILE_EVIDENCE_LIMIT]
    previews: dict[str, str] = {}
    for item in evidence_files:
        try:
            detail = _get(f"{base}/contents/{item['path']}")
            previews[item["path"]] = _content_preview(detail) if isinstance(detail, dict) else ""
        except GitHubAPIError:
            previews[item.get("path", "")] = ""

    useful_dirs = {
        "src", "app", "lib", "tests", "test", "docs", "packages", "skills",
        "api", "backend", "frontend", "core", ".github", ".agents",
    }
    directory_items = [
        item for item in contents
        if item.get("type") == "dir" and item.get("name", "").lower() in useful_dirs
    ][:DIRECTORY_EVIDENCE_LIMIT]
    children: dict[str, list[str]] = {}
    for item in directory_items:
        try:
            listing = _get(f"{base}/contents/{item['path']}")
            children[item["path"]] = [child.get("name", "") for child in listing[:50]] if isinstance(listing, list) else []
        except GitHubAPIError:
            children[item.get("path", "")] = []

    for item in files:
        item["content_preview"] = previews.get(item["path"], "")
        item["children"] = children.get(item["path"], [])
    return files


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
    issues_raw = _get(
        f"{base}/issues",
        {"state": "open", "per_page": API_PAGE_SIZE, "page": 1},
    )
    prs_raw = _get(
        f"{base}/pulls",
        {"state": "open", "per_page": API_PAGE_SIZE, "page": 1},
    )
    branches_raw = _get(f"{base}/branches", {"per_page": API_PAGE_SIZE, "page": 1})
    open_issues_total = _search_total_count(f"repo:{owner}/{repo} is:issue is:open")
    open_prs_total = _search_total_count(f"repo:{owner}/{repo} is:pr is:open")

    files = _enrich_root_items(base, contents) if isinstance(contents, list) else []
    issue_base = f"https://github.com/{owner}/{repo}/issues"
    pr_base = f"https://github.com/{owner}/{repo}/pull"
    issues = [
        {
            "number": issue.get("number"),
            "title": issue.get("title"),
            "labels": [label["name"] for label in issue.get("labels", [])],
            "author": issue.get("user", {}).get("login"),
            "created_at": issue.get("created_at"),
            "updated_at": issue.get("updated_at"),
            "url": issue.get("html_url") or f"{issue_base}/{issue.get('number')}",
            "comments": issue.get("comments", 0),
            "body": (issue.get("body") or "")[:2000],
            "assignees": [assignee.get("login") for assignee in issue.get("assignees", [])],
            "milestone": (issue.get("milestone") or {}).get("title"),
        }
        for issue in (issues_raw if isinstance(issues_raw, list) else [])
        if "pull_request" not in issue
    ][:REPORT_SAMPLE_LIMIT]
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
    ][:REPORT_SAMPLE_LIMIT]
    branches = [
        {
            "name": branch["name"],
            "protected": branch.get("protected", False),
            "last_commit_date": None,
        }
        for branch in (branches_raw if isinstance(branches_raw, list) else [])
    ]
    for index, branch in enumerate(branches):
        if index >= BRANCH_DETAIL_LIMIT:
            break
        raw_branch = branches_raw[index] if isinstance(branches_raw, list) else {}
        sha = (raw_branch.get("commit") or {}).get("sha")
        if not sha:
            continue
        try:
            commit = _get(f"{base}/commits/{sha}")
            branch["last_commit_date"] = (
                commit.get("commit", {})
                .get("committer", {})
                .get("date")
            )
        except GitHubAPIError:
            branch["last_commit_date"] = None

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
            "pushed_at": meta.get("pushed_at"),
        },
        "files": files,
        "issues": issues,
        "pull_requests": pull_requests,
        "branches": branches,
        "stats": {
            "open_issues_total": open_issues_total if open_issues_total is not None else len(issues),
            "open_prs_total": open_prs_total if open_prs_total is not None else len(pull_requests),
            "issues_sampled": len(issues),
            "pull_requests_sampled": len(pull_requests),
            "branches_sampled": len(branches),
            "branches_with_commit_dates": min(len(branches), BRANCH_DETAIL_LIMIT),
            "api_page_size": API_PAGE_SIZE,
            "report_sample_limit": REPORT_SAMPLE_LIMIT,
        },
    }
    _snapshot_cache[key] = snapshot
    return snapshot
