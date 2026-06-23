"""
Deterministic report sections — guaranteed detail for issues, PRs, and branches.
"""
from __future__ import annotations

import json
import re
import tomllib
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html import escape
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


TECH_EVIDENCE = {
    "pyproject.toml": ("Python", "Python packaging, dependencies, and tool configuration"),
    "requirements.txt": ("Python", "Python dependency list"),
    "setup.py": ("Python", "Python package build configuration"),
    "package.json": ("JavaScript/TypeScript", "Node.js scripts and dependencies"),
    "tsconfig.json": ("TypeScript", "TypeScript compiler configuration"),
    "go.mod": ("Go", "Go module and dependency definition"),
    "cargo.toml": ("Rust", "Rust crate metadata and dependencies"),
    "gemfile": ("Ruby", "Ruby dependencies"),
    "pom.xml": ("Java", "Maven build and dependency configuration"),
    "build.gradle": ("Java/Kotlin", "Gradle build configuration"),
    "dockerfile": ("Docker", "Container build instructions"),
    "docker-compose.yml": ("Docker Compose", "Local multi-service environment"),
    "compose.yml": ("Docker Compose", "Local multi-service environment"),
}

CONFIG_PURPOSES = {
    "gemini-extension.json": "Gemini extension metadata/configuration; it is not itself a programming language.",
    "greptile.json": "Greptile repository analysis configuration; it is not part of the runtime tech stack.",
    "uv.lock": "Exact locked Python dependency versions managed by uv.",
    ".gitattributes": "Git behavior such as line endings and diff handling.",
    ".gitignore": "Files intentionally excluded from version control.",
}

KNOWN_DEPENDENCIES = {
    "django": "Django web framework",
    "fastapi": "FastAPI web framework",
    "flask": "Flask web framework",
    "crewai": "CrewAI agent orchestration",
    "langchain": "LangChain LLM tooling",
    "pydantic": "Pydantic data validation",
    "pytest": "pytest test framework",
    "playwright": "Playwright browser automation",
    "requests": "Requests HTTP client",
    "react": "React UI library",
    "next": "Next.js web framework",
    "vue": "Vue UI framework",
    "express": "Express server framework",
    "typescript": "TypeScript language tooling",
}


def _file_map(snapshot: dict[str, Any]) -> dict[str, dict]:
    return {item.get("name", "").lower(): item for item in snapshot.get("files", [])}


def _detected_technologies(snapshot: dict[str, Any]) -> list[tuple[str, str]]:
    files = _file_map(snapshot)
    detected: list[tuple[str, str]] = []
    primary = snapshot.get("meta", {}).get("language")
    if primary:
        detected.append((primary, "primary language reported by GitHub"))
    for filename, (technology, reason) in TECH_EVIDENCE.items():
        if filename in files and technology.lower() not in {item[0].lower() for item in detected}:
            detected.append((technology, f"{reason}; evidence: `{files[filename].get('name')}`"))
    dependencies: set[str] = set()
    pyproject = files.get("pyproject.toml", {}).get("content_preview", "")
    if pyproject:
        try:
            data = tomllib.loads(pyproject)
            project = data.get("project", {})
            for requirement in project.get("dependencies", []):
                dependencies.add(re.split(r"[<>=!~\[; ]", requirement, maxsplit=1)[0].lower())
            poetry = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
            dependencies.update(name.lower() for name in poetry if name.lower() != "python")
        except (tomllib.TOMLDecodeError, TypeError):
            pass
    package_json = files.get("package.json", {}).get("content_preview", "")
    if package_json:
        try:
            data = json.loads(package_json)
            dependencies.update(name.lower() for name in data.get("dependencies", {}))
            dependencies.update(name.lower() for name in data.get("devDependencies", {}))
        except (json.JSONDecodeError, TypeError):
            pass
    requirements = files.get("requirements.txt", {}).get("content_preview", "")
    for line in requirements.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            dependencies.add(re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0].lower())
    manifest_text = f"{pyproject}\n{package_json}\n{requirements}".lower()
    for dependency, description in KNOWN_DEPENDENCIES.items():
        if dependency in dependencies or re.search(rf"[\"']{re.escape(dependency)}(?:[\"'\s<>=!~\[]|$)", manifest_text):
            if dependency.lower() not in {item[0].lower() for item in detected}:
                detected.append((dependency, f"{description}; verified in a dependency manifest"))
    return detected


