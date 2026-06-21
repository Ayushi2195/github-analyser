"""
Deterministic repository health score — no LLM.
Gives you a concrete metric interviewers can ask about.
"""
from __future__ import annotations

from typing import Any


def compute_health_score(snapshot: dict[str, Any]) -> dict[str, Any]:
    meta = snapshot.get("meta", {})
    files = snapshot.get("files", [])
    issues = snapshot.get("issues", [])
    pull_requests = snapshot.get("pull_requests", [])
    branches = snapshot.get("branches", [])

    score = 100
    notes: list[str] = []
    breakdown: list[dict[str, Any]] = []
    file_names = {f["name"].lower() for f in files}

    if not meta.get("description"):
        score -= 10
        notes.append("Missing repository description")
        breakdown.append({"criterion": "Repository description", "deduction": 10, "result": "Missing"})
    else:
        breakdown.append({"criterion": "Repository description", "deduction": 0, "result": "Present"})
    if "readme.md" not in file_names:
        score -= 15
        notes.append("No README.md at repository root")
        breakdown.append({"criterion": "Root README", "deduction": 15, "result": "Missing"})
    else:
        breakdown.append({"criterion": "Root README", "deduction": 0, "result": "Present"})
    if len(issues) > 10:
        score -= 10
        notes.append(f"High open issue count ({len(issues)} sampled)")
        breakdown.append({"criterion": "Sampled open issues", "deduction": 10, "result": f"{len(issues)} sampled (>10)"})
    else:
        breakdown.append({"criterion": "Sampled open issues", "deduction": 0, "result": f"{len(issues)} sampled"})
    if len(pull_requests) > 8:
        score -= 8
        notes.append(f"Many open pull requests ({len(pull_requests)} sampled)")
        breakdown.append({"criterion": "Sampled open PRs", "deduction": 8, "result": f"{len(pull_requests)} sampled (>8)"})
    else:
        breakdown.append({"criterion": "Sampled open PRs", "deduction": 0, "result": f"{len(pull_requests)} sampled"})
    if len(branches) > 15:
        score -= 12
        notes.append(f"Branch sprawl ({len(branches)} branches)")
        breakdown.append({"criterion": "Branch count", "deduction": 12, "result": f"{len(branches)} branches (>15)"})
    else:
        breakdown.append({"criterion": "Branch count", "deduction": 0, "result": f"{len(branches)} branches"})
    if not meta.get("license"):
        score -= 5
        notes.append("No license detected")
        breakdown.append({"criterion": "License", "deduction": 5, "result": "Not detected"})
    else:
        breakdown.append({"criterion": "License", "deduction": 0, "result": meta.get("license")})

    protected = sum(1 for b in branches if b.get("protected"))
    if branches and protected == 0:
        score -= 5
        notes.append("No protected branches")
        breakdown.append({"criterion": "Branch protection", "deduction": 5, "result": "None detected"})
    else:
        breakdown.append({"criterion": "Branch protection", "deduction": 0, "result": f"{protected} protected"})

    score = max(0, min(100, score))
    if score >= 80:
        label = "Healthy"
    elif score >= 60:
        label = "Needs attention"
    else:
        label = "At risk"

    return {
        "score": score,
        "label": label,
        "notes": notes or ["No major risks detected"],
        "breakdown": breakdown,
    }
