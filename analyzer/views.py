import re
from datetime import datetime
from pathlib import Path
from statistics import mean

import markdown
from django.conf import settings
from django.http import FileResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from pymongo.errors import ConnectionFailure, PyMongoError, ServerSelectionTimeoutError

from analyzer.github_api import GitHubAPIError, fetch_repo_snapshot, parse_repo_url
from analyzer.mongo_cache import (
    RepoAnalysisCache,
    analyzed_ago_label,
    analyzed_at_label,
    cache_is_fresh,
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
from .crew.crew import run_analysis_result

CACHE_REPORT_VERSION = 20
PDF_CACHE_VERSION = 16
PDF_STORAGE_DIR = Path(settings.BASE_DIR) / "generated_reports"

# turns stars for a repo , eg:45135 into "45.1k" for better look
def _format_count(value: int) -> str:
    if value >= 1000:
        return f"{value / 1000:.1f}k".replace(".0k", "k")
    return str(value)


def _scorecard_display(scorecard: dict) -> dict[str, str]:
    score = scorecard.get("score")
    if score is None:
        return {
            "value": "N/A",
            "state": "attention",
            "text_class": "text-slate-500",
            "label": "Scorecard unavailable",
        }
    try:
        numeric = float(score)
    except (TypeError, ValueError):
        return {
            "value": "N/A",
            "state": "attention",
            "text_class": "text-slate-500",
            "label": "Scorecard unavailable",
        }
    text_class = "text-emerald-600" if numeric >= 7 else "text-amber-600" if numeric >= 4 else "text-rose-600"
    value = f"{numeric:.1f}/10".replace(".0/10", "/10")
    return {
        "value": value,
        "state": "healthy",
        "text_class": text_class,
        "label": "OpenSSF Scorecard",
    }


def _gallery_item(analysis: RepoAnalysisCache) -> dict:
    openssf_sections = analysis.openssf_sections or {}
    scorecard = openssf_sections.get("scorecard") or {}
    scorecard_display = _scorecard_display(scorecard)
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
        "scorecard_score": scorecard_display["value"],
        "scorecard_label": scorecard_display["label"],
        "health_label": scorecard_display["label"],
        "health_state": scorecard_display["state"],
        "health_text_class": scorecard_display["text_class"],
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

    featured_needed = min(3, 6 - len(real_analyses)) # if not enough real analyses, fill with featured ones, but max 3 featured to keep it fresh
    featured_analyses = safe_cached_analyses(limit=featured_needed, is_featured=True)
    analyses = [*real_analyses, *featured_analyses]
    return [_gallery_item(analysis) for analysis in analyses]


def _safe_gallery_items() -> list[dict]: 
    try:
        return _gallery_items()
    except Exception as exc:
        print(f"Gallery unavailable: {exc}", flush=True)
        return []


# to show how many real analyses done, count the real analyses(whose isFeatured=False)
def _cached_real_analysis_count() -> int: 
    try:
        connect_mongo()
        return RepoAnalysisCache.objects(is_featured=False).count() 
    except Exception as exc:
        print(f"Analysis count unavailable: {exc}", flush=True)
        return 0


def _fallback_preview() -> dict:   #if MongoDB is not available or no cached data for the sample repo, show this hardcoded preview data for the sample repo (tiangolo/fastapi)
    return {
        "repo_display": "tiangolo/fastapi",
        "health_score": 80,
        "scorecard_score": "N/A",
        "health_label": "Security signals",
        "health_class": "emerald",
        "has_preview_data": False,
        "issues_total": 0,
        "prs_total": 0,
        "branches_sampled": 0,
        "issue_titles": [
            "Analyze tiangolo/fastapi to show exact GitHub issue titles here",
            "Saved FastAPI data will include issue numbers and titles",
            "The preview updates from MongoDB once the report exists",
        ],
    }


def _score_tone(score: int) -> str:
    if score >= 80:
        return "emerald"
    if score >= 65:
        return "amber"
    return "rose"


def _sample_preview() -> dict:
    preview = _fallback_preview()
    try:
        cached = get_cached_analysis("https://github.com/tiangolo/fastapi")
    except (GitHubAPIError, PyMongoError, OSError):
        return preview
    if not cached:
        return preview

    report_sections = ((cached.openssf_sections or {}).get("report") or {})
    summary = report_sections.get("pdf_summary") or {}
    issue_titles = list(summary.get("issue_titles") or [])[:3]
    if not issue_titles:
        # Read reports saved before issue groups were removed from the PDF data.
        for group in summary.get("issue_groups", []):
            for issue in group.get("issues", []):
                title = issue.get("title")
                number = issue.get("number")
                if title:
                    prefix = f"#{number} " if number else ""
                    issue_titles.append(f"{prefix}{title}")
                if len(issue_titles) >= 3:
                    break
            if len(issue_titles) >= 3:
                break

    security_summary = (cached.openssf_sections or {}).get("security_summary") or {}
    score = security_summary.get("score", preview["health_score"])
    preview.update(
        {
            "repo_display": f"{cached.owner}/{cached.repo_name}",
            "health_score": score,
            "scorecard_score": _scorecard_display((cached.openssf_sections or {}).get("scorecard") or {})["value"],
            "health_label": security_summary.get("label") or preview["health_label"],
            "health_class": _score_tone(score),
            "has_preview_data": True,
            "issues_total": summary.get("issues_total", 0),
            "prs_total": 0,
            "branches_sampled": summary.get("branches_sampled", cached_branch_count(cached)),
            "issue_titles": issue_titles or preview["issue_titles"],
        }
    )
    return preview


def _safe_sample_preview() -> dict:
    try:
        return _sample_preview()
    except Exception as exc:
        print(f"Sample preview unavailable: {exc}", flush=True)
        return _fallback_preview()


#builds stats band on homepage [] [] [] []
def _homepage_context(extra: dict | None = None) -> dict:
    total_real = _cached_real_analysis_count()
    gallery = _safe_gallery_items()
    score_values = []
    for item in gallery:
        raw = item.get("scorecard_score", "N/A").replace("/10", "")
        try:
            score_values.append(float(raw))
        except (TypeError, ValueError):
            pass
    avg_score = round(mean(score_values), 1) if score_values else "N/A"
    context = {
        "gallery_items": gallery,
        "real_analysis_count": total_real,
        "repos_analyzed": f"{total_real:,}",  # toal these many repos analyzed
        "avg_health_score": avg_score,
        "healthy_count": len(score_values),
        "language_count": len({item["primary_language"] for item in gallery if item["primary_language"]}), #how many languages seen
        "sample_tags": ["Structure", "OpenSSF", "OSV", "Branches"],
        "sample_preview": _safe_sample_preview(),
    }
    if extra:
        context.update(extra)
    return context


def _safe_homepage_context(extra: dict | None = None) -> dict:
    try:
        return _homepage_context(extra)
    except Exception as exc:
        print(f"Homepage context fallback used: {exc}", flush=True)
        context = {
            "gallery_items": [],
            "real_analysis_count": 0,
            "repos_analyzed": "0",
            "avg_health_score": 0,
            "healthy_count": 0,
            "language_count": 0,
            "sample_tags": ["Structure", "OpenSSF", "OSV", "Branches"],
            "sample_preview": _fallback_preview(),
        }
        if extra:
            context.update(extra)
        return context


# GET /  => shows homepage
def index(request):
    return render(request, "analyzer/index.html", _safe_homepage_context())


def _build_pdf_summary(snapshot: dict) -> dict:
    issues = snapshot.get("issues", [])
    branches = snapshot.get("branches", [])
    stats = snapshot.get("stats", {})
    scorecard = snapshot.get("openssf_scorecard") or {}
    badge = snapshot.get("best_practices_badge") or {}
    vulns = (snapshot.get("osv_vulnerabilities") or {}).get("vulns") or []
    issue_titles = []
    for issue in issues[:3]:
        title = issue.get("title")
        if title:
            number = issue.get("number")
            issue_titles.append(f"#{number} {title}" if number else title)

    return {
        "issues_total": stats.get("open_issues_total", len(issues)),
        "issues_sampled": stats.get("issues_sampled", len(issues)),
        "scorecard_status": "Available" if scorecard.get("available") else "Unavailable",
        "best_practices_level": (badge.get("level") or "None").title(),
        "osv_vulnerability_count": len(vulns),
        "branches_sampled": stats.get("branches_sampled", len(branches)),
        "issue_titles": issue_titles,
    }


def _pdf_summary_for(repo_url: str) -> dict:
    try:
        cached = get_cached_analysis(repo_url)
        cached_summary = (((cached.openssf_sections or {}).get("report") or {}).get("pdf_summary")) if cached else None
        if cached_summary:
            return cached_summary
    except (GitHubAPIError, PyMongoError, OSError):
        pass

    try:
        return _build_pdf_summary(fetch_repo_snapshot(repo_url))
    except (GitHubAPIError, PyMongoError, OSError):
        return {
            "issues_total": "Data unavailable",
            "issues_sampled": "Data unavailable",
            "scorecard_status": "Data unavailable",
            "best_practices_level": "Data unavailable",
            "osv_vulnerability_count": "Data unavailable",
            "branches_sampled": "Data unavailable",
            "issue_titles": [],
        }


# VERY IMP FUNCTION
def _render_markdown_report(repo_url: str) -> tuple[str, str]:
    normalized_url = normalize_repo_url(repo_url)
    try:
        cached = get_cached_analysis(normalized_url)
        if cached and cached_markdown(cached) and cache_is_fresh(cached):
            print("Using MongoDB cache (analysis is less than 24 hours old).", flush=True)
            return _cached_report_content(cached)
    except Exception as exc:
        print(f"Cache lookup skipped: {exc}", flush=True)

    result = run_analysis_result(normalized_url) #what 4 crewai agents from crew/crew.py returns
    md_report = result["markdown"]  #returns a dict
    html_report = markdown.markdown(  #mkd gets converted to HTML using markdown library
        md_report,
        extensions=["tables", "fenced_code", "nl2br"],
        # handles branch tables, f_c->code blocks, nl2br turns newlines into <br> tags for better formatting
    )
    report_sections = {
        # sections is a dict with keys like 'structure', 'issues', 'pull_requests', 'branches' containing respective mkd sections generated by agents
        **result["sections"],
        "markdown": md_report,
        "html": html_report,
        "pdf_summary": _build_pdf_summary(result["snapshot"]),
        "cache_version": CACHE_REPORT_VERSION,
    }
    try:
        print("Saving report to MongoDB...", flush=True) #after agents finish, save to mongodb
        save_analysis_cache(
            normalized_url,
            result["snapshot"],
            result["health"],
            report_sections,
        )
        print("Report saved to MongoDB.", flush=True)
    except (ConnectionFailure, ServerSelectionTimeoutError) as exc:
        print(f"MongoDB save failed, returning report without cache: {type(exc).__name__}: {exc}", flush=True)
    except PyMongoError as exc:
        print(f"MongoDB save skipped, returning report without cache: {type(exc).__name__}: {exc}", flush=True)
    except Exception as exc:
        print(f"MongoDB save skipped: {type(exc).__name__}: {exc}", flush=True)
    _try_write_pdf_file(normalized_url, html_report, md_report)
    print("Analysis completed.", flush=True)
    return md_report, html_report


def _cached_report_content(cached: RepoAnalysisCache) -> tuple[str, str]:
    """Render a saved report without fetching GitHub data or running CrewAI."""
    md_report = cached_markdown(cached)
    html_report = cached_html(cached) or markdown.markdown(
        md_report,
        extensions=["tables", "fenced_code", "nl2br"],
    )
    return md_report, html_report


def _strip_first_h1(html_report: str) -> str:
    html = re.sub(r"<h1>.*?</h1>", "", html_report, count=1, flags=re.DOTALL)
    # Horizontal rules from markdown add extra layers; hide them in PDF.
    html = re.sub(r"<hr\s*/?>", "", html, flags=re.IGNORECASE)
    return html


def _repo_display_name(repo_url: str, md_report: str) -> str:
    match = re.search(r"\*\*Repository:\*\* \[([^\]]+)\]", md_report)
    if match:
        return match.group(1)
    try:
        owner, repo = parse_repo_url(repo_url)
        return f"{owner}/{repo}"
    except GitHubAPIError:
        return repo_url


def _build_pdf_html(repo_url: str, html_report: str, md_report: str) -> str:
    pdf_summary = _pdf_summary_for(repo_url)
    return render_to_string(
        "analyzer/report_print.html",
        {
            "repo_url": repo_url,
            "repo_display": _repo_display_name(repo_url, md_report),
            "report_html": _strip_first_h1(html_report),
            "generated_at": datetime.now().strftime("%d %b %Y, %I:%M %p"),
            "pdf_summary": pdf_summary,
        },
    )


def _pdf_filename(repo_url: str) -> str:
    try:
        owner, repo = parse_repo_url(repo_url)
        safe_owner = re.sub(r"[^\w\-]", "", owner)[:40]
        safe_repo = re.sub(r"[^\w\-]", "", repo)[:40]
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"repoflow-{safe_owner}-{safe_repo}-{stamp}.pdf"
    except GitHubAPIError:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"repoflow-report-{stamp}.pdf"


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


def _try_write_pdf_file(repo_url: str, html_report: str, md_report: str) -> Path | None:
    try:
        return _write_pdf_file(repo_url, html_report, md_report)
    except Exception as exc:
        print(f"PDF generation skipped: {exc}", flush=True)
        try:
            update_pdf_path(repo_url, "")
        except (GitHubAPIError, PyMongoError, OSError):
            pass
        return None


def _stored_pdf_path(repo_url: str) -> Path | None:
    deterministic_path = _pdf_cache_path(repo_url)
    if deterministic_path.exists() and deterministic_path.is_file():
        return deterministic_path

    try:
        cached = get_cached_analysis(repo_url)
    except (GitHubAPIError, PyMongoError, OSError):
        return None
    if not cached or not cached.pdf_path:
        return None
    path = Path(cached.pdf_path)
    if not path.name.endswith(f"-v{PDF_CACHE_VERSION}.pdf"):
        return None
    if path.exists() and path.is_file():
        return path
    return None


def _pdf_file_response(path: Path, repo_url: str) -> FileResponse:
    response = FileResponse(
        path.open("rb"),
        content_type="application/pdf",
        as_attachment=True,
        filename=_pdf_filename(repo_url),
    )
    response["Content-Length"] = str(path.stat().st_size)
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    return response


# ANALYZE BUTTON FUNCTION - POST /analyze
def analyze(request):
    if request.method != "POST": #this view only accepts POST requests, if GET request comes, show homepage
        return render(request, "analyzer/index.html", _safe_homepage_context())

    repo_url = request.POST.get("repo_url", "").strip() # get the repo url from the form input in homepage
    if not repo_url: #if no url pasted, show error
        return render(
            request,
            "analyzer/index.html",
            _safe_homepage_context({"error": "Please enter a GitHub repository URL.", "repo_url": repo_url}),
        )

    try: #else
        md_report, html_report = _render_markdown_report(repo_url)
        return render(
            request,
            "analyzer/index.html",
            _safe_homepage_context({"report": html_report, "repo_url": repo_url}), #everything's fine
        )
    except GitHubAPIError as exc: #errors related to GitHub API like rate limits, repo not found, etc
        return render(
            request,
            "analyzer/index.html",
            _safe_homepage_context({"error": str(exc), "repo_url": repo_url}),
        )
    except Exception as exc: #other exceptional errors
        return render(
            request,
            "analyzer/index.html",
            _safe_homepage_context({
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
            _safe_homepage_context({
                "error": "That saved report was not found. Analyze the repository to create it.",
                "repo_url": repo_url,
            }),
        )

    md_report, html_report = _cached_report_content(cached)
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

    try:
        cached = get_cached_analysis(repo_url)
        if cached and cached_markdown(cached):
            md_report, html_report = _cached_report_content(cached)
        else:
            md_report, html_report = _render_markdown_report(repo_url)
    except GitHubAPIError as exc:
        return render(
            request,
            "analyzer/index.html",
            _safe_homepage_context({"error": str(exc), "repo_url": repo_url}),
        )
    except Exception as exc:
        return render(
            request,
            "analyzer/index.html",
            _safe_homepage_context({
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
            _safe_homepage_context({
                "error": f"PDF export failed: {exc}.{hint}",
                "repo_url": repo_url,
                "report": html_report,
            }),
        )

    return _pdf_file_response(pdf_path, repo_url)
