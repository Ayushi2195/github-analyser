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


def run_analysis(repo_url: str) -> str:
    clear_snapshot_cache()
    snapshot = fetch_repo_snapshot(repo_url)
    full_name = snapshot["meta"].get("full_name", repo_url)

    structure = structure_task(repo_url, snapshot)

    crew = Crew(
        agents=[structure.agent],
        tasks=[structure],
        process=Process.sequential,
        verbose=True,
    )
    crew.kickoff()
    clear_snapshot_cache()

    issues_md = build_issues_section(snapshot)
    prs_md = build_pull_requests_section(snapshot)
    branches_md = build_branches_section(snapshot)

    return f"""# 📊 GitHub Repository Analysis Report

**Repository:** [{full_name}]({repo_url})

---

## 🏥 Repository Health

{_health_section(snapshot)}

---

## 🗂️ Repository Structure

{_task_output(structure)}

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
