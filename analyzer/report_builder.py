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


TREE_COMMENT_OVERRIDES = {
    "api": "FastAPI Backend",
    "agents": "AI agent implementations",
    "auth": "Authentication and user management",
    "routes": "API endpoints",
    "loaders": "Data loaders and connectors",
    "app": "Frontend or application source",
    "src": "Main source code",
    "components": "UI components",
    "contexts": "State management",
    "services": "API client implementations",
    "lib": "Reusable library code",
    "core": "Core application logic",
    "backend": "Backend implementation",
    "frontend": "Frontend implementation",
    "tests": "Unit and integration tests",
    "test": "Automated tests",
    "docs": "Documentation",
    ".github": "GitHub workflows and community files",
    "readme.md": "Project overview and setup instructions",
    "contributing.md": "Contribution rules for new developers",
    "security.md": "Security vulnerability reporting policy",
    "package.json": "Node.js scripts and dependencies",
    "pyproject.toml": "Python project metadata and dependencies",
    "requirements.txt": "Python dependency list",
    "go.mod": "Go module definition",
    "cargo.toml": "Rust crate metadata",
    "dockerfile": "Container build instructions",
    "app_factory.py": "Application initialization",
    "config.py": "Configuration",
    "index.py": "Server entry point",
    "main.py": "Application entry point",
    "client.py": "Client implementation",
    "connection.py": "Connection management",
    "models.py": "Data models",
    "app.tsx": "Main frontend entry point",
}


def _tree_comment(name: str, item_type: str = "") -> str:
    lower = name.lower()
    if lower in TREE_COMMENT_OVERRIDES:
        return TREE_COMMENT_OVERRIDES[lower]
    return ""


def _format_tree_line(prefix: str, connector: str, name: str, comment: str) -> str:
    label = f"{prefix}{connector} {name}"
    if not comment:
        return label
    return f"{label:<36} # {comment}"


def _repository_tree(snapshot: dict[str, Any]) -> str:
    meta = snapshot.get("meta", {})
    repo_name = meta.get("full_name") or f"{snapshot.get('owner', '')}/{snapshot.get('repo', '')}".strip("/")
    files = sorted(
        snapshot.get("files", []),
        key=lambda item: (item.get("type") != "dir", item.get("name", "").lower()),
    )
    selected = files[:18]
    lines = [f"{repo_name}/"]
    for index, item in enumerate(selected):
        name = item.get("name", "")
        if not name:
            continue
        is_last = index == len(selected) - 1
        connector = "└──" if is_last else "├──"
        display_name = f"{name}/" if item.get("type") == "dir" else name
        lines.append(_format_tree_line("", connector, display_name, _tree_comment(name, item.get("type", ""))))
        children = item.get("children") or []
        if item.get("type") == "dir" and children:
            child_prefix = "    " if is_last else "│   "
            for child_index, child in enumerate(children[:5]):
                child_is_last = child_index == min(len(children), 5) - 1
                child_connector = "└──" if child_is_last else "├──"
                child_display = f"{child}/" if "." not in child else child
                lines.append(_format_tree_line(child_prefix, child_connector, child_display, _tree_comment(child)))
            if len(children) > 5:
                lines.append(f"{child_prefix}└── ... {len(children) - 5} more items")
    if not selected:
        lines.append("└── No root files were returned by the GitHub API")
    return "\n".join(lines)


def _has_root_file(snapshot: dict[str, Any], *names: str) -> bool:
    available = {item.get("name", "").lower() for item in snapshot.get("files", [])}
    return any(name.lower() in available for name in names)


def _has_ci_config(snapshot: dict[str, Any]) -> bool:
    files = _file_map(snapshot)
    github = files.get(".github") or {}
    children = {child.lower() for child in github.get("children") or []}
    root_names = {item.get("name", "").lower() for item in snapshot.get("files", [])}
    return (
        "workflows" in children
        or ".github/workflows" in root_names
        or any(name in root_names for name in ("azure-pipelines.yml", ".travis.yml", "circle.yml", "jenkinsfile"))
    )


