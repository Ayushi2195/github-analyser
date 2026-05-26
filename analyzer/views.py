import re
from datetime import datetime

import markdown
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string

from analyzer.github_api import GitHubAPIError, parse_repo_url
from analyzer.pdf_generator import html_to_pdf
from .crew import run_analysis

SESSION_REPORT_KEY = "repoflow_report"


def index(request):
    return render(request, "analyzer/index.html")


def _render_markdown_report(repo_url: str) -> tuple[str, str]:
    md_report = run_analysis(repo_url)
    html_report = markdown.markdown(
        md_report,
        extensions=["tables", "fenced_code", "nl2br"],
    )
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
        return render(request, "analyzer/index.html")

    repo_url = request.POST.get("repo_url", "").strip()
    if not repo_url:
        return render(
            request,
            "analyzer/index.html",
            {"error": "Please enter a GitHub repository URL.", "repo_url": repo_url},
        )

    try:
        md_report, html_report = _render_markdown_report(repo_url)
        _cache_report(request, repo_url, html_report, md_report)
        return render(
            request,
            "analyzer/index.html",
            {"report": html_report, "repo_url": repo_url},
        )
    except GitHubAPIError as exc:
        return render(
            request,
            "analyzer/index.html",
            {"error": str(exc), "repo_url": repo_url},
        )
    except Exception as exc:
        return render(
            request,
            "analyzer/index.html",
            {
                "error": f"Analysis failed: {exc}",
                "repo_url": repo_url,
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
                {"error": str(exc), "repo_url": repo_url},
            )
        except Exception as exc:
            return render(
                request,
                "analyzer/index.html",
                {
                    "error": f"PDF export failed: {exc}",
                    "repo_url": repo_url,
                },
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
            {
                "error": f"PDF export failed: {exc}.{hint}",
                "repo_url": repo_url,
                "report": html_report,
            },
        )

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{_pdf_filename(repo_url)}"'
    return response
