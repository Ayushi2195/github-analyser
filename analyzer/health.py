"""Transparent, deterministic repository-maintenance health scoring."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _parse_github_date(value: str | None) -> datetime | None: #this gives time stamp for
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_days(value: str | None, now: datetime) -> int | None: #give age in day for a time stamp in order to calculate how old is the last code push, last PR creation, last branch update etc. which are important signals for health scoring
    parsed = _parse_github_date(value)
    if not parsed:
        return None
    return max(0, (now - parsed).days)


def _root_file_evidence(files: list[dict]) -> tuple[set[str], dict[str, set[str]]]: # returns a set of file names at the root like README.md, LICENSE, CONTRIBUTING.md, CI/CD config files etc. This helps in checking these imp files are present or not
    names = {str(item.get("name", "")).lower() for item in files}
    children = {
        str(item.get("name", "")).lower(): { 
            str(child).lower() for child in (item.get("children") or [])
        }
        for item in files
        if item.get("type") == "dir" 
    }
    return names, children


def compute_health_score( 
    snapshot: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Score observable maintenance signals, not popularity or code quality."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    meta = snapshot.get("meta", {}) #meta contains repo metadata like description, stars, forks, default branch, primary language, license etc. which are important signals for health scoring
    files = snapshot.get("files", [])
    issues = snapshot.get("issues", []) #snapshot contains all the data fetched from GitHub API in one call
    pull_requests = snapshot.get("pull_requests", [])
    branches = snapshot.get("branches", [])
    stats = snapshot.get("stats", {})
    file_names, directory_children = _root_file_evidence(files)

    score = 60
    notes: list[str] = []
    breakdown: list[dict[str, Any]] = []

    def record(criterion: str, change: int, result: str, note: str | None = None) -> None: #record is 
        nonlocal score
        score += change
        breakdown.append({
            "criterion": criterion,
            "change": change,
            "deduction": max(0, -change),
            "result": result,
        })
        if note:
            notes.append(note)

    if meta.get("description"): #description present so +5 points
        record("Repository description", 5, "Present", "Repository purpose is documented") #means 
    else:
        record("Repository description", -3, "Missing", "Missing repository description")

    if "readme.md" in file_names: #//ly
        record("Root README", 10, "Present", "Root README is available")
    else:
        record("Root README", -10, "Missing", "No README.md at repository root")

    if meta.get("license"):
        record("License", 5, str(meta["license"]), f"License detected: {meta['license']}")
    else:
        record("License", 0, "Not detected", "No license detected")

    github_children = directory_children.get(".github", set())
    has_contributing = "contributing.md" in file_names or "contributing.md" in github_children
    record(
        "Contribution guide", #have positive points if present
        5 if has_contributing else 0,
        "Present" if has_contributing else "Not detected",
        "Contribution guide is available" if has_contributing else "No CONTRIBUTING.md detected",
    )

    ci_names = {
        ".travis.yml", ".gitlab-ci.yml", "azure-pipelines.yml", "jenkinsfile",
        "circle.yml", ".circleci",
    }
    has_ci = bool(file_names & ci_names) or "workflows" in github_children
    record(
        "Automated CI/CD",
        8 if has_ci else 0,
        "Configuration detected" if has_ci else "Not detected",
        "Automated CI/CD configuration detected" if has_ci else "No CI/CD configuration detected at inspected paths",
    )

    activity_age = _age_days(meta.get("pushed_at") or meta.get("updated_at"), now) #age to calculate stale prs or issues or branches
    if activity_age is None:
        activity_change, activity_result = 0, "Date unavailable"
    elif activity_age <= 30:
        activity_change, activity_result = 12, f"Last code push {activity_age} days ago"
    elif activity_age <= 90:
        activity_change, activity_result = 8, f"Last code push {activity_age} days ago"
    elif activity_age <= 180:
        activity_change, activity_result = 3, f"Last code push {activity_age} days ago"
    elif activity_age <= 365:
        activity_change, activity_result = 0, f"Last code push {activity_age} days ago"
    else:
        activity_change, activity_result = -8, f"No code push for {activity_age} days"
    record("Recent code activity", activity_change, activity_result, activity_result)

    open_issues = int(stats.get("open_issues_total", len(issues)) or 0)
    stars = int(meta.get("stars") or 0)
    issue_ratio = open_issues / max(stars, 10)
    if open_issues <= 10:
        issue_change, issue_status = 3, "manageable"
    elif issue_ratio <= 0.02:
        issue_change, issue_status = 3, "low relative to community size"
    elif issue_ratio <= 0.10:
        issue_change, issue_status = 0, "proportionate to community size"
    elif issue_ratio <= 0.50:
        issue_change, issue_status = -5, "elevated relative to community size"
    else:
        issue_change, issue_status = -10, "high relative to community size"
    ratio_result = f"{open_issues} open / {stars} stars; {issue_status}"
    record("Normalized issue load", issue_change, ratio_result, ratio_result)

    pr_ages = [
        age for age in (_age_days(pr.get("created_at"), now) for pr in pull_requests)
        if age is not None
    ]
    stale_prs = sum(age > 180 for age in pr_ages)
    stale_pr_ratio = stale_prs / len(pr_ages) if pr_ages else 0.0
    if not pr_ages:
        pr_change, pr_result = 0, "No dated open PRs in sample"
    elif stale_prs == 0:
        pr_change, pr_result = 5, f"0 of {len(pr_ages)} sampled PRs older than 180 days"
    elif stale_pr_ratio <= 0.20:
        pr_change, pr_result = 0, f"{stale_prs} of {len(pr_ages)} sampled PRs older than 180 days"
    elif stale_pr_ratio <= 0.50:
        pr_change, pr_result = -5, f"{stale_prs} of {len(pr_ages)} sampled PRs older than 180 days"
    else:
        pr_change, pr_result = -10, f"{stale_prs} of {len(pr_ages)} sampled PRs older than 180 days"
    record("Pull-request freshness", pr_change, pr_result, pr_result)

    dated_feature_branches = [
        age for branch in branches
        if branch.get("name") != meta.get("default_branch")
        for age in [_age_days(branch.get("last_commit_date"), now)]
        if age is not None
    ]
    stale_branches = sum(age > 180 for age in dated_feature_branches)
    stale_branch_ratio = stale_branches / len(dated_feature_branches) if dated_feature_branches else 0.0
    if len(branches) > 50 and stale_branch_ratio > 0.50:
        branch_change = -6
        branch_result = f"{len(branches)} sampled; {stale_branches}/{len(dated_feature_branches)} dated non-default branches stale"
    elif len(branches) > 25:
        branch_change = -3
        branch_result = f"{len(branches)} sampled branches; review branch cleanup"
    else:
        branch_change = 0
        branch_result = f"{len(branches)} sampled branches"
    record("Branch hygiene", branch_change, branch_result, branch_result)

    protected = sum(1 for branch in branches if branch.get("protected"))
    record(
        "Branch protection",
        2 if protected else 0,
        f"{protected} protected" if protected else "None detected; optional hardening recommendation",
        f"{protected} protected branch(es) detected" if protected else "No protected branches detected; no score deducted",
    )

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
        "notes": notes,
        "breakdown": breakdown,
        "baseline": 60,
        "metrics": {
            "open_issues_total": open_issues,
            "stars": stars,
            "issues_per_star": round(issue_ratio, 4),
            "issue_load_status": issue_status,
            "sampled_prs_with_dates": len(pr_ages),
            "stale_pr_count": stale_prs,
            "stale_pr_ratio": round(stale_pr_ratio, 4),
            "activity_age_days": activity_age,
            "has_ci": has_ci,
            "has_contributing": has_contributing,
            "protected_branch_count": protected,
        },
    }