def _days_since(value: str | None) -> str:
    parsed = _parse_github_date(value)
    if not parsed:
        return "Data unavailable"
    days = max(0, (datetime.now(timezone.utc) - parsed).days)
    if days == 0:
        return "today"
    if days == 1:
        return "1 day ago"
    return f"{days} days ago"


def _stat_card(title: str, value: str, tone: str = "neutral") -> str:
    return (
        f'<div class="repo-stat-card repo-stat-{tone}">'
        f'<span>{escape(title)}</span>'
        f'<strong>{escape(value)}</strong>'
        '</div>'
    )


def _repository_statistics(snapshot: dict[str, Any]) -> str:
    meta = snapshot.get("meta", {})
    stats = snapshot.get("stats", {})
    branches = snapshot.get("branches", [])
    protected_count = sum(1 for branch in branches if branch.get("protected"))
    branch_count = stats.get("branches_sampled", len(branches))
    cards = [
        _stat_card(
            "Repository purpose",
            "Documented" if meta.get("description") else "No description",
            "good" if meta.get("description") else "warn",
        ),
        _stat_card(
            "Root README",
            "Available" if _has_root_file(snapshot, "README.md") else "Missing",
            "good" if _has_root_file(snapshot, "README.md") else "warn",
        ),
        _stat_card(
            "License",
            f"Detected: {meta.get('license')}" if meta.get("license") else "Not detected",
            "good" if meta.get("license") else "warn",
        ),
        _stat_card(
            "CONTRIBUTING.md",
            "Available" if _has_root_file(snapshot, "CONTRIBUTING.md") else "Not detected",
            "good" if _has_root_file(snapshot, "CONTRIBUTING.md") else "warn",
        ),
        _stat_card(
            "CI/CD",
            "Configuration detected" if _has_ci_config(snapshot) else "Not detected",
            "good" if _has_ci_config(snapshot) else "warn",
        ),
        _stat_card("Last code push", _days_since(meta.get("pushed_at") or meta.get("updated_at"))),
        _stat_card("Open issues", str(stats.get("open_issues_total", len(snapshot.get("issues", []))))),
        _stat_card("Open PRs", str(stats.get("open_prs_total", len(snapshot.get("pull_requests", []))))),
        _stat_card(
            "Branches",
            f"{branch_count} sampled; review cleanup" if branch_count >= 30 else f"{branch_count} sampled",
            "warn" if branch_count >= 30 else "neutral",
        ),
        _stat_card(
            "Protected branches",
            f"{protected_count} detected" if protected_count else "None detected",
            "good" if protected_count else "warn",
        ),
    ]
    return "\n".join([
        '<div class="repo-stat-grid">',
        *cards,
        '</div>',
    ])


def build_structure_section(snapshot: dict[str, Any], ai_overview: str = "") -> str:
    meta = snapshot.get("meta", {})
    files = snapshot.get("files", [])
    technologies = _detected_technologies(snapshot)
    repo_display = meta.get("full_name") or snapshot.get("repo") or "This repository"
    overview = (
        f"<strong>{escape(str(repo_display))}</strong> is described by its maintainers as: "
        f"{escape(str(meta.get('description') or 'No GitHub description was provided.'))} "
        f"The default branch is <code>{escape(str(meta.get('default_branch') or 'unknown'))}</code>."
    )
    clean_ai = ai_overview.strip()
    if re.search(r"[\u3400-\u9fff]", clean_ai) or any(term in clean_ai.lower() for term in (" likely ", " probably ", " may be ")):
        clean_ai = ""

    lines = [
        '<h2 class="report-heading report-heading-green">Repository Overview</h2>',
        "",
        "### What This Project Is",
        "",
        f'<div class="overview-card">{overview}</div>',
    ]
    if clean_ai:
        lines.extend(["", f'<div class="overview-card overview-card-muted">{escape(clean_ai)}</div>'])

    lines.extend([
        "",
        "### Structure",
        "",
        "```text",
        _repository_tree(snapshot),
        "```",
    ])

    lines.extend(["", "### Verified Tech Stack", ""])
    if technologies:
        lines.append('<div class="tech-stack-grid">')
        lines.extend(
            f'<div class="tech-pill"><strong>{escape(technology)}</strong><span>{escape(reason)}.</span></div>'
            for technology, reason in technologies
        )
        lines.append("</div>")
    else:
        lines.append("- **Not confidently detected:** inspect dependency manifests before assuming a framework or language.")

    lines.extend(["", "### Repository Statistics", "", _repository_statistics(snapshot)])

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


