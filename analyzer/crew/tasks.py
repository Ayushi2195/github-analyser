import json

from crewai import Task

from analyzer.report_format import (
    BRANCHES_FORMAT,
    ISSUES_FORMAT,
    PRS_FORMAT,
    STRUCTURE_FORMAT,
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
            f"Root files and folders:\n{files_str}\n\n"
            f"{STRUCTURE_FORMAT}\n\n"
            "Be specific and detailed. Reference actual file and folder names. "
            "Do not write generic filler."
        ),
        expected_output=(
            "Detailed Markdown with Project Overview, Tech Stack, "
            "Key Files and Folders (every item), and Repository Stats."
        ),
        agent=structure_agent(),
    )


def issues_task(repo_url: str, snapshot: dict) -> Task:
    issues_str = json.dumps(snapshot["issues"], indent=2)
    count = len(snapshot["issues"])
    return Task(
        description=(
            f"Analyze open issues for: {repo_url}\n\n"
            f"Total open issues in dataset: {count}\n\n"
            f"Open issues JSON (include ALL {count} in your report):\n{issues_str}\n\n"
            f"{ISSUES_FORMAT}\n\n"
            "Be exhaustive — every issue must appear exactly once."
        ),
        expected_output="Detailed Markdown Open Issues Report grouped by labels.",
        agent=issue_agent(),
    )


def pull_requests_task(repo_url: str, snapshot: dict) -> Task:
    prs_str = json.dumps(snapshot["pull_requests"], indent=2)
    count = len(snapshot["pull_requests"])
    return Task(
        description=(
            f"Analyze pull requests for: {repo_url}\n\n"
            f"Open PR count: {count}\n\n"
            f"Pull requests JSON:\n{prs_str}\n\n"
            f"{PRS_FORMAT}\n\n"
            "Use real PR numbers, authors, branch names, and URLs from the data."
        ),
        expected_output="Detailed Markdown Pull Request Analysis Report.",
        agent=pull_request_agent(),
    )


def branches_task(repo_url: str, snapshot: dict) -> Task:
    branches_str = json.dumps(snapshot["branches"], indent=2)
    default_branch = snapshot["meta"].get("default_branch", "main")
    return Task(
        description=(
            f"Analyze branches for: {repo_url}\n\n"
            f"Default branch: {default_branch}\n\n"
            f"Branches JSON:\n{branches_str}\n\n"
            f"{BRANCHES_FORMAT}\n\n"
            "Classify every branch. Use exact branch names from the data."
        ),
        expected_output="Detailed Markdown branch analysis with all sections.",
        agent=branch_agent(),
    )