def _purpose_for_item(item: dict) -> str:
    name = item.get("name", "")
    lower = name.lower()
    children = item.get("children") or []
    child_hint = f" Visible entries include {', '.join(f'`{child}`' for child in children[:5])}." if children else ""
    if lower == "readme.md":
        return "Primary project introduction, setup instructions, and usage guide. Start here before reading code."
    if lower in TECH_EVIDENCE:
        return TECH_EVIDENCE[lower][1] + "."
    if lower in CONFIG_PURPOSES:
        return CONFIG_PURPOSES[lower]
    if lower in {"src", "app", "lib", "core", "backend", "frontend", "api", "packages"}:
        return f"Likely implementation code based on the conventional directory name.{child_hint}"
    if lower in {"tests", "test"}:
        return f"Automated tests; useful for learning expected behavior and safe examples of how components are called.{child_hint}"
    if lower == "docs":
        return f"Project documentation beyond the README; use it after the setup guide for deeper concepts.{child_hint}"
    if lower == ".github":
        return f"GitHub automation, issue templates, or contribution workflows.{child_hint}"
    if lower in {"agents.md", "claude.md", "concepts.md", "architecture.md", "configuration.md", "contributing.md"}:
        return "Human-readable project guidance; read this early because its filename signals architecture, setup, or contributor rules."
    if lower in {"skills", ".agents", ".claude-plugin"}:
        return f"Project-specific AI/skill integration area. Its exact contents, not the folder name alone, should determine behavior.{child_hint}"
    if lower in {"fixtures", "examples", "samples"}:
        return f"Example or test data that can show expected inputs and outputs.{child_hint}"
    return "Supporting root item. RepoFlow has insufficient content evidence to claim a more specific purpose."


def build_structure_section(snapshot: dict[str, Any], ai_overview: str = "") -> str:
    meta = snapshot.get("meta", {})
    files = snapshot.get("files", [])
    file_names = {item.get("name", "").lower() for item in files}
    technologies = _detected_technologies(snapshot)
    overview = (
        f"**{meta.get('full_name') or snapshot.get('repo')}** is described by its maintainers as: "
        f"{meta.get('description') or 'No GitHub description was provided.'} "
        f"The default branch is `{meta.get('default_branch') or 'unknown'}`."
    )
    clean_ai = ai_overview.strip()
    if re.search(r"[\u3400-\u9fff]", clean_ai) or any(term in clean_ai.lower() for term in (" likely ", " probably ", " may be ")):
        clean_ai = ""

    lines = ['<h2 class="report-heading report-heading-green">Repository Structure Analysis</h2>', "", "### What This Project Is", "", overview]
    if clean_ai:
        lines.extend(["", clean_ai])

    lines.extend(["", "### Verified Tech Stack", ""])
    if technologies:
        lines.extend(f"- **{technology}:** {reason}." for technology, reason in technologies)
    else:
        lines.append("- **Not confidently detected:** inspect dependency manifests before assuming a framework or language.")

    config_items = [item for item in files if item.get("name", "").lower() in CONFIG_PURPOSES]
    if config_items:
        lines.extend(["", "### Configuration Files (Not Technologies)", ""])
        for item in config_items:
            lines.append(f"- **`{item['name']}`:** {_purpose_for_item(item)}")

    priority_names = [
        "readme.md", "contributing.md", "architecture.md", "concepts.md", "configuration.md",
        "pyproject.toml", "package.json", "go.mod", "cargo.toml", "src", "app", "lib",
        "core", "skills", "tests", "docs", ".github",
    ]
    selected = []
    by_name = _file_map(snapshot)
    for name in priority_names:
        if name in by_name and by_name[name] not in selected:
            selected.append(by_name[name])
    selected = selected[:12]
    lines.extend(["", "### Key Files and Folders: Why a Student Should Care", ""])
    for item in selected:
        lines.append(f"- **`{item['name']}` ({item.get('type', 'item')}):** {_purpose_for_item(item)}")
    if not selected:
        lines.append("- No high-confidence onboarding files were detected at the repository root.")

    reading_order = []
    for name in ("readme.md", "concepts.md", "architecture.md", "configuration.md", "contributing.md"):
        if name in by_name:
            reading_order.append(by_name[name]["name"])
    implementation = next((by_name[name]["name"] for name in ("src", "app", "lib", "core", "skills") if name in by_name), None)
    tests = next((by_name[name]["name"] for name in ("tests", "test") if name in by_name), None)
    if implementation:
        reading_order.append(implementation)
    if tests:
        reading_order.append(tests)
    lines.extend(["", "### Suggested Reading Order", ""])
    if reading_order:
        for index, name in enumerate(reading_order[:6], start=1):
            lines.append(f"{index}. **`{name}`** - {_purpose_for_item(by_name[name.lower()])}")
    else:
        lines.append("1. Start with the README, then locate the main source and test directories manually.")

    lines.extend(["", "### Before You Contribute", ""])
    if technologies:
        lines.append("- Learn the basics of: " + ", ".join(technology for technology, _ in technologies[:5]) + ".")
    if "tests" in file_names or "test" in file_names:
        lines.append("- Read and run the test suite before changing implementation code.")
    if "contributing.md" in file_names:
        lines.append("- Follow `CONTRIBUTING.md` for setup, style, and pull-request rules.")
    else:
        lines.append("- No root `CONTRIBUTING.md` was detected; check `.github` or the README for contributor rules.")

    lines.extend([
        "", "### Repository Stats", "",
        f"- **Stars:** {meta.get('stars') or 0}",
        f"- **Forks:** {meta.get('forks') or 0}",
        f"- **Default branch:** {meta.get('default_branch') or 'Data unavailable'}",
        f"- **Primary language:** {meta.get('language') or 'Not specified'}",
        f"- **License:** {meta.get('license') or 'Not specified'}",
        f"- **Last updated:** {meta.get('updated_at') or 'Data unavailable'}",
    ])
    return "\n".join(lines)