def build_recommendations_section(snapshot: dict[str, Any]) -> str:
    scorecard = snapshot.get("openssf_scorecard") or {}
    badge = snapshot.get("best_practices_badge") or {}
    insights = snapshot.get("security_insights") or {}
    vulns = (snapshot.get("osv_vulnerabilities") or {}).get("vulns") or []
    branches = snapshot.get("branches", [])
    issues = snapshot.get("issues", [])
    recommendations = []

    if vulns:
        recommendations.append("Review OSV vulnerability records first and confirm whether the repository is affected.")
    if not badge.get("found"):
        recommendations.append("Consider completing the OpenSSF Best Practices Badge to document security hygiene.")
    if not any((
        insights.get("has_security_insights"),
        insights.get("has_security_md"),
        insights.get("has_github_security_md"),
    )):
        recommendations.append("Add a SECURITY.md file to tell contributors how to report vulnerabilities.")

    low_checks = []
    for check in scorecard.get("checks") or []:
        try:
            score = float(check.get("score"))
        except (TypeError, ValueError):
            continue
        if score < 5:
            low_checks.append(check.get("name") or "Scorecard check")
    if low_checks:
        recommendations.append("Prioritize low OpenSSF Scorecard checks: " + ", ".join(low_checks[:4]) + ".")

    if len(branches) > 30:
        recommendations.append("Review branch sprawl and delete stale branches that have no active PR.")
    if _beginner_issue_candidates(issues):
        recommendations.append("Use the Good First Issues shortlist for a safer first contribution path.")
    elif not issues:
        recommendations.append("No open GitHub issues were found; check whether the project uses an external tracker.")

    if not recommendations:
        recommendations.append("Security metadata looks reasonably complete; keep monitoring Scorecard, OSV, and branch activity over time.")

    lines = ['<h2 class="report-heading report-heading-yellow">💡 Recommendations</h2>', ""]
    lines.extend(f"- {recommendation}" for recommendation in recommendations)
    return "\n".join(lines)


def _scorecard_indicator(score: Any) -> str:
    try:
        numeric = float(score)
    except (TypeError, ValueError):
        return "Not scored"
    if numeric >= 7:
        return "Pass"
    if numeric > 0:
        return "Review"
    return "Fail"


def _status_tone(label: str) -> str:
    lowered = label.lower()
    if lowered in {"pass", "present", "available", "gold"}:
        return "good"
    if lowered in {"review", "silver", "passing"}:
        return "warn"
    if lowered in {"fail", "missing", "unavailable"}:
        return "bad"
    return "neutral"


def _scorecard_check_by_name(snapshot: dict[str, Any], target: str) -> dict[str, Any] | None:
    target_lower = target.lower()
    for check in (snapshot.get("openssf_scorecard") or {}).get("checks") or []:
        name = str(check.get("name") or "").lower()
        if name == target_lower:
            return check
    return None


def _openSSF_intro(title: str, body: str) -> str:
    return (
        f'<div class="security-intro">'
        f'<strong>{escape(title)}</strong>'
        f'<p>{escape(body)}</p>'
        '</div>'
    )


def _plain_scorecard_reason(name: str, score: Any, reason: str) -> str:
    name_lower = name.lower()
    reason_lower = reason.lower()
    try:
        numeric_score = float(score)
    except (TypeError, ValueError):
        numeric_score = None

    if (
        "branch" in name_lower
        and "protection" in name_lower
        and "classic branch protection" in reason_lower
    ):
        return (
            "Branch protection rules exist but are restricted. This repository uses classic "
            "branch protection, which requires admin access to read. Treat this as a sign of "
            "stricter security, not a failure."
        )
    if "internal error" in reason_lower and "github token" in reason_lower and "branch protection" in reason_lower:
        return (
            "Branch protection rules exist but are restricted. This repository uses classic "
            "branch protection, which requires admin access to read. Treat this as a sign of "
            "stricter security, not a failure."
        )
    if "depend" in name_lower and "pinn" in name_lower and numeric_score == 0:
        return (
            "Dependencies in CI/CD workflows are not pinned to exact commit hashes. "
            "This is a supply-chain risk even in large projects."
        )
    if "release" in name_lower and ("no releases" in reason_lower or "not found" in reason_lower or numeric_score == 0):
        return (
            "No signed GitHub Releases detected. This project may publish through npm, "
            "PyPI, or a custom pipeline instead."
        )
    if any(raw in reason_lower for raw in ("internal error", "unavailable", "rpc error", "token", "exception")):
        return "Scorecard could not read this signal fully. Review the project settings manually if this check matters."
    return reason or "No reason provided."


