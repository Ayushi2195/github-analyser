"""
Deterministic report sections — guaranteed detail for issues, PRs, and branches.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def _label_group(labels: list[str]) -> str:
    if not labels:
        return "Uncategorized"
    return labels[0]


def build_issues_section(snapshot: dict[str, Any]) -> str:
    issues = snapshot.get("issues", [])
    lines = [
        "## Open Issues Report",
        "",
        f"There are currently **{len(issues)}** open issues on GitHub.",
        "",
    ]
    if not issues:
        lines.append("No open issues at this time.")
        return "\n".join(lines)

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
    lines = [
        "## Pull Request Analysis Report",
        "",
        "### Introduction",
        "",
    ]
    if not prs:
        lines.append(
            "There are currently **no open pull requests**. "
            "The repository has no in-flight code review work at the moment."
        )
        lines.append("")
        lines.append("### Conclusion")
        lines.append("")
        lines.append("No open PRs — development may be paused or changes land directly on branches.")
        return "\n".join(lines)

    lines.append(
        f"This repository has **{len(prs)}** open pull request(s) awaiting review or merge."
    )
    lines.append("")
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

    lines.append("")
    lines.append("### Conclusion")
    lines.append("")
    if len(prs) == 1:
        lines.append(
            f"There is **1** open pull request. Review and merge when checks pass."
        )
    else:
        lines.append(
            f"There are **{len(prs)}** open pull requests — prioritize review to reduce backlog."
        )
    return "\n".join(lines)


def build_branches_section(snapshot: dict[str, Any]) -> str:
    branches = snapshot.get("branches", [])
    default = snapshot.get("meta", {}).get("default_branch", "main")
    lines = ["## Branches", ""]

    lines.append("### Main Branch")
    lines.append("")
    lines.append(f"The main/default branch is: **{default}**")
    lines.append("")

    feature_prefixes = ("feat", "feature", "dev", "fix", "bug", "soda", "mcp", "query")
    release_prefixes = ("release", "rel", "v")

    feature, release, other, protected = [], [], [], []
    for branch in branches:
        name = branch["name"]
        if name == default:
            continue
        if branch.get("protected"):
            protected.append(name)
        lower = name.lower()
        if lower.startswith(release_prefixes):
            release.append(name)
        elif lower.startswith(feature_prefixes) or "-" in name:
            feature.append(name)
        else:
            other.append(name)

    lines.append("### Feature Branches")
    lines.append("")
    if feature:
        for name in sorted(feature):
            lines.append(f"- **{name}** — likely used for feature or topic development.")
    else:
        lines.append("No obvious feature branches (or only default branch exists).")
    lines.append("")

    lines.append("### Release Branches")
    lines.append("")
    if release:
        for name in sorted(release):
            lines.append(f"- **{name}**")
    else:
        lines.append("No explicit release branches identified in the branch list.")
    lines.append("")

    if other:
        lines.append("### Other Branches")
        lines.append("")
        for name in sorted(other):
            lines.append(f"- **{name}**")
        lines.append("")

    lines.append("### Protected Branches")
    lines.append("")
    if protected:
        for name in sorted(protected):
            lines.append(f"- **{name}** — protected")
    else:
        lines.append(
            "No protected branches are configured (all branches show `protected: false`). "
            "Consider protecting **main** to prevent accidental direct pushes."
        )
    lines.append("")

    return "\n".join(lines).strip()