def _parse_github_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _stale_issue_count(issues: list[dict], days: int = 90) -> int:
    now = datetime.now(timezone.utc)
    stale = 0
    for issue in issues:
        last_activity = _parse_github_date(issue.get("updated_at") or issue.get("created_at"))
        if last_activity and (now - last_activity).days >= days:
            stale += 1
    return stale


def _issue_file_hints(issue: dict) -> list[str]:
    text = f"{issue.get('title', '')}\n{issue.get('body', '')}"
    matches = re.findall(
        r"(?<![\w.-])([\w./-]+\.(?:py|js|jsx|ts|tsx|go|rs|java|md|toml|json|ya?ml|sh))\b",
        text,
        flags=re.IGNORECASE,
    )
    return list(dict.fromkeys(matches))[:3]


def _issue_candidate(issue: dict) -> dict:
    labels = " ".join(issue.get("labels", [])).lower()
    title = (issue.get("title") or "").lower()
    body = (issue.get("body") or "").lower()
    score = 0
    reasons = []
    if "good first issue" in labels or "good-first-issue" in labels:
        score += 10
        reasons.append("maintainers labeled it as a good first issue")
    if "help wanted" in labels:
        score += 7
        reasons.append("maintainers explicitly requested help")
    if any(term in labels or term in title for term in ("documentation", "docs", "typo", "readme")):
        score += 5
        reasons.append("documentation-focused work is usually easier to review")
    if any(term in labels or term in title for term in ("test", "config", "warning", "message")):
        score += 3
        reasons.append("the title suggests a bounded test or configuration change")
    if "bug" in labels:
        score += 2
    if not issue.get("assignees"):
        score += 2
        reasons.append("no assignee is currently listed")
    if issue.get("comments", 0) <= 3:
        score += 1
    if any(term in title for term in ("security", "architecture", "migration", "rewrite", "crash", "race condition")):
        score -= 4
        reasons.append("the title suggests higher-risk behavior")
    if any(term in title for term in ("invitation", "showcase", "wallpaper", "fake engagement", "subscribe")):
        score -= 8
    file_hints = _issue_file_hints(issue)
    if file_hints:
        score += 3
        reasons.append("the issue points to concrete files: " + ", ".join(f"`{path}`" for path in file_hints))
    if len(body) >= 200:
        score += 2
        reasons.append("the issue contains enough description to investigate")

    difficulty = "Beginner" if score >= 8 else "Intermediate" if score >= 3 else "Advanced/unclear"
    if any(term in labels or term in title for term in ("documentation", "docs", "typo", "readme")):
        target = f"`{file_hints[0]}`" if file_hints else "the referenced documentation"
        first_step = f"Open {target}, verify the expected wording from the issue, and prepare the smallest documentation-only edit."
    elif file_hints:
        first_step = f"Open `{file_hints[0]}`, reproduce the reported behavior, then find or add its nearest test."
    else:
        first_step = "Read the full issue discussion, ask the maintainer to confirm scope, and locate the affected code before claiming it."
    return {
        "issue": issue,
        "score": score,
        "difficulty": difficulty,
        "reasons": reasons[:3] or ["limited evidence is available; confirm scope with a maintainer"],
        "first_step": first_step,
    }


