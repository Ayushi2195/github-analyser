"""
Deterministic report sections — guaranteed detail for issues, PRs, and branches.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any


def _label_group(labels: list[str]) -> str:
    if not labels:
        return "Uncategorized"
    return labels[0]


def _top_counts(counter: Counter, limit: int = 5) -> str:
    if not counter:
        return "Data unavailable"
    return " | ".join(f"{name}: {count}" for name, count in counter.most_common(limit))


def _label_counts(items: list[dict]) -> Counter:
    counts: Counter = Counter()
    for item in items:
        labels = item.get("labels", [])
        if labels:
            for label in labels:
                counts[label] += 1
        else:
            counts["unlabeled"] += 1
    return counts


def _author_counts(items: list[dict]) -> Counter:
    return Counter(item.get("author") or "unknown" for item in items)


def _clean_branch_token(value: str) -> str:
    value = value.replace("_", " ").replace("-", " ").replace("/", " / ")
    return " ".join(value.split())


def _branch_category(name: str) -> tuple[str, str]:
    lower = name.lower()
    if lower.startswith("dependabot/"):
        return "Dependabot updates", "Automated dependency management branch created by Dependabot."
    if lower.startswith("copilot/"):
        issue_hint = ""
        match = re.search(r"(?:fix|issue)[-/]?(\d+)", lower)
        if match:
            issue_hint = f" for issue #{match.group(1)}"
        return "Copilot suggestions", f"GitHub Copilot suggested code change{issue_hint}."
    if lower.startswith(("ci/", "ci-", "test/", "tests/", "e2e/", "build/", "workflow/", "github-actions/")) or "ci" in lower or "e2e" in lower:
        return "CI/CD work", f"CI/CD or test automation work: {_clean_branch_token(name)}."
    if lower.startswith(("fix/", "fix-", "bug/", "bugfix/", "bugfix-", "hotfix/", "hotfix-")) or "fix" in lower:
        topic = re.sub(r"^(bugfix|hotfix|fix|bug)[/-]?", "", name, flags=re.IGNORECASE)
        return "Bug fixes", f"Bug fix targeting {_clean_branch_token(topic) or 'a reported defect'}."
    if lower.startswith(("feature/", "feature-", "feat/", "feat-")):
        topic = re.sub(r"^(feature|feat)[/-]?", "", name, flags=re.IGNORECASE)
        return "Feature branches", f"Feature work for {_clean_branch_token(topic) or 'a new capability'}."
    if lower.startswith(("release/", "release-", "rel/", "v")):
        return "Release branches", f"Release or version preparation branch: {_clean_branch_token(name)}."
    if lower.startswith(("docs/", "docs-", "doc/", "doc-")):
        topic = re.sub(r"^(docs|doc)[/-]?", "", name, flags=re.IGNORECASE)
        return "Documentation", f"Documentation update for {_clean_branch_token(topic) or 'project docs'}."
    return "Other branches", f"Branch name indicates {_clean_branch_token(name)}."


def _branch_interest_score(name: str, category: str) -> int:
    lower = name.lower()
    score = 0
    if category in {"Feature branches", "Bug fixes", "CI/CD work", "Documentation"}:
        score += 5
    if category in {"Dependabot updates", "Copilot suggestions"}:
        score -= 5
    if any(token in lower for token in ("memory", "security", "auth", "database", "migration", "api", "e2e", "performance")):
        score += 4
    score += min(len(name) // 12, 4)
    return score


def build_issues_section(snapshot: dict[str, Any]) -> str:
    issues = snapshot.get("issues", [])
    stats = snapshot.get("stats", {})
    total = stats.get("open_issues_total", len(issues))
    sampled = stats.get("issues_sampled", len(issues))
    lines = [
        "## Open Issues Report",
        "",
        "### Real Numbers Summary",
        "",
        f"- **Open issues:** {total} total, {sampled} sampled",
        f"- **Sample source:** GitHub API page 1, up to {stats.get('api_page_size', 100)} items fetched",
        f"- **Label breakdown:** {_top_counts(_label_counts(issues))}",
        f"- **Top reporters:** {_top_counts(_author_counts(issues), limit=3)}",
        "",
    ]
    if not issues:
        if total:
            lines.append("Data unavailable: GitHub reported open issues, but no issue records were available in the sampled API response.")
        else:
            lines.append("No open issues at this time.")
        return "\n".join(lines)

    lines.extend(["### Sampled Issue Details", ""])

    grouped: dict[str, list[dict]] = defaultdict(list)
    for issue in issues:
        grouped[_label_group(issue.get("labels", []))].append(issue)

    for group_name in sorted(grouped.keys()):
        lines.append(f"### {group_name}")
        lines.append("")
        for issue in grouped[group_name]:
            author = issue.get("author") or "unknown"
            url = issue.get("url", "#")
            lines.append(
                f"- **Issue #{issue['number']}:** {issue['title']} - "
                f"reported by @{author} - [View issue]({url})"
            )
            if issue.get("labels"):
                lines.append(f"  - Labels: {', '.join(issue['labels'])}")
            if issue.get("comments"):
                lines.append(f"  - Comments: {issue['comments']}")
        lines.append("")

    return "\n".join(lines).strip()


def build_pull_requests_section(snapshot: dict[str, Any]) -> str:
    prs = snapshot.get("pull_requests", [])
    stats = snapshot.get("stats", {})
    total = stats.get("open_prs_total", len(prs))
    sampled = stats.get("pull_requests_sampled", len(prs))
    draft_count = sum(1 for pr in prs if pr.get("draft"))
    base_counts = Counter(pr.get("base") or "unknown" for pr in prs)
    lines = [
        "## Pull Request Analysis Report",
        "",
        "### Real Numbers Summary",
        "",
        f"- **Open pull requests:** {total} total, {sampled} sampled",
        f"- **Draft PRs in sample:** {draft_count}",
        f"- **Target branches:** {_top_counts(base_counts)}",
        f"- **Top PR authors:** {_top_counts(_author_counts(prs), limit=3)}",
        "",
    ]
    if not prs:
        if total:
            lines.append("Data unavailable: GitHub reported open PRs, but no PR records were available in the sampled API response.")
        else:
            lines.append("There are currently **no open pull requests**.")
        return "\n".join(lines)

    lines.append("### Open Pull Requests")
    lines.append("")

    for pr in prs:
        author = pr.get("author") or "unknown"
        url = pr.get("url", "#")
        draft = " (draft)" if pr.get("draft") else ""
        lines.append(
            f"- **PR #{pr['number']}:** \"{pr['title']}\"{draft} - "
            f"submitted by @{author}, **{pr.get('head')}** -> **{pr.get('base')}** - "
            f"[View PR]({url})"
        )
        lines.append(
            f"  - Likely intent: changes on branch `{pr.get('head')}` "
            f"targeting `{pr.get('base')}`."
        )

    return "\n".join(lines)


def build_branches_section(snapshot: dict[str, Any]) -> str:
    branches = snapshot.get("branches", [])
    default = snapshot.get("meta", {}).get("default_branch", "main")
    stats = snapshot.get("stats", {})
    protected_count = sum(1 for branch in branches if branch.get("protected"))
    prs = snapshot.get("pull_requests", [])
    pr_targets = Counter(pr.get("base") or "unknown" for pr in prs)
    lines = ["## Branches", ""]

    lines.append("### Real Numbers Summary")
    lines.append("")
    lines.append(f"- **Default branch:** {default}")
    lines.append(f"- **Branches sampled:** {stats.get('branches_sampled', len(branches))}")
    lines.append(f"- **Protected branches in sample:** {protected_count}")
    lines.append("")

    categorized: dict[str, list[dict]] = defaultdict(list)
    protected = []
    for branch in branches:
        name = branch.get("name", "")
        if not name:
            continue
        if branch.get("protected"):
            protected.append(name)
        if name == default:
            categorized["Default branch"].append(
                {
                    "name": name,
                    "description": "Primary default branch for repository development.",
                    "score": 0,
                }
            )
            continue
        category, description = _branch_category(name)
        categorized[category].append(
            {
                "name": name,
                "description": description,
                "score": _branch_interest_score(name, category),
            }
        )

    category_order = [
        "Default branch",
        "Dependabot updates",
        "Copilot suggestions",
        "CI/CD work",
        "Feature branches",
        "Bug fixes",
        "Documentation",
        "Release branches",
        "Other branches",
    ]

    lines.append("### Branch Categories")
    lines.append("")
    for category in category_order:
        group = categorized.get(category, [])
        if not group:
            continue
        example_names = ", ".join(item["name"] for item in group[:3])
        suffix = f" Examples: {example_names}." if example_names else ""
        if category == "Dependabot updates":
            meaning = "automated dependency management"
        elif category == "Copilot suggestions":
            meaning = "AI-suggested fixes or code changes"
        elif category == "CI/CD work":
            meaning = "pipeline, workflow, or test automation work"
        elif category == "Bug fixes":
            meaning = "defect fixes inferred from branch names"
        elif category == "Feature branches":
            meaning = "new feature or capability work"
        elif category == "Documentation":
            meaning = "documentation updates"
        elif category == "Release branches":
            meaning = "release or version preparation"
        elif category == "Default branch":
            meaning = "primary development line"
        else:
            meaning = "branches that do not match a stronger naming pattern"
        lines.append(f"- **{category}:** {len(group)} branch(es) — {meaning}.{suffix}")
    lines.append("")

    interesting = sorted(
        [
            item
            for category, group in categorized.items()
            if category not in {"Default branch", "Dependabot updates", "Copilot suggestions"}
            for item in group
        ],
        key=lambda item: item["score"],
        reverse=True,
    )[:5]

    lines.append("### Most Interesting Non-Automated Branches")
    lines.append("")
    if interesting:
        for item in interesting:
            open_prs = pr_targets.get(item["name"], 0)
            pr_text = f"{open_prs} open PR(s) target this branch" if open_prs else "No sampled open PRs target this branch"
            lines.append(f"- **{item['name']}** — {item['description']} {pr_text}.")
    else:
        lines.append("No non-automated branch names with enough signal were found in the sampled branch list.")
    lines.append("")

    lines.append("### Protected Branches")
    lines.append("")
    if protected:
        for name in sorted(protected):
            lines.append(f"- **{name}** — protected")
    else:
        lines.append(
            "No protected branches were found in the sampled branch list. "
            f"Consider protecting **{default}** if direct pushes should be restricted."
        )
    lines.append("")

    return "\n".join(lines).strip()
