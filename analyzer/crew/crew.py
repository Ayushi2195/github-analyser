"""
CrewAI workflow: LLM for structure; deterministic sections for issues/PRs/branches.
"""
from __future__ import annotations

from crewai import Crew, Process

from analyzer.github_api import clear_snapshot_cache, fetch_repo_snapshot
from analyzer.health import compute_health_score
from analyzer.report_builder import (
    build_branches_section,
    build_issues_section,
    build_pull_requests_section,
)

from .tasks import structure_task


def _task_output(task) -> str:
    if task.output and task.output.raw:
        return task.output.raw.strip()
    return "_No output generated._"


def _health_section(snapshot: dict) -> str:
    health = compute_health_score(snapshot)
    notes = "\n".join(f"- {note}" for note in health["notes"])
    return (
        f"**Score:** {health['score']}/100 ({health['label']})\n\n"
        f"**Signals:**\n{notes}"
    )


def run_analysis_result(repo_url: str) -> dict:
    clear_snapshot_cache()
    snapshot = fetch_repo_snapshot(repo_url)
    full_name = snapshot["meta"].get("full_name", repo_url)
    health = compute_health_score(snapshot)

    structure = structure_task(repo_url, snapshot)

    crew = Crew(
        agents=[structure.agent],
        tasks=[structure],
        process=Process.sequential,
        verbose=True,
    )
    crew.kickoff()
    clear_snapshot_cache()

    structure_md = _task_output(structure)
    health_md = _health_section(snapshot)
    issues_md = build_issues_section(snapshot)
    prs_md = build_pull_requests_section(snapshot)
    branches_md = build_branches_section(snapshot)

    markdown_report = f"""# 📊 GitHub Repository Analysis Report

**Repository:** [{full_name}]({repo_url})

---

## 🏥 Repository Health

{health_md}

---

## 🗂️ Repository Structure

{structure_md}

---

## 🐛 Open Issues

{issues_md}

---

## 🔀 Pull Requests

{prs_md}

---

## 🌿 Branch Analysis

{branches_md}
"""

    return {
        "markdown": markdown_report,
        "snapshot": snapshot,
        "health": health,
        "sections": {
            "health": health_md,
            "structure": structure_md,
            "issues": issues_md,
            "pull_requests": prs_md,
            "branches": branches_md,
            "branch_count": len(snapshot.get("branches", [])),
        },
    }


def run_analysis(repo_url: str) -> str:
    return run_analysis_result(repo_url)["markdown"]
