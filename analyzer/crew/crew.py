"""
CrewAI workflow: LLM for structure; deterministic sections for issues/PRs/branches.
"""
from __future__ import annotations

from crewai import Crew, Process

from analyzer.github_api import clear_snapshot_cache, fetch_repo_snapshot
from analyzer.health import compute_health_score
from analyzer.report_builder import (
    build_branch_snapshot,
    build_branches_section,
    build_executive_summary,
    build_issues_section,
    build_pull_requests_section,
    build_structure_section,
)

from .tasks import structure_task


def _task_output(task) -> str:
    if task.output and task.output.raw:
        return task.output.raw.strip()
    return "_No output generated._"


def _health_section(snapshot: dict, health: dict) -> str:
    meta = snapshot.get("meta", {})
    stats = snapshot.get("stats", {})
    notes = "\n".join(f"- {note}" for note in health["notes"])
    deductions = [item for item in health.get("breakdown", []) if item.get("deduction")]
    deduction_lines = "\n".join(
        f"- **-{item['deduction']} points — {item['criterion']}:** {item['result']}"
        for item in deductions
    ) or "- **No deductions:** all checked repository-health signals passed."
    description = meta.get("description") or "No repository description was provided on GitHub."
    return (
        f"**Score:** {health['score']}/100 ({health['label']})\n\n"
        f"**Repository context:** {description} The project primarily uses "
        f"**{meta.get('language') or 'an unspecified language'}**, has "
        f"**{meta.get('stars') or 0} stars** and **{meta.get('forks') or 0} forks**, "
        f"and develops on **{meta.get('default_branch') or 'an unknown default branch'}**. "
        f"GitHub currently reports **{stats.get('open_issues_total', len(snapshot.get('issues', [])))} open issues** "
        f"and **{stats.get('open_prs_total', len(snapshot.get('pull_requests', [])))} open PRs**.\n\n"
        f"### Signals\n\n{notes}\n\n"
        f"### How This Score Is Calculated\n\n"
        f"RepoFlow uses a transparent, rule-based score rather than asking the AI to guess. "
        f"Every repository starts at **100 points**. It checks the repository description, root README, "
        f"sampled issue and PR volume, branch count, license, and branch protection.\n\n"
        f"{deduction_lines}\n\n"
        f"**Labels:** 80–100 = Healthy, 60–79 = Needs attention, below 60 = At risk. "
        f"The score is a fast maintenance signal, not a judgment of code quality or security."
    )


def run_analysis_result(repo_url: str) -> dict:
    print(f"Analyzing: {repo_url}", flush=True)
    clear_snapshot_cache()
    snapshot = fetch_repo_snapshot(repo_url)
    full_name = snapshot["meta"].get("full_name", repo_url)
    health = compute_health_score(snapshot)

    structure = structure_task(repo_url, snapshot)

    print("Running structure agent...", flush=True)
    crew = Crew(
        agents=[structure.agent],
        tasks=[structure],
        process=Process.sequential,
        cache=False,
        verbose=False,
    )
    crew.kickoff()
    clear_snapshot_cache()

    print("Running issues agent...", flush=True)
    print("Running PR agent...", flush=True)
    print("Running branch agent...", flush=True)
    print("Generating report...", flush=True)
    ai_overview = _task_output(structure)
    structure_md = build_structure_section(snapshot, ai_overview)
    summary_md = build_executive_summary(snapshot, health)
    health_md = _health_section(snapshot, health)
    issues_md = build_issues_section(snapshot)
    prs_md = build_pull_requests_section(snapshot)
    branch_snapshot_md = build_branch_snapshot(snapshot)
    branches_md = build_branches_section(snapshot)

    markdown_report = f"""# 📊 GitHub Repository Analysis Report

**Repository:** [{full_name}]({repo_url})

---

<h2 class="report-heading report-heading-green">🏥 Repository Health</h2>

{health_md}

---

{summary_md}

---

{structure_md}

---

<h2 class="report-heading report-heading-yellow">🐛 Open Issues</h2>

{issues_md}

---

<h2 class="report-heading report-heading-yellow">🔀 Pull Requests</h2>

{prs_md}

---

<h2 class="report-heading report-heading-yellow">🌿 Branch Analysis</h2>

{branch_snapshot_md}

{branches_md}
"""

    return {
        "markdown": markdown_report,
        "snapshot": snapshot,
        "health": health,
        "sections": {
            "health": health_md,
            "summary": summary_md,
            "structure": structure_md,
            "issues": issues_md,
            "pull_requests": prs_md,
            "branch_snapshot": branch_snapshot_md,
            "branches": branches_md,
            "branch_count": len(snapshot.get("branches", [])),
        },
    }


def run_analysis(repo_url: str) -> str:
    return run_analysis_result(repo_url)["markdown"]
