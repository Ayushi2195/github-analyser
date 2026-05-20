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
    file_names = {f["name"].lower() for f in files}

    if not meta.get("description"):
        score -= 10
        notes.append("Missing repository description")
    if "readme.md" not in file_names:
        score -= 15
        notes.append("No README.md at repository root")
    if len(issues) > 10:
        score -= 10
        notes.append(f"High open issue count ({len(issues)} sampled)")
    if len(pull_requests) > 8:
        score -= 8
        notes.append(f"Many open pull requests ({len(pull_requests)} sampled)")
    if len(branches) > 15:
        score -= 12
        notes.append(f"Branch sprawl ({len(branches)} branches)")
    if not meta.get("license"):
        score -= 5
        notes.append("No license detected")

    protected = sum(1 for b in branches if b.get("protected"))
    if branches and protected == 0:
        score -= 5
        notes.append("No protected branches")

    score = max(0, min(100, score))
    if score >= 80:
        label = "Healthy"
    elif score >= 60:
        label = "Needs attention"
    else:
        label = "At risk"

    return {"score": score, "label": label, "notes": notes or ["No major risks detected"]}
