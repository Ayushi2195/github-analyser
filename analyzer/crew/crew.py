"""
CrewAI workflow: one compact LLM summary; deterministic report sections.
"""
from __future__ import annotations

from crewai import Crew, Process

from analyzer.github_api import clear_snapshot_cache, fetch_repo_snapshot
from analyzer.report_builder import (
    build_branch_snapshot,
    build_branches_section,
    build_good_first_issues_section,
    build_recommendations_section,
    build_security_section,
    build_security_insights_section,
    build_structure_section,
    build_vulnerabilities_section,
)

from .tasks import security_task


def _task_output(task) -> str:
    if task.output and task.output.raw:
        return task.output.raw.strip()
    return "_No output generated._"


def _fallback_security_summary(snapshot: dict) -> str:
    scorecard = snapshot.get("openssf_scorecard") or {}
    badge = snapshot.get("best_practices_badge") or {}
    osv = snapshot.get("osv_vulnerabilities") or {}
    insights = snapshot.get("security_insights") or {}
    score = scorecard.get("score")
    vulns = osv.get("vulns") or []
    strengths = []
    gaps = []
    if score is not None:
        strengths.append(f"OpenSSF Scorecard is {score}/10")
    if badge.get("found"):
        strengths.append(f"Best Practices badge is {badge.get('level') or 'present'}")
    if not vulns and osv.get("available", True):
        strengths.append("OSV found no vulnerabilities for the default branch commit")
    if not any(insights.values()):
        gaps.append("security policy metadata is missing")
    weak_checks = []
    for check in scorecard.get("checks") or []:
        try:
            if float(check.get("score")) <= 0:
                weak_checks.append(check.get("name") or "a Scorecard check")
        except (TypeError, ValueError):
            continue
    if weak_checks:
        gaps.append(f"{weak_checks[0]} needs attention")
    strength_text = strengths[0] if strengths else "GitHub and OpenSSF data was collected successfully"
    gap_text = gaps[0] if gaps else "no critical gap stands out from the sampled signals"
    return (
        f"The repository security posture is summarized from GitHub, OpenSSF, and OSV data. "
        f"The biggest strength is that {strength_text}. "
        f"The main improvement area is that {gap_text}; maintainers should address that first."
    )


def run_analysis_result(repo_url: str) -> dict:
    print(f"Analyzing: {repo_url}", flush=True)
    clear_snapshot_cache()
    snapshot = fetch_repo_snapshot(repo_url)
    full_name = snapshot["meta"].get("full_name", repo_url)

    security = security_task(repo_url, snapshot)

    print("Running security summary agent...", flush=True)
    try:
        crew = Crew(
            agents=[security.agent],
            tasks=[security],
            process=Process.sequential,
            cache=False,
            verbose=False,
        )
        crew.kickoff() #runs a compact CrewAI task for the plain-English security summary
        security_summary = _task_output(security)
    except Exception as exc:
        print(f"Security summary agent skipped: {type(exc).__name__}: {exc}", flush=True)
        security_summary = _fallback_security_summary(snapshot)
    clear_snapshot_cache()

    print("Building OpenSSF security analysis...", flush=True)
    print("Building development insights...", flush=True)
    print("Generating report...", flush=True)
    structure_md = build_structure_section(snapshot, "")
    security_md = build_security_section(snapshot, security_summary)
    vulnerabilities_md = build_vulnerabilities_section(snapshot)
    security_insights_md = build_security_insights_section(snapshot)
    branch_snapshot_md = build_branch_snapshot(snapshot)
    branches_md = build_branches_section(snapshot)
    good_first_issues_md = build_good_first_issues_section(snapshot)
    recommendations_md = build_recommendations_section(snapshot)

    markdown_report = f"""# 📊 RepoFlow Security & Development Report

**Repository:** [{full_name}]({repo_url})

---

{structure_md}

---

<h2 class="report-heading report-heading-yellow">🛡 OpenSSF Security Analysis</h2>

{security_md}

---

{vulnerabilities_md}

---

{security_insights_md}

---

<h2 class="report-heading report-heading-yellow">🌿 Development Insights</h2>

---

{branch_snapshot_md}

{branches_md}

---

{good_first_issues_md}

---

{recommendations_md}
"""

    security_signal_count = 0
    if (snapshot.get("openssf_scorecard") or {}).get("available"):
        security_signal_count += 1
    if (snapshot.get("best_practices_badge") or {}).get("found"):
        security_signal_count += 1
    if (snapshot.get("osv_vulnerabilities") or {}).get("available", True):
        security_signal_count += 1
    if any((snapshot.get("security_insights") or {}).values()):
        security_signal_count += 1

    security_summary = {
        "score": security_signal_count * 25,
        "label": f"{security_signal_count}/4 security signals present",
        "notes": [],
    }

    return {
        "markdown": markdown_report,
        "snapshot": snapshot,
        "health": security_summary,
        "sections": {
            "security": security_md,
            "vulnerabilities": vulnerabilities_md,
            "security_insights": security_insights_md,
            "structure": structure_md,
            "good_first_issues": good_first_issues_md,
            "recommendations": recommendations_md,
            "branch_snapshot": branch_snapshot_md,
            "branches": branches_md,
            "branch_count": len(snapshot.get("branches", [])),
        },
    }


def run_analysis(repo_url: str) -> str:
    return run_analysis_result(repo_url)["markdown"]
