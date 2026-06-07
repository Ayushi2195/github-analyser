"""
Deterministic report sections — guaranteed detail for issues, PRs, and branches.
"""
from __future__ import annotations

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
    lines = ["## Branches", ""]

    lines.append("### Real Numbers Summary")
    lines.append("")
    lines.append(f"- **Default branch:** {default}")
    lines.append(f"- **Branches sampled:** {stats.get('branches_sampled', len(branches))}")
    lines.append(f"- **Protected branches in sample:** {protected_count}")
    lines.append("")

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
