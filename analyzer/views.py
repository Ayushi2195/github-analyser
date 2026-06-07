import re
from datetime import datetime
from statistics import mean

import markdown
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from pymongo.errors import PyMongoError

from analyzer.github_api import GitHubAPIError, parse_repo_url
from analyzer.mongo_cache import (
    RepoAnalysisCache,
    analyzed_ago_label,
    analyzed_at_label,
    cached_branch_count,
    cached_html,
    cached_markdown,
    connect_mongo,
    get_cached_analysis,
    normalize_repo_url,
    safe_cached_analyses,
    save_analysis_cache,
)
from analyzer.pdf_generator import html_to_pdf
from .crew.crew import run_analysis_result

SESSION_REPORT_KEY = "repoflow_report"
CACHE_REPORT_VERSION = 2

FEATURED_REPOS = [
    {
        "full_name": "facebook/react",
        "owner": "facebook",
        "repo": "react",
        "repo_url": "https://github.com/facebook/react",
        "health_score": 92,
        "health_label": "Healthy",
        "primary_language": "JavaScript",
        "tech_stack": ["JavaScript", "UI", "MIT"],
        "stars": 228000,
        "branch_count": 12,
        "analyzed_ago": "Featured",
    },
    {
        "full_name": "fastapi/fastapi",
        "owner": "fastapi",
        "repo": "fastapi",
        "repo_url": "https://github.com/fastapi/fastapi",
        "health_score": 91,
        "health_label": "Healthy",
        "primary_language": "Python",
        "tech_stack": ["Python", "API", "MIT"],
        "stars": 86000,
        "branch_count": 8,
        "analyzed_ago": "Featured",
    },
    {
        "full_name": "django/django",
        "owner": "django",
        "repo": "django",
        "repo_url": "https://github.com/django/django",
        "health_score": 89,
        "health_label": "Healthy",
        "primary_language": "Python",
        "tech_stack": ["Python", "Web", "BSD-3-Clause"],
        "stars": 83000,
        "branch_count": 10,
        "analyzed_ago": "Featured",
    },
]