def _best_practices_badge_section(snapshot: dict[str, Any]) -> str:
    badge = snapshot.get("best_practices_badge") or {}
    if badge.get("found") and badge.get("level"):
        level = str(badge["level"]).strip().lower()
        label = {"passing": "Passing", "silver": "Silver", "gold": "Gold"}.get(level, level.title())
        return "\n".join([
            "### OpenSSF Best Practices Badge",
            "",
            _openSSF_intro(
                "What this badge means",
                "The OpenSSF Best Practices Badge is a public signal that a project follows a set of community security and maintenance practices. "
                "It matters because it tells contributors and users that the project has taken concrete steps toward safer, more predictable releases. "
                f"A {label.lower()} badge means the project reached a documented level of practice maturity, not just a one-time scan result."
            ),
            "",
            '<div class="badge-showcase">',
            f'<div class="badge-medal badge-{escape(level)}">{escape(label)}</div>',
            '<div>',
            '<strong>OpenSSF Best Practices badge detected</strong>',
            '<p>This project has completed OpenSSF Best Practices criteria for open-source quality and security hygiene.</p>',
            '</div>',
            '</div>',
        ])
    fallback = _scorecard_check_by_name(snapshot, "CII-Best-Practices")
    if fallback:
        score = fallback.get("score")
        reason = _plain_scorecard_reason(
            str(fallback.get("name") or "CII-Best-Practices"),
            score,
            str(fallback.get("reason") or ""),
        )
        try:
            numeric_score = float(score)
        except (TypeError, ValueError):
            numeric_score = 0
        if numeric_score >= 5:
            return "\n".join([
                "### OpenSSF Best Practices Badge",
                "",
                _openSSF_intro(
                    "What this badge means",
                    "The OpenSSF Best Practices Badge is a public signal that a project follows a set of community security and maintenance practices. "
                    "It matters because it helps contributors quickly see whether a repository is being run with security and release discipline in mind. "
                    "This project did not return a badge directly, but Scorecard shows the badge-related check as passing, which is a strong proxy signal."
                ),
                "",
                '<div class="badge-showcase">',
                '<div class="badge-medal badge-passing">Passing</div>',
                '<div>',
                '<strong>Best Practices signal found in Scorecard</strong>',
                '<p>The direct badge API did not return a project, but Scorecard reports the CII-Best-Practices check as passing.</p>',
                '</div>',
                '</div>',
            ])
        return "\n".join([
            "### OpenSSF Best Practices Badge",
            "",
            _openSSF_intro(
                "What this badge means",
                "The OpenSSF Best Practices Badge is a public signal that a project follows a set of community security and maintenance practices. "
                "It matters because it gives maintainers a simple way to show that the project is taking release hygiene seriously. "
                "The badge was not found here, so the project may still be healthy, but it has not published that public proof yet."
            ),
            "",
            '<div class="security-card security-card-warn">',
            '<span class="security-status security-status-warn">Review</span>',
            '<strong>Best Practices badge not confirmed</strong>',
            f'<p>{escape(reason)}</p>',
            '<p><a href="https://www.bestpractices.dev" target="_blank" rel="noreferrer">Apply or learn more at bestpractices.dev</a></p>',
            '</div>',
        ])
    return "\n".join([
        "### OpenSSF Best Practices Badge",
        "",
        _openSSF_intro(
            "What this badge means",
            "The OpenSSF Best Practices Badge is a public signal that a project follows a set of community security and maintenance practices. "
            "It matters because contributors can use it to judge whether the project is paying attention to release discipline and operational hygiene. "
            "No badge was detected here, so the project may not have published that proof yet."
        ),
        "",
        '<div class="security-card security-card-warn">',
        '<span class="security-status security-status-warn">Not detected</span>',
        '<strong>No OpenSSF Best Practices badge detected</strong>',
        '<p>The project may still be healthy, but it has not published a Best Practices badge in the OpenSSF database.</p>',
        '<p><a href="https://www.bestpractices.dev" target="_blank" rel="noreferrer">See the badge program and apply at bestpractices.dev</a></p>',
        '</div>',
    ])


