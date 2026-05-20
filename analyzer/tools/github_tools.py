"""
CrewAI tools — agents call these instead of hallucinating GitHub data.
(CrewAI 1.14 requires crewai.tools.tool, not LangChain StructuredTool.)
"""
from __future__ import annotations

import json

from crewai.tools import tool

from analyzer.github_api import fetch_repo_snapshot


def _snapshot_for(repo_url: str) -> dict:
    return fetch_repo_snapshot(repo_url)


@tool
def get_repo_structure(repo_url: str) -> str:
    """Fetch repository metadata and root-level files/folders for a public GitHub repo URL."""
    data = _snapshot_for(repo_url)
    payload = {
        "meta": data["meta"],
        "files": data["files"],
        "owner": data["owner"],
        "repo": data["repo"],
    }
    return json.dumps(payload, indent=2)


@tool
def get_repo_issues(repo_url: str) -> str:
    """Fetch open issues (excluding PRs) for a public GitHub repo URL."""
    data = _snapshot_for(repo_url)
    return json.dumps(
        {
            "repo_url": data["repo_url"],
            "open_issues": data["issues"],
            "count": len(data["issues"]),
        },
        indent=2,
    )


@tool
def get_repo_pull_requests(repo_url: str) -> str:
    """Fetch open pull requests for a public GitHub repo URL."""
    data = _snapshot_for(repo_url)
    return json.dumps(
        {
            "repo_url": data["repo_url"],
            "open_pull_requests": data["pull_requests"],
            "count": len(data["pull_requests"]),
        },
        indent=2,
    )


@tool
def get_repo_branches(repo_url: str) -> str:
    """Fetch branch list for a public GitHub repo URL."""
    data = _snapshot_for(repo_url)
    return json.dumps(
        {
            "default_branch": data["meta"].get("default_branch"),
            "branches": data["branches"],
            "count": len(data["branches"]),
        },
        indent=2,
    )