FEATURED_REPORTS = {
    "facebook/react": {
        "analyzed_at": "Featured seed report",
        "markdown": """# 📊 GitHub Repository Analysis Report

**Repository:** [facebook/react](https://github.com/facebook/react)

---

## 🏥 Repository Health

**Score:** 92/100 (Healthy)

**Signals:**
- Mature repository structure with clear package boundaries
- Strong ecosystem documentation and active maintenance
- Large issue/PR volume is expected for a project at this scale

---

## 🗂️ Repository Structure

React is a mature JavaScript UI library with a monorepo-style layout. The repo is organized around packages, build tooling, examples, fixtures, and documentation.

### Tech Stack
- JavaScript
- Node.js package tooling
- MIT license

### Key Files and Folders
- **packages/**: Core React packages and supporting modules.
- **fixtures/**: Example apps and integration fixtures.
- **scripts/**: Build, test, and release automation.
- **README.md**: Project overview and onboarding entry point.

---

## 🐛 Open Issues

### Real Numbers Summary

- **Open issues:** Data unavailable in this featured seed report
- **Sampled issues:** Data unavailable

Analyze this repository from the input form to generate exact issue numbers, titles, labels, and authors from the GitHub API.

---

## 🔀 Pull Requests

### Real Numbers Summary

- **Open pull requests:** Data unavailable in this featured seed report
- **Sampled PRs:** Data unavailable

Analyze this repository from the input form to generate exact PR numbers, authors, branch names, and URLs from the GitHub API.

---

## 🌿 Branch Analysis

### Real Numbers Summary

- **Default branch:** Data unavailable in this featured seed report
- **Branches sampled:** Data unavailable

Analyze this repository from the input form to generate exact branch names and protection signals from the GitHub API.
""",
    },
    "fastapi/fastapi": {
        "analyzed_at": "Featured seed report",
        "markdown": """# 📊 GitHub Repository Analysis Report

**Repository:** [fastapi/fastapi](https://github.com/fastapi/fastapi)

---

## 🏥 Repository Health

**Score:** 91/100 (Healthy)

**Signals:**
- Clear Python project identity and documentation
- Strong API-focused ecosystem with active maintenance
- Healthy public contribution workflow

---

## 🗂️ Repository Structure

FastAPI is a Python web framework focused on type hints, API ergonomics, and automatic documentation. The repository layout is documentation-heavy and contributor-friendly.

### Tech Stack
- Python
- ASGI ecosystem
- MIT license

### Key Files and Folders
- **fastapi/**: Framework source package.
- **docs/**: User-facing documentation and examples.
- **tests/**: Regression and behavior coverage.
- **pyproject.toml**: Python project configuration.

---

## 🐛 Open Issues

### Real Numbers Summary

- **Open issues:** Data unavailable in this featured seed report
- **Sampled issues:** Data unavailable

Analyze this repository from the input form to generate exact issue numbers, titles, labels, and authors from the GitHub API.

---

## 🔀 Pull Requests

### Real Numbers Summary

- **Open pull requests:** Data unavailable in this featured seed report
- **Sampled PRs:** Data unavailable

Analyze this repository from the input form to generate exact PR numbers, authors, branch names, and URLs from the GitHub API.

---

## 🌿 Branch Analysis

### Real Numbers Summary

- **Default branch:** Data unavailable in this featured seed report
- **Branches sampled:** Data unavailable

Analyze this repository from the input form to generate exact branch names and protection signals from the GitHub API.
""",
    },
    "django/django": {
        "analyzed_at": "Featured seed report",
        "markdown": """# 📊 GitHub Repository Analysis Report

**Repository:** [django/django](https://github.com/django/django)

---

## 🏥 Repository Health

**Score:** 89/100 (Healthy)

**Signals:**
- Long-running mature framework with stable conventions
- Deep test suite and documentation culture
- Large contributor surface requires careful review discipline

---

## 🗂️ Repository Structure

Django is a mature Python web framework with a stable source layout, extensive tests, and strong documentation. The repository is built for long-term maintenance.

### Tech Stack
- Python
- Web framework
- BSD license

### Key Files and Folders
- **django/**: Framework source package.
- **tests/**: Large test suite for framework behavior.
- **docs/**: Project documentation and release notes.
- **setup.cfg / pyproject.toml**: Packaging and tooling configuration.

---

## 🐛 Open Issues

### Real Numbers Summary

- **Open issues:** Data unavailable in this featured seed report
- **Sampled issues:** Data unavailable

Analyze this repository from the input form to generate exact issue numbers, titles, labels, and authors from the GitHub API.

---

## 🔀 Pull Requests

### Real Numbers Summary

- **Open pull requests:** Data unavailable in this featured seed report
- **Sampled PRs:** Data unavailable

Analyze this repository from the input form to generate exact PR numbers, authors, branch names, and URLs from the GitHub API.

---

## 🌿 Branch Analysis

### Real Numbers Summary

- **Default branch:** Data unavailable in this featured seed report
- **Branches sampled:** Data unavailable

Analyze this repository from the input form to generate exact branch names and protection signals from the GitHub API.
""",
    },
}


def _format_count(value: int) -> str:
    if value >= 1000:
        return f"{value / 1000:.1f}k".replace(".0k", "k")
    return str(value)


def _featured_gallery_items() -> list[dict]:
    return [
        {
            **item,
            "stars": _format_count(item["stars"]),
            "display_url": item["repo_url"].replace("https://", ""),
            "report_url": reverse(
                "featured_report",
                kwargs={"owner": item["owner"], "repo_name": item["repo"]},
            ),
            "is_featured": True,
            "analyzed_at_label": "Featured seed report",
        }
        for item in FEATURED_REPOS
    ]


def _gallery_items() -> list[dict]:
    analyses = safe_cached_analyses(limit=6)
    items = [
        {
            "full_name": f"{analysis.owner}/{analysis.repo_name}",
            "owner": analysis.owner,
            "repo": analysis.repo_name,
            "repo_url": analysis.repo_url,
            "display_url": analysis.repo_url.replace("https://", ""),
            "report_url": reverse(
                "cached_report",
                kwargs={"owner": analysis.owner, "repo_name": analysis.repo_name},
            ),
            "is_featured": False,
            "health_score": analysis.health_score or 0,
            "health_label": analysis.health_label or "Unknown",
            "primary_language": analysis.primary_language or "Unknown",
            "tech_stack": analysis.tech_stack or [analysis.primary_language or "Repo"],
            "stars": _format_count(analysis.stars or 0),
            "branch_count": cached_branch_count(analysis),
            "analyzed_ago": analyzed_ago_label(analysis),
            "analyzed_at_label": analyzed_at_label(analysis),
        }
        for analysis in analyses
    ]
    if len(items) >= 6:
        return items[:6]

    featured = _featured_gallery_items()
    if not items:
        return featured

    featured_needed = max(0, 4 - len(items))
    return items + featured[:featured_needed]


