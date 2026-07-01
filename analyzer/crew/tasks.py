import json

from crewai import Task

from .agents import security_agent, structure_agent


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


def security_task(repo_url: str, snapshot: dict) -> Task:
    scorecard = snapshot.get("openssf_scorecard") or {}
    top_checks = sorted(scorecard.get("checks") or [], key=lambda item: item.get("score", 0), reverse=True)[:3]
    payload = {
        "scorecard": {
            "available": bool(scorecard.get("available")),
            "score": scorecard.get("score"),
            "checks": top_checks,
        },
        "osv_vulnerabilities": snapshot.get("osv_vulnerabilities") or {},
        "best_practices_badge": snapshot.get("best_practices_badge") or {},
        "security_insights": snapshot.get("security_insights") or {},
    }
    payload_json = json.dumps(payload, indent=2)
    return Task(
        description=(
            f"Write a plain-English security summary for: {repo_url}\n\n"
            f"You are given these OpenSSF-related results as JSON:\n{payload_json}\n\n"
            "Write exactly 4-5 sentences in English only. No bullet points, no headings, no markdown lists. "
            "Explain the overall security posture, the biggest strength, the biggest gap, and one specific actionable recommendation "
            "for the maintainer. Do not repeat raw API field names unless you briefly explain them. "
            "Do not mention that you are an AI."
        ),
        expected_output="Exactly 4-5 sentences of plain-English security summary in English only.",
        agent=security_agent(),
    )