def _beginner_issue_candidates(issues: list[dict], limit: int = 3) -> list[dict]:
    ranked = sorted((_issue_candidate(issue) for issue in issues), key=lambda item: item["score"], reverse=True)
    return [candidate for candidate in ranked if candidate["score"] >= 1][:limit]


def build_executive_summary(snapshot: dict[str, Any], health: dict[str, Any]) -> str:
    issues = snapshot.get("issues", [])
    prs = snapshot.get("pull_requests", [])
    branches = snapshot.get("branches", [])
    stats = snapshot.get("stats", {})
    open_issues_total = stats.get("open_issues_total", len(issues))
    open_prs_total = stats.get("open_prs_total", len(prs))
    stale_count = _stale_issue_count(issues)
    protected_count = sum(1 for branch in branches if branch.get("protected"))
    candidates = _beginner_issue_candidates(issues)
    health_score = health.get("score", 0)
    health_label = health.get("label", "Unknown")
    health_metrics = health.get("metrics", {})
    health_tone = "assessment-health-good" if health_score > 75 else "assessment-health-warn" if health_score >= 50 else "assessment-health-bad"

    findings = [
        f"<div class=\"assessment-stat\"><strong>{stale_count}</strong><span>stale sampled issues over 90 days</span></div>",
        f"<div class=\"assessment-stat\"><strong>{len(branches)}</strong><span>branches inspected</span></div>",
        f"<div class=\"assessment-stat\"><strong>{health_metrics.get('issues_per_star', 0):.3f}</strong><span>open issues per star</span></div>",
    ]
    risks = []
    if protected_count:
        risks.append(f"<div class=\"assessment-line\">✓ {protected_count} protected branch(es) detected</div>")
    issue_load_status = health_metrics.get("issue_load_status", "")
    if issue_load_status in {"elevated relative to community size", "high relative to community size"}:
        risks.append(
            f"<div class=\"assessment-line\">⚠ {open_issues_total} open issues are {escape(issue_load_status)}</div>"
        )
    stale_pr_count = health_metrics.get("stale_pr_count", 0)
    sampled_prs = health_metrics.get("sampled_prs_with_dates", 0)
    if stale_pr_count:
        risks.append(
            f"<div class=\"assessment-line\">⚠ {stale_pr_count} of {sampled_prs} sampled PRs have been open over 180 days</div>"
        )
    if not risks:
        risks.append("<div class=\"assessment-line\">✓ No high-confidence maintenance risks detected</div>")

    recommendations = []
    if candidates:
        candidate = candidates[0]
        issue = candidate["issue"]
        recommendations.append(
            f"<a class=\"recommendation-pill\" href=\"{escape(str(issue.get('url', '#')))}\">"
            f"Start with #{issue.get('number')}: {escape(str(issue.get('title', 'Issue')))}</a>"
        )
    elif open_issues_total == 0:
        recommendations.append("<span class=\"recommendation-pill\">Check for an external issue tracker</span>")
    else:
        recommendations.append("<span class=\"recommendation-pill\">Ask maintainers for a scoped beginner task</span>")
    if open_prs_total == 0:
        recommendations.append("<span class=\"recommendation-pill\">Confirm whether contributions are currently active</span>")
    if not protected_count:
        default = snapshot.get("meta", {}).get("default_branch", "main")
        recommendations.append(f"<span class=\"recommendation-pill\">Optional: protect {escape(str(default))} from direct pushes</span>")
    if stale_count:
        recommendations.append("<span class=\"recommendation-pill\">Triage stale issues before adding new work</span>")

    return "\n".join([
        '<h2 class="assessment-heading report-heading report-heading-yellow">Repository Assessment</h2>',
        '<div class="assessment-grid">',
        '<section class="assessment-card assessment-critical">',
        '<div class="assessment-card-title">⚠ Critical Findings</div>',
        f'<div class="assessment-health {health_tone}"><strong>{health_score}/100</strong><span>{escape(str(health_label))}</span></div>',
        *findings,
        '</section>',
        '<section class="assessment-card assessment-risks">',
        '<div class="assessment-card-title">🔥 Risks</div>',
        *risks,
        '</section>',
        '<section class="assessment-card assessment-recommendations">',
        '<div class="assessment-card-title">💡 Recommendations</div>',
        '<div class="recommendation-list">',
        *recommendations,
        '</div>',
        '</section>',
        '</div>',
    ])