def _cached_analysis_count() -> int:
    try:
        connect_mongo()
        return RepoAnalysisCache.objects.count()
    except (PyMongoError, OSError):
        return 0


def _homepage_context(extra: dict | None = None) -> dict:
    total_real = _cached_analysis_count()
    gallery = _gallery_items()
    avg_score = round(mean(item["health_score"] for item in gallery))
    context = {
        "gallery_items": gallery,
        "repos_analyzed": f"{total_real:,}",
        "avg_health_score": avg_score,
        "healthy_count": sum(1 for item in gallery if item["health_score"] >= 80),
        "language_count": len({item["primary_language"] for item in gallery if item["primary_language"]}),
        "sample_tags": ["Structure", "Health score", "Issues", "Branches"],
    }
    if extra:
        context.update(extra)
    return context


def index(request):
    return render(request, "analyzer/index.html", _homepage_context())


def _render_markdown_report(repo_url: str) -> tuple[str, str]:
    normalized_url = normalize_repo_url(repo_url)
    try:
        cached = get_cached_analysis(normalized_url)
        if (
            cached
            and cached_markdown(cached)
            and (cached.report_sections or {}).get("cache_version") == CACHE_REPORT_VERSION
        ):
            md_report = cached_markdown(cached)
            html_report = cached_html(cached) or markdown.markdown(
                md_report,
                extensions=["tables", "fenced_code", "nl2br"],
            )
            return md_report, html_report
    except (PyMongoError, OSError):
        pass

    result = run_analysis_result(normalized_url)
    md_report = result["markdown"]
    html_report = markdown.markdown(
        md_report,
        extensions=["tables", "fenced_code", "nl2br"],
    )
    report_sections = {
        **result["sections"],
        "markdown": md_report,
        "html": html_report,
        "cache_version": CACHE_REPORT_VERSION,
    }
    try:
        save_analysis_cache(
            normalized_url,
            result["snapshot"],
            result["health"],
            report_sections,
        )
    except (PyMongoError, OSError):
        pass
    return md_report, html_report


def _strip_first_h1(html_report: str) -> str:
    html = re.sub(r"<h1>.*?</h1>", "", html_report, count=1, flags=re.DOTALL)
    # Horizontal rules from markdown add extra layers; hide them in PDF.
    html = re.sub(r"<hr\s*/?>", "", html, flags=re.IGNORECASE)
    return html


def _parse_health(md_report: str) -> tuple[int, str]:
    match = re.search(r"\*\*Score:\*\* (\d+)/100 \(([^)]+)\)", md_report)
    if match:
        return int(match.group(1)), match.group(2)
    return 0, "Unknown"


def _repo_display_name(repo_url: str, md_report: str) -> str:
    match = re.search(r"\*\*Repository:\*\* \[([^\]]+)\]", md_report)
    if match:
        return match.group(1)
    try:
        owner, repo = parse_repo_url(repo_url)
        return f"{owner}/{repo}"
    except GitHubAPIError:
        return repo_url


def _cache_report(request, repo_url: str, html_report: str, md_report: str) -> None:
    request.session[SESSION_REPORT_KEY] = {
        "repo_url": repo_url,
        "html_report": html_report,
        "md_report": md_report,
    }
    request.session.modified = True


def _get_cached_report(request, repo_url: str) -> tuple[str, str] | None:
    cached = request.session.get(SESSION_REPORT_KEY)
    if cached and cached.get("repo_url") == repo_url:
        return cached.get("md_report", ""), cached.get("html_report", "")
    return None


def _build_pdf_html(repo_url: str, html_report: str, md_report: str) -> str:
    health_score, health_label = _parse_health(md_report)
    return render_to_string(
        "analyzer/report_print.html",
        {
            "repo_url": repo_url,
            "repo_display": _repo_display_name(repo_url, md_report),
            "report_html": _strip_first_h1(html_report),
            "generated_at": datetime.now().strftime("%d %b %Y, %I:%M %p"),
            "health_score": health_score,
            "health_label": health_label,
        },
    )