def build_security_insights_section(snapshot: dict[str, Any]) -> str:
    insights = snapshot.get("security_insights") or {}
    has_security_insights = bool(insights.get("has_security_insights"))
    has_security_md = bool(insights.get("has_security_md"))
    has_github_security_md = bool(insights.get("has_github_security_md"))

    def insight_card(title: str, value: bool, detail: str) -> str:
        label = "Present" if value else "Missing"
        tone = "good" if value else "warn"
        return (
            f'<div class="security-card security-card-{tone}">'
            f'<span class="security-status security-status-{tone}">{label}</span>'
            f'<strong>{escape(title)}</strong>'
            f'<p>{escape(detail)}</p>'
            '</div>'
        )

    lines = [
        "### Security Insights",
        "",
        _openSSF_intro(
            "What this checks",
            "Security Insights looks for files that tell contributors how this project handles vulnerability reporting and security policies. "
            "That matters because open source users often need a clear path for reporting issues without opening a public bug report. "
            "If the files are present, it is easier for maintainers and security researchers to coordinate responsibly."
        ),
        "",
        '<div class="security-card-grid">',
        insight_card("SECURITY-INSIGHTS.yml/yaml", has_security_insights, "Machine-readable OpenSSF security metadata for tools and reviewers."),
        insight_card("Root SECURITY.md", has_security_md, "Contributor-facing instructions for reporting vulnerabilities from the repository root."),
        insight_card(".github/SECURITY.md", has_github_security_md, "GitHub-recognized security policy location for vulnerability reporting."),
        '</div>',
    ]
    if not any((has_security_insights, has_security_md, has_github_security_md)):
        lines.extend([
            "",
            '<div class="recommendation-banner"><strong>Recommendation:</strong> Add a SECURITY.md file to tell contributors how to report vulnerabilities.</div>',
        ])
    return "\n".join(lines)