def build_branch_snapshot(snapshot: dict[str, Any]) -> str:
    default = snapshot.get("meta", {}).get("default_branch", "main")
    counts: Counter = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    for branch in snapshot.get("branches", []):
        name = branch.get("name", "")
        if not name:
            continue
        category = "Default branch" if name == default else _branch_category(name)[0]
        counts[category] += 1
        if len(examples[category]) < 3:
            examples[category].append(name)
    cards = []
    for category, count in counts.most_common():
        names = ", ".join(escape(name) for name in examples[category])
        cards.append(
            '<div class="branch-snapshot-card">'
            f'<strong>{count}</strong><span>{escape(category)}</span>'
            f'<small>{names}</small></div>'
        )
    if not cards:
        cards.append('<div class="branch-snapshot-card"><strong>0</strong><span>Branches available</span></div>')
    return "\n".join([
        '<section class="branch-snapshot-section">',
        '<h3>Branch Snapshot</h3>',
        '<div class="branch-snapshot-grid">',
        *cards,
        '</div>',
        '</section>',
    ])


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
    if lower.startswith(("ci/", "ci-", "ci_", "test/", "tests/", "e2e/", "build/", "workflow/", "github-actions/")) or "/ci/" in lower or "e2e" in lower:
        return "CI/CD work", f"CI/CD work: {_clean_branch_token(name)}."
    if lower.startswith(("fix/", "fix-", "fix_", "bug/", "bug-", "bug_", "bugfix/", "bugfix-", "bugfix_", "hotfix/", "hotfix-", "hotfix_")) or "fix" in lower:
        topic = re.sub(r"^(bugfix|hotfix|fix|bug)[/_-]?", "", name, flags=re.IGNORECASE)
        return "Bug fixes", f"Bug fix targeting {_clean_branch_token(topic) or 'a reported defect'}."
    if lower.startswith(("feature/", "feature-", "feature_", "feat/", "feat-", "feat_")):
        topic = re.sub(r"^(feature|feat)[/_-]?", "", name, flags=re.IGNORECASE)
        return "Feature branches", f"Feature work: {_clean_branch_token(topic) or 'new capability'} improvements, not yet merged."
    if lower in {"mcp", "model-context-protocol"} or lower.startswith(("mcp/", "mcp-")):
        return "Feature branches", "Likely MCP (Model Context Protocol) integration work in progress."
    if "query-set" in lower or "query_sets" in lower or "querysets" in lower:
        return "Feature branches", "Feature branch for query set functionality."
    if lower.startswith(("release/", "release-", "release_", "rel/", "rel-", "rel_", "v")):
        return "Release branches", f"Release or version preparation branch: {_clean_branch_token(name)}."
    if lower.startswith(("docs/", "docs-", "docs_", "doc/", "doc-", "doc_")):
        topic = re.sub(r"^(docs|doc)[/_-]?", "", name, flags=re.IGNORECASE)
        return "Documentation", f"Documentation update for {_clean_branch_token(topic) or 'project docs'}."
    return "Other branches", f"Work in progress around {_clean_branch_token(name)}."


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


def _branch_activity(branch: dict, open_prs: int) -> tuple[str, str]:
    commit_date = _parse_github_date(branch.get("last_commit_date"))
    if open_prs:
        noun = "PR" if open_prs == 1 else "PRs"
        return "Active", f"{open_prs} open {noun} use this as their source branch; inspect those PRs for current context"
    if commit_date:
        age_days = max(0, (datetime.now(timezone.utc) - commit_date).days)
        if age_days > 90:
            return "Likely abandoned", f"last commit was {age_days} days ago and no sampled open PR uses it; do not base your learning on it"
        if age_days > 30:
            return "Dormant", f"last commit was {age_days} days ago with no sampled open PR; verify with maintainers before using it"
        return "Recently updated", f"last commit was {age_days} days ago, but no sampled open PR currently uses it"
    return "Unknown activity", "commit recency was unavailable and no sampled open PR uses it; avoid making a strong conclusion"