def _pdf_filename(repo_url: str) -> str:
    try:
        _, repo = parse_repo_url(repo_url)
        safe = re.sub(r"[^\w\-]", "", repo)[:40]
        return f"repoflow-{safe}-report.pdf"
    except GitHubAPIError:
        return "repoflow-report.pdf"


def analyze(request):
    if request.method != "POST":
        return render(request, "analyzer/index.html", _homepage_context())

    repo_url = request.POST.get("repo_url", "").strip()
    if not repo_url:
        return render(
            request,
            "analyzer/index.html",
            _homepage_context({"error": "Please enter a GitHub repository URL.", "repo_url": repo_url}),
        )

    try:
        md_report, html_report = _render_markdown_report(repo_url)
        _cache_report(request, repo_url, html_report, md_report)
        return render(
            request,
            "analyzer/index.html",
            _homepage_context({"report": html_report, "repo_url": repo_url}),
        )
    except GitHubAPIError as exc:
        return render(
            request,
            "analyzer/index.html",
            _homepage_context({"error": str(exc), "repo_url": repo_url}),
        )
    except Exception as exc:
        return render(
            request,
            "analyzer/index.html",
            _homepage_context({
                "error": f"Analysis failed: {exc}",
                "repo_url": repo_url,
            }),
        )


def cached_report(request, owner: str, repo_name: str):
    repo_url = f"https://github.com/{owner}/{repo_name}"
    try:
        cached = get_cached_analysis(repo_url)
    except (GitHubAPIError, PyMongoError, OSError):
        cached = None

    if not cached or not cached_markdown(cached):
        return render(
            request,
            "analyzer/index.html",
            _homepage_context({
                "error": "That saved report was not found. Analyze the repository to create it.",
                "repo_url": repo_url,
            }),
        )

    if (cached.report_sections or {}).get("cache_version") != CACHE_REPORT_VERSION:
        md_report, html_report = _render_markdown_report(repo_url)
        try:
            cached = get_cached_analysis(repo_url) or cached
        except (GitHubAPIError, PyMongoError, OSError):
            pass
    else:
        md_report = cached_markdown(cached)
        html_report = cached_html(cached) or markdown.markdown(
            md_report,
            extensions=["tables", "fenced_code", "nl2br"],
        )
    _cache_report(request, repo_url, html_report, md_report)
    return render(
        request,
        "analyzer/report_detail.html",
        {
            "repo_url": repo_url,
            "repo_display": f"{owner}/{repo_name}",
            "report": html_report,
            "analyzed_at": analyzed_at_label(cached),
        },
    )


def featured_report(request, owner: str, repo_name: str):
    key = f"{owner}/{repo_name}"
    featured = FEATURED_REPORTS.get(key)
    if not featured:
        return redirect("index")

    repo_url = f"https://github.com/{key}"
    md_report = featured["markdown"]
    html_report = markdown.markdown(
        md_report,
        extensions=["tables", "fenced_code", "nl2br"],
    )
    _cache_report(request, repo_url, html_report, md_report)
    return render(
        request,
        "analyzer/report_detail.html",
        {
            "repo_url": repo_url,
            "repo_display": key,
            "report": html_report,
            "analyzed_at": featured["analyzed_at"],
        },
    )


def download_pdf(request):
    repo_url = request.GET.get("repo_url", "").strip()
    if not repo_url:
        return redirect("index")

    cached = _get_cached_report(request, repo_url)
    if cached:
        md_report, html_report = cached
    else:
        try:
            md_report, html_report = _render_markdown_report(repo_url)
        except GitHubAPIError as exc:
            return render(
                request,
                "analyzer/index.html",
                _homepage_context({"error": str(exc), "repo_url": repo_url}),
            )
        except Exception as exc:
            return render(
                request,
                "analyzer/index.html",
                _homepage_context({
                    "error": f"PDF export failed: {exc}",
                    "repo_url": repo_url,
                }),
            )

    try:
        pdf_html = _build_pdf_html(repo_url, html_report, md_report)
        pdf_bytes = html_to_pdf(pdf_html)
    except Exception as exc:
        hint = ""
        if "playwright" in str(exc).lower() or "chromium" in str(exc).lower():
            hint = " Run: pip install playwright && playwright install chromium"
        return render(
            request,
            "analyzer/index.html",
            _homepage_context({
                "error": f"PDF export failed: {exc}.{hint}",
                "repo_url": repo_url,
                "report": html_report,
            }),
        )

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{_pdf_filename(repo_url)}"'
    return response