def build_security_section(snapshot: dict[str, Any], security_summary: str = "") -> str:
    scorecard = snapshot.get("openssf_scorecard") or {}
    badge_md = _best_practices_badge_section(snapshot)
    if not scorecard.get("available"):
        if scorecard.get("status_code") == 404:
            message = (
                "OpenSSF Scorecard scans a repository for common security and maintenance signals like branch protection, "
                "dependency pinning, and release practices. The scan matters because it gives a fast, standardized view of "
                "how the project handles supply-chain and maintenance hygiene. This repository may not be in the OpenSSF database yet, "
                "so the tool could not return a scorecard result."
            )
        else:
            message = (
                "OpenSSF Scorecard scans a repository for common security and maintenance signals like branch protection, "
                "dependency pinning, and release practices. The scan matters because it gives a fast, standardized view of "
                "how the project handles supply-chain and maintenance hygiene. The lookup failed this time, so the report cannot "
                "confirm the repository’s current Scorecard state."
            )
        return "\n".join([
            '<h2 class="report-heading report-heading-green">OpenSSF Security Scorecard</h2>',
            "",
            f'<div class="security-summary">{escape(security_summary)}</div>' if security_summary else "",
            "",
            _openSSF_intro("What Scorecard is", message),
            "",
            badge_md,
        ])

    overall = scorecard.get("score")
    date = scorecard.get("date")
    repo = scorecard.get("repo", {}).get("name") if isinstance(scorecard.get("repo"), dict) else None
    checks = scorecard.get("checks") or []
    lines = [
        '<h2 class="report-heading report-heading-green">OpenSSF Security Scorecard</h2>',
        "",
        f'<div class="security-summary">{escape(security_summary)}</div>' if security_summary else "",
        "",
        _openSSF_intro(
            "What Scorecard is",
            "OpenSSF Scorecard scans a repository for common security and maintenance signals like branch protection, dependency pinning, "
            "release discipline, and workflow hardening. It matters because those small operational choices shape supply-chain risk in real projects. "
            "The score below is a snapshot of how this repository behaves in practice, not a judgment on code quality."
        ),
        "",
        "### Overall Score",
        "",
        '<div class="scorecard-hero">',
        f'<div class="scorecard-score"><strong>{overall if overall is not None else "?"}/10</strong></div>',
        '<div>',
        '<strong>OpenSSF Scorecard</strong>',
        '<p>Automated security posture checks from the OpenSSF Scorecard service.</p>',
        '</div>',
        '</div>',
    ]
    if repo:
        lines.append(f"- **Scorecard repository:** {repo}")
    if date:
        lines.append(f"- **Scorecard date:** {date}")
    lines.extend(["", "### Individual Checks", "", '<div class="scorecard-check-grid">'])
    if not checks:
        lines.append('<div class="security-card security-card-neutral"><strong>No individual checks returned</strong><p>The Scorecard API returned an overall result without detailed checks.</p></div>')
        lines.append("</div>")
        lines.extend(["", badge_md])
        return "\n".join(lines)

    for check in checks:
        name = check.get("name") or "Unnamed check"
        score = check.get("score")
        reason = _plain_scorecard_reason(str(name), score, str(check.get("reason") or ""))
        indicator = _scorecard_indicator(score)
        tone = _status_tone(indicator)
        score_text = score if score is not None else "Data unavailable"
        lines.extend([
            f'<div class="scorecard-check scorecard-check-{tone}">',
            f'<span class="security-status security-status-{tone}">{indicator}</span>',
            f'<strong>{escape(str(name))}</strong>',
            f'<small>Score: {escape(str(score_text))}/10</small>',
            f'<p>{escape(str(reason))}</p>',
            '</div>',
        ])
    lines.extend(["</div>", "", badge_md])
    return "\n".join(lines).strip()


def _vulnerability_id(vuln: dict[str, Any]) -> str:
    aliases = vuln.get("aliases") or []
    cve = next((alias for alias in aliases if str(alias).startswith("CVE-")), None)
    return cve or vuln.get("id") or "Unknown vulnerability"


def _vulnerability_severity(vuln: dict[str, Any]) -> str:
    severities = vuln.get("severity") or []
    if severities:
        first = severities[0]
        severity_type = first.get("type") or "Severity"
        score = first.get("score") or "Data unavailable"
        return f"{severity_type}: {score}"
    database_specific = vuln.get("database_specific") or {}
    return database_specific.get("severity") or "Severity unavailable"


