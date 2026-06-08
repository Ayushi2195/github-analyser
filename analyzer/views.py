import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean

import markdown
from django.conf import settings
from django.http import FileResponse, HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from pymongo.errors import PyMongoError

from analyzer.github_api import GitHubAPIError, fetch_repo_snapshot, parse_repo_url
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
    update_pdf_path,
)
from analyzer.pdf_generator import html_to_pdf
from analyzer.report_builder import _branch_category
from .crew.crew import run_analysis_result

SESSION_REPORT_KEY = "repoflow_report"
CACHE_REPORT_VERSION = 4
PDF_CACHE_VERSION = 1
PDF_STORAGE_DIR = Path(settings.BASE_DIR) / "generated_reports"

def _format_count(value: int) -> str:
    if value >= 1000:
        return f"{value / 1000:.1f}k".replace(".0k", "k")
    return str(value)


def _gallery_item(analysis: RepoAnalysisCache) -> dict:
    return {
        "full_name": f"{analysis.owner}/{analysis.repo_name}",
        "owner": analysis.owner,
        "repo": analysis.repo_name,
        "repo_url": analysis.repo_url,
        "display_url": analysis.repo_url.replace("https://", ""),
        "report_url": reverse(
            "cached_report",
            kwargs={"owner": analysis.owner, "repo_name": analysis.repo_name},
        ),
        "is_featured": bool(getattr(analysis, "is_featured", False)),
        "health_score": analysis.health_score or 0,
        "health_label": analysis.health_label or "Unknown",
        "primary_language": analysis.primary_language or "Unknown",
        "tech_stack": analysis.tech_stack or [analysis.primary_language or "Repo"],
        "stars": _format_count(analysis.stars or 0),
        "branch_count": cached_branch_count(analysis),
        "analyzed_ago": analyzed_ago_label(analysis),
        "analyzed_at_label": analyzed_at_label(analysis),
    }


def _gallery_items() -> list[dict]:
    real_analyses = safe_cached_analyses(limit=6, is_featured=False)
    if len(real_analyses) >= 6:
        return [_gallery_item(analysis) for analysis in real_analyses[:6]]

    featured_needed = min(3, 6 - len(real_analyses))
    featured_analyses = safe_cached_analyses(limit=featured_needed, is_featured=True)
    analyses = [*real_analyses, *featured_analyses]
    return [_gallery_item(analysis) for analysis in analyses]


def _cached_analysis_count() -> int:
    try:
        connect_mongo()
        return RepoAnalysisCache.objects.count()
    except (PyMongoError, OSError):
        return 0


def _homepage_context(extra: dict | None = None) -> dict:
    total_real = _cached_analysis_count()
    gallery = _gallery_items()
    avg_score = round(mean(item["health_score"] for item in gallery)) if gallery else 0
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


def _health_color(score: int) -> str:
    if score >= 80:
        return "#10b981"
    if score >= 65:
        return "#f59e0b"
    return "#ef4444"


def _format_date(value: str | None) -> str:
    if not value:
        return "Data unavailable"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%d %b %Y")
    except ValueError:
        return value


def _issue_label_style(label: str) -> dict:
    label_lower = label.lower()
    if "bug" in label_lower or "fix" in label_lower:
        return {"bg": "#fee2e2", "border": "#fecaca", "color": "#991b1b"}
    if "feature" in label_lower or "enhancement" in label_lower:
        return {"bg": "#dbeafe", "border": "#bfdbfe", "color": "#1d4ed8"}
    if "help" in label_lower or "good first" in label_lower:
        return {"bg": "#dcfce7", "border": "#bbf7d0", "color": "#166534"}
    if "doc" in label_lower:
        return {"bg": "#fef3c7", "border": "#fde68a", "color": "#92400e"}
    if label_lower == "unlabeled":
        return {"bg": "#f1f5f9", "border": "#cbd5e1", "color": "#475569"}
    return {"bg": "#eef2ff", "border": "#c7d2fe", "color": "#4338ca"}


def _build_pdf_summary(snapshot: dict) -> dict:
    issues = snapshot.get("issues", [])
    prs = snapshot.get("pull_requests", [])
    branches = snapshot.get("branches", [])
    default_branch = snapshot.get("meta", {}).get("default_branch")
    stats = snapshot.get("stats", {})
    label_groups: dict[str, list[dict]] = defaultdict(list)
    for issue in issues:
        labels = issue.get("labels") or ["unlabeled"]
        for label in labels:
            label_groups[label].append(issue)

    issue_groups = [
        {
            "label": label,
            "count": len(grouped),
            "issues": grouped[:5],
            "displayed_count": min(len(grouped), 5),
            "style": _issue_label_style(label),
        }
        for label, grouped in sorted(label_groups.items(), key=lambda item: (-len(item[1]), item[0]))[:6]
    ]

    pr_targets = Counter(pr.get("base") or "unknown" for pr in prs)
    branch_category_counts: Counter = Counter()
    branch_category_examples: dict[str, list[str]] = defaultdict(list)
    for branch in branches:
        name = branch.get("name") or ""
        if not name:
            continue
        category = "Default branch" if name == default_branch else _branch_category(name)[0]
        branch_category_counts[category] += 1
        if len(branch_category_examples[category]) < 3:
            branch_category_examples[category].append(name)
    branch_groups = [
        {
            "category": category,
            "count": count,
            "examples": branch_category_examples.get(category, []),
        }
        for category, count in branch_category_counts.most_common(6)
    ]
    branch_rows = [
        {
            "name": branch.get("name") or "Data unavailable",
            "last_commit_date": _format_date(branch.get("last_commit_date")),
            "open_prs": pr_targets.get(branch.get("name"), 0),
            "protected": "Yes" if branch.get("protected") else "No",
        }
        for branch in branches[:12]
    ]

    return {
        "issues_total": stats.get("open_issues_total", len(issues)),
        "issues_sampled": stats.get("issues_sampled", len(issues)),
        "prs_total": stats.get("open_prs_total", len(prs)),
        "prs_sampled": stats.get("pull_requests_sampled", len(prs)),
        "branches_sampled": stats.get("branches_sampled", len(branches)),
        "issue_groups_note": "Counts are from the sampled GitHub API issues in this report. Each group shows up to 5 examples.",
        "issue_groups": issue_groups,
        "branch_groups": branch_groups,
        "branch_rows": branch_rows,
    }


