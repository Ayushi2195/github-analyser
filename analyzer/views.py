import re
from datetime import datetime
from statistics import mean

import markdown
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
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

FALLBACK_GALLERY = [
    {
        "full_name": "facebook/react",
        "owner": "facebook",
        "repo": "react",
        "repo_url": "https://github.com/facebook/react",
        "health_score": 92,
        "health_label": "Healthy",
        "primary_language": "JavaScript",
        "tech_stack": ["JavaScript", "MIT"],
        "stars": 228000,
        "branch_count": 12,
        "analyzed_ago": "5h ago",
    },
    {
        "full_name": "rust-lang/rustlings",
        "owner": "rust-lang",
        "repo": "rustlings",
        "repo_url": "https://github.com/rust-lang/rustlings",
        "health_score": 88,
        "health_label": "Healthy",
        "primary_language": "Rust",
        "tech_stack": ["Rust", "MIT"],
        "stars": 54000,
        "branch_count": 7,
        "analyzed_ago": "1d ago",
    },
    {
        "full_name": "moby/moby",
        "owner": "moby",
        "repo": "moby",
        "repo_url": "https://github.com/moby/moby",
        "health_score": 61,
        "health_label": "Needs attention",
        "primary_language": "Go",
        "tech_stack": ["Go", "Apache-2.0"],
        "stars": 68000,
        "branch_count": 21,
        "analyzed_ago": "3d ago",
    },
]


def _format_count(value: int) -> str:
    if value >= 1000:
        return f"{value / 1000:.1f}k".replace(".0k", "k")
    return str(value)


def _tech_stack(snapshot: dict) -> list[str]:
    meta = snapshot.get("meta", {})
    stack = []
    for value in [meta.get("language"), *(meta.get("topics") or [])[:2], meta.get("license")]:
        if value and value not in stack:
            stack.append(value)
    return stack[:4]


def _gallery_items() -> list[dict]:
    analyses = safe_cached_analyses(limit=5)
    items = [
        {
            "full_name": f"{analysis.owner}/{analysis.repo_name}",
            "owner": analysis.owner,
            "repo": analysis.repo_name,
            "repo_url": analysis.repo_url,
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
    fallbacks = [
        {
            **item,
            "stars": _format_count(item["stars"]),
            "analyzed_at_label": "Sample gallery item",
        }
        for item in FALLBACK_GALLERY
    ]
    return (items + fallbacks)[:5]


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
    repo_count = max(total_real, 1240)
    context = {
        "gallery_items": gallery,
        "repos_analyzed": f"{repo_count:,}",
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
        if cached and cached_markdown(cached):
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