def build_issues_section(snapshot: dict[str, Any]) -> str:
    issues = snapshot.get("issues", [])
    stats = snapshot.get("stats", {})
    total = stats.get("open_issues_total", len(issues))
    sampled = stats.get("issues_sampled", len(issues))
    lines = [
        '<h2 class="report-heading report-heading-green">Open Issues Report</h2>',
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

    candidates = _beginner_issue_candidates(issues)
    lines.extend(["### Beginner Contribution Shortlist", ""])
    if candidates:
        lines.append(
            "These are ranked from the sampled issues using labels, scope clues, assignee status, "
            "description quality, and concrete file references. Verify scope with maintainers before starting."
        )
        lines.append("")
        for candidate in candidates:
            issue = candidate["issue"]
            reasons = "; ".join(candidate["reasons"])
            lines.extend([
                f"#### #{issue.get('number')} - {issue.get('title')}",
                "",
                f"- **Estimated difficulty:** {candidate['difficulty']}",
                f"- **Why it may suit a student:** {reasons}.",
                f"- **Suggested first step:** {candidate['first_step']}",
                f"- **Issue:** [Open on GitHub]({issue.get('url', '#')})",
                "",
            ])
    else:
        lines.extend([
            "No issue in the sample has enough evidence to recommend confidently to a beginner.",
            "Ask maintainers for a small, well-scoped task instead of selecting an issue from its title alone.",
            "",
        ])

    lines.extend(["### Sampled Issue Details", ""])

    grouped: dict[str, list[dict]] = defaultdict(list)
    for issue in issues:
        grouped[_label_group(issue.get("labels", []))].append(issue)

    for group_name in sorted(grouped.keys()):
        group = grouped[group_name]
        lines.append(f"### {group_name} ({len(group)} sampled)")
        lines.append("")
        for issue in group[:5]:
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
        if len(group) > 5:
            lines.append(f"- _{len(group) - 5} more sampled issues in this group are omitted; use GitHub for the full list._")
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
        '<h2 class="report-heading report-heading-green">Pull Request Analysis Report</h2>',
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

    themes: Counter = Counter()
    for pr in prs:
        text = f"{pr.get('title', '')} {pr.get('head', '')}".lower()
        if any(token in text for token in ("fix", "bug", "hotfix")):
            themes["Bug fixes"] += 1
        elif any(token in text for token in ("feat", "feature", "add")):
            themes["Features"] += 1
        elif "doc" in text:
            themes["Documentation"] += 1
        elif any(token in text for token in ("ci", "test", "workflow")):
            themes["Tests/CI"] += 1
        else:
            themes["Other"] += 1
    lines.append(f"**Work themes in the sample:** {_top_counts(themes)}")
    lines.append("")

    for pr in prs[:12]:
        author = pr.get("author") or "unknown"
        url = pr.get("url", "#")
        draft = " (draft)" if pr.get("draft") else ""
        lines.append(
            f"- **PR #{pr['number']}:** \"{pr['title']}\"{draft} - "
            f"submitted by @{author}, **{pr.get('head')}** -> **{pr.get('base')}** - "
            f"[View PR]({url})"
        )
    if len(prs) > 12:
        lines.append(f"- _{len(prs) - 12} additional sampled PRs are omitted; use GitHub for the full queue._")

    return "\n".join(lines)


def build_branches_section(snapshot: dict[str, Any]) -> str:
    branches = snapshot.get("branches", [])
    default = snapshot.get("meta", {}).get("default_branch", "main")
    stats = snapshot.get("stats", {})
    protected_count = sum(1 for branch in branches if branch.get("protected"))
    prs = snapshot.get("pull_requests", [])
    pr_targets = Counter(pr.get("base") or "unknown" for pr in prs)
    pr_sources = Counter(pr.get("head") or "unknown" for pr in prs)
    lines = ['<h2 class="report-heading report-heading-green">Branches</h2>', ""]

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
                "branch": branch,
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
            open_prs = pr_sources.get(item["name"], 0)
            activity, guidance = _branch_activity(item.get("branch", {}), open_prs)
            commit_date = item.get("branch", {}).get("last_commit_date")
            date_text = commit_date[:10] if commit_date else "date unavailable"
            lines.append(
                f"- **{item['name']}** - {item['description']} "
                f"**{activity}** ({date_text}): {guidance}."
            )
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
