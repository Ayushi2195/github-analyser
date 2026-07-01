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


