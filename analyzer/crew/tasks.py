import json

from crewai import Task

from .agents import security_agent


def _compact_check(check: dict) -> dict:
    reason = str(check.get("reason") or "")
    return {
        "name": check.get("name"),
        "score": check.get("score"),
        "reason": reason[:180],
    }


def security_task(repo_url: str, snapshot: dict) -> Task:
    scorecard = snapshot.get("openssf_scorecard") or {}
    checks = scorecard.get("checks") or []
    scored_checks = [check for check in checks if isinstance(check.get("score"), (int, float))]
    weak_checks = sorted(scored_checks, key=lambda item: item.get("score", 10))[:4]
    strong_checks = sorted(scored_checks, key=lambda item: item.get("score", 0), reverse=True)[:2]
    osv = snapshot.get("osv_vulnerabilities") or {}
    vulns = osv.get("vulns") or []
    payload = {
        "scorecard": {
            "available": bool(scorecard.get("available")),
            "score": scorecard.get("score"),
            "weak_checks": [_compact_check(check) for check in weak_checks],
            "strong_checks": [_compact_check(check) for check in strong_checks],
        },
        "osv": {
            "available": bool(osv.get("available", True)),
            "vulnerability_count": len(vulns),
            "ids": [vuln.get("id") for vuln in vulns[:3]],
        },
        "best_practices_badge": {
            "found": bool((snapshot.get("best_practices_badge") or {}).get("found")),
            "level": (snapshot.get("best_practices_badge") or {}).get("level"),
        },
        "security_insights": snapshot.get("security_insights") or {},
    }
    payload_json = json.dumps(payload, separators=(",", ":"))
    return Task(
        description=(
            f"Write a plain-English security summary for: {repo_url}\n\n"
            f"Security signals JSON:\n{payload_json}\n\n"
            "Write exactly 3 concise English sentences. No bullet points, no headings, no markdown lists. "
            "Explain the overall security posture, the biggest strength, the biggest gap, and one specific actionable recommendation "
            "for the maintainer. Do not repeat raw API field names unless you briefly explain them. "
            "Do not mention that you are an AI."
        ),
        expected_output="Exactly 3 concise sentences of plain-English security summary.",
        agent=security_agent(),
    )
