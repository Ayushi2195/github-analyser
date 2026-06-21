import json

from crewai import Task

from analyzer.report_format import (
    BRANCHES_FORMAT,
    ISSUES_FORMAT,
    PRS_FORMAT,
)

from .agents import branch_agent, issue_agent, pull_request_agent, structure_agent


def structure_task(repo_url: str, snapshot: dict) -> Task:
    meta_str = json.dumps(snapshot["meta"], indent=2)
    files_str = json.dumps(snapshot["files"], indent=2)
    return Task(
        description=(
            f"Analyze repository structure for: {repo_url}\n\n"
            f"Call get_repo_structure with repo_url={repo_url!r} if needed, "
            "but primary data is below — use it.\n\n"
            f"Repository metadata:\n{meta_str}\n\n"
            f"Root files, selected content previews, and directory children:\n{files_str}\n\n"
            "Write 2-4 concise English sentences explaining the project's purpose and likely data flow. "
            "Use only evidence present above. Do not list the tech stack or describe every file; Python does that deterministically. "
            "Do not use words such as likely, probably, possibly, or may. Do not output any non-English text. "
            "If evidence is insufficient, state exactly what could not be determined."
        ),
        expected_output=(
            "A short evidence-based English project overview with no title or file-by-file list."
        ),
        agent=structure_agent(),
    )


def issues_task(repo_url: str, snapshot: dict) -> Task:
    issues_str = json.dumps(snapshot["issues"], indent=2)
    count = len(snapshot["issues"])
    stats_str = json.dumps(snapshot.get("stats", {}), indent=2)
    return Task(
        description=(
            f"Analyze open issues for: {repo_url}\n\n"
            f"GitHub API stats:\n{stats_str}\n\n"
            f"You have been given EXACTLY these {count} sampled issues from the GitHub API:\n{issues_str}\n\n"
            f"{ISSUES_FORMAT}\n\n"
            "You MUST reference specific issue numbers, titles, and authors. "
            "NEVER make general statements. If data is missing, say 'Data unavailable'."
        ),
        expected_output="Detailed Markdown Open Issues Report grouped by labels.",
        agent=issue_agent(),
    )


def pull_requests_task(repo_url: str, snapshot: dict) -> Task:
    prs_str = json.dumps(snapshot["pull_requests"], indent=2)
    count = len(snapshot["pull_requests"])
    stats_str = json.dumps(snapshot.get("stats", {}), indent=2)
    return Task(
        description=(
            f"Analyze pull requests for: {repo_url}\n\n"
            f"GitHub API stats:\n{stats_str}\n\n"
            f"You have been given EXACTLY these {count} sampled pull requests from the GitHub API:\n{prs_str}\n\n"
            f"{PRS_FORMAT}\n\n"
            "Use real PR numbers, authors, branch names, and URLs from the data. "
            "NEVER make general statements. If data is missing, say 'Data unavailable'."
        ),
        expected_output="Detailed Markdown Pull Request Analysis Report.",
        agent=pull_request_agent(),
    )


def branches_task(repo_url: str, snapshot: dict) -> Task:
    branches_str = json.dumps(snapshot["branches"], indent=2)
    default_branch = snapshot["meta"].get("default_branch", "main")
    stats_str = json.dumps(snapshot.get("stats", {}), indent=2)
    return Task(
        description=(
            f"Analyze branches for: {repo_url}\n\n"
            f"Default branch: {default_branch}\n\n"
            f"GitHub API stats:\n{stats_str}\n\n"
            f"You have been given EXACTLY these sampled branches from the GitHub API:\n{branches_str}\n\n"
            f"{BRANCHES_FORMAT}\n\n"
            "Classify every sampled branch. Use exact branch names from the data. "
            "For each interesting branch, write a one-line interpretation instead of saying "
            "'Branch name indicates X'. Examples: feat_config_files means "
            "'Feature work: configuration file improvements, not yet merged'; mcp means "
            "'Likely MCP (Model Context Protocol) integration work in progress'; query-sets means "
            "'Feature branch for query set functionality'. If a branch has 0 open PRs targeting it, "
            "add '(stale - no active PR)'. If it has PRs, add '(active - N open PRs targeting it)'. "
            "NEVER make general statements. If data is missing, say 'Data unavailable'."
        ),
        expected_output="Detailed Markdown branch analysis with all sections.",
        agent=branch_agent(),
    )