def build_vulnerabilities_section(snapshot: dict[str, Any]) -> str:
    osv_data = snapshot.get("osv_vulnerabilities") or {}
    vulns = osv_data.get("vulns") or []
    lines = [
        '<h2 class="report-heading report-heading-yellow">OSV Vulnerability Scan</h2>',
        "",
        _openSSF_intro(
            "What OSV is",
            "OSV is a vulnerability database that tracks known security issues affecting open source projects and packages. "
            "It matters because it gives maintainers and contributors a quick way to check whether a repository has public known vulnerabilities. "
            "A clean result means OSV did not return a known issue for this repository URL at the time of the scan."
        ),
        "",
    ]
    if not vulns:
        if not osv_data.get("available", True):
            lines.append(
                '<div class="security-card security-card-warn">'
                '<span class="security-status security-status-warn">Scan failed</span>'
                '<strong>OSV scan could not be completed — try again later.</strong>'
                '<p>The rest of the report is still generated from GitHub and OpenSSF data.</p>'
                '</div>'
            )
        else:
            lines.append(
                '<div class="security-card security-card-good">'
                '<span class="security-status security-status-good">Clear</span>'
                '<strong>No known vulnerabilities found in the OSV database — this repository has a clean vulnerability record.</strong>'
                '<p>OSV did not return known vulnerability records for this repository URL, which means no public vulnerability matches were found during the scan.</p>'
                '</div>'
            )
        return "\n".join(lines)

    lines.extend([
        '<div class="vuln-list">',
        f'<div class="security-card security-card-bad"><span class="security-status security-status-bad">Review</span><strong>{len(vulns)} known vulnerabilit{"y" if len(vulns) == 1 else "ies"} returned by OSV</strong><p>Confirm whether the repository is affected before treating these as exploitable findings.</p></div>',
    ])
    for vuln in vulns:
        vuln_id = _vulnerability_id(vuln)
        summary = vuln.get("summary") or vuln.get("details") or "No summary provided."
        summary = summary.strip().replace("\n", " ")
        if len(summary) > 240:
            summary = summary[:237].rstrip() + "..."
        aliases = [alias for alias in vuln.get("aliases", []) if alias != vuln_id]
        alias_text = f" ({', '.join(aliases[:3])})" if aliases else ""
        link = f"https://osv.dev/vulnerability/{vuln.get('id')}" if vuln.get("id") else ""
        lines.extend([
            f"### {vuln_id}{alias_text}",
            "",
            f"- **Severity:** {_vulnerability_severity(vuln)}",
            f"- **Summary:** {summary}",
        ])
        if link:
            link_html = f'<a href="{escape(link)}">View OSV record</a>'
        else:
            link_html = ""
        lines.extend([
            '<div class="vuln-card">',
            f'<strong>{escape(str(vuln_id))}{escape(alias_text)}</strong>',
            f'<span>{escape(_vulnerability_severity(vuln))}</span>',
            f'<p>{escape(summary)}</p>',
            link_html,
            '</div>',
        ])
    lines.append("</div>")
    return "\n".join(lines).strip()


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


def build_good_first_issues_section(snapshot: dict[str, Any]) -> str:
    issues = snapshot.get("issues", [])
    stats = snapshot.get("stats", {})
    total = stats.get("open_issues_total", len(issues))
    sampled = stats.get("issues_sampled", len(issues))
    candidates = _beginner_issue_candidates(issues, limit=5)
    lines = [
        '<h2 class="report-heading report-heading-green">Good First Issues</h2>',
        "",
        f"RepoFlow sampled **{sampled}** of **{total}** open GitHub issues and ranked beginner-friendly tasks using labels, scope clues, assignee status, comments, and concrete file references.",
        "",
    ]
    if not issues:
        if total:
            lines.append("GitHub reports open issues, but the sampled API response did not include issue records.")
        else:
            lines.append("No open GitHub issues found. This repo may use an external issue tracker or currently have no public issue queue.")
        return "\n".join(lines)

    if not candidates:
        lines.extend([
            "No sampled issue has enough evidence to confidently recommend as beginner-friendly.",
            "For a first contribution, ask maintainers for a small scoped task instead of picking an issue only from its title.",
        ])
        return "\n".join(lines)

    for candidate in candidates:
        issue = candidate["issue"]
        reasons = "; ".join(candidate["reasons"])
        lines.extend([
            f"### #{issue.get('number')} - {issue.get('title')}",
            "",
            f"- **Estimated difficulty:** {candidate['difficulty']}",
            f"- **Why it may suit a student:** {reasons}.",
            f"- **Suggested first step:** {candidate['first_step']}",
            f"- **Issue:** [Open on GitHub]({issue.get('url', '#')})",
            "",
        ])
    return "\n".join(lines).strip()


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
    sampled_count = stats.get("branches_sampled", len(branches))
    unprotected = sorted(
        branch.get("name", "")
        for branch in branches
        if branch.get("name") and not branch.get("protected")
    )
    if protected_count:
        lines.append(f"**{protected_count} of {sampled_count} sampled branches are protected ✅**")
        if unprotected:
            lines.append("")
            lines.append("Unprotected sampled branches:")
            for name in unprotected[:10]:
                lines.append(f"- **{name}**")
            if len(unprotected) > 10:
                lines.append(f"- _{len(unprotected) - 10} more unprotected branches omitted._")
    else:
        lines.append(
            "No protected branches were found in the sampled branch list. "
            f"Consider protecting **{default}** if direct pushes should be restricted."
        )
    lines.append("")

    return "\n".join(lines).strip()