def _normalize_pdf_summary(summary: dict) -> dict:
    summary["issue_groups_note"] = (
        "Counts are from the sampled GitHub API issues in this report. "
        "Each group shows up to 5 examples."
    )
    for group in summary.get("issue_groups", []):
        count = group.get("count", 0)
        shown = len(group.get("issues", []))
        group["displayed_count"] = min(shown, count, 5)
        group.setdefault("style", _issue_label_style(group.get("label", "unlabeled")))
    summary.setdefault("branch_groups", [])
    return summary


def _pdf_summary_for(repo_url: str) -> dict:
    try:
        cached = get_cached_analysis(repo_url)
        cached_summary = (cached.report_sections or {}).get("pdf_summary") if cached else None
        if cached_summary and cached_summary.get("issue_groups") and cached_summary.get("branch_rows"):
            return _normalize_pdf_summary(cached_summary)
    except (GitHubAPIError, PyMongoError, OSError):
        pass

    try:
        return _normalize_pdf_summary(_build_pdf_summary(fetch_repo_snapshot(repo_url)))
    except (GitHubAPIError, PyMongoError, OSError):
        return _normalize_pdf_summary({
            "issues_total": "Data unavailable",
            "issues_sampled": "Data unavailable",
            "prs_total": "Data unavailable",
            "prs_sampled": "Data unavailable",
            "branches_sampled": "Data unavailable",
            "issue_groups": [],
            "branch_groups": [],
            "branch_rows": [],
        })


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
            if not _stored_pdf_path(normalized_url):
                try:
                    _write_pdf_file(normalized_url, html_report, md_report)
                except Exception:
                    pass
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
        "pdf_summary": _build_pdf_summary(result["snapshot"]),
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
    try:
        _write_pdf_file(normalized_url, html_report, md_report)
    except Exception:
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
    pdf_summary = _pdf_summary_for(repo_url)
    score_dash = max(0, min(100, health_score)) * 2.51
    return render_to_string(
        "analyzer/report_print.html",
        {
            "repo_url": repo_url,
            "repo_display": _repo_display_name(repo_url, md_report),
            "report_html": _strip_first_h1(html_report),
            "generated_at": datetime.now().strftime("%d %b %Y, %I:%M %p"),
            "health_score": health_score,
            "health_label": health_label,
            "health_color": _health_color(health_score),
            "score_dash": score_dash,
            "score_gap": 251 - score_dash,
            "pdf_summary": pdf_summary,
        },
    )


def _pdf_filename(repo_url: str) -> str:
    try:
        _, repo = parse_repo_url(repo_url)
        safe = re.sub(r"[^\w\-]", "", repo)[:40]
        return f"repoflow-{safe}-report.pdf"
    except GitHubAPIError:
        return "repoflow-report.pdf"


def _pdf_cache_path(repo_url: str) -> Path:
    try:
        owner, repo = parse_repo_url(repo_url)
        safe_owner = re.sub(r"[^\w\-]", "", owner)[:40]
        safe_repo = re.sub(r"[^\w\-]", "", repo)[:40]
        filename = f"repoflow-{safe_owner}-{safe_repo}-v{PDF_CACHE_VERSION}.pdf"
    except GitHubAPIError:
        filename = f"repoflow-report-v{PDF_CACHE_VERSION}.pdf"
    return PDF_STORAGE_DIR / filename


def _write_pdf_file(repo_url: str, html_report: str, md_report: str) -> Path:
    PDF_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    path = _pdf_cache_path(repo_url)
    pdf_html = _build_pdf_html(repo_url, html_report, md_report)
    path.write_bytes(html_to_pdf(pdf_html))
    try:
        update_pdf_path(repo_url, str(path))
    except (GitHubAPIError, PyMongoError, OSError):
        pass
    return path


def _stored_pdf_path(repo_url: str) -> Path | None:
    try:
        cached = get_cached_analysis(repo_url)
    except (GitHubAPIError, PyMongoError, OSError):
        return None
    if not cached or not cached.pdf_path:
        return None
    path = Path(cached.pdf_path)
    if path.exists() and path.is_file():
        return path
    return None


def _pdf_file_response(path: Path, repo_url: str) -> FileResponse:
    return FileResponse(
        path.open("rb"),
        content_type="application/pdf",
        as_attachment=True,
        filename=_pdf_filename(repo_url),
    )


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


def download_pdf(request):
    repo_url = request.GET.get("repo_url", "").strip()
    if not repo_url:
        return redirect("index")

    stored_pdf = _stored_pdf_path(repo_url)
    if stored_pdf:
        return _pdf_file_response(stored_pdf, repo_url)

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
        pdf_path = _write_pdf_file(repo_url, html_report, md_report)
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

    return _pdf_file_response(pdf_path, repo_url)
