import io
import re
from datetime import datetime

import markdown
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from xhtml2pdf import pisa

from analyzer.github_api import GitHubAPIError
from .crew import run_analysis


def index(request):
    return render(request, "analyzer/index.html")


def _render_markdown_report(repo_url: str) -> tuple[str, str]:
    """
    Run the analysis and return (markdown_report, html_report).
    Shared between HTML view and PDF download so the content matches.
    """
    md_report = run_analysis(repo_url)
    html_report = markdown.markdown(
        md_report,
        extensions=["tables", "fenced_code", "nl2br"],
    )
    return md_report, html_report


def _strip_first_h1(html_report: str) -> str:
    """Remove the report's first H1 to avoid duplicate PDF titles."""
    return re.sub(r"<h1>.*?</h1>", "", html_report, count=1, flags=re.DOTALL)


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
        _md, html_report = _render_markdown_report(repo_url)
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
    """
    Generate a PDF version of the latest report for a given repo URL.
    Re-runs analysis so the user can download even on a fresh page load.
    """
    repo_url = request.GET.get("repo_url", "").strip()
    if not repo_url:
        return redirect("index")

    try:
        md_report, html_report = _render_markdown_report(repo_url)
    except GitHubAPIError as exc:
        # Redirect back to index with error
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

    # Wrap the report HTML inside a simpler PDF-friendly template
    pdf_html = render_to_string(
        "analyzer/report_pdf.html",
        {
            "repo_url": repo_url,
            "markdown_report": md_report,
            "report_html": _strip_first_h1(html_report),
            "generated_at": datetime.now().strftime("%d %b %Y, %I:%M %p"),
        },
    )

    result = io.BytesIO()
    pisa_status = pisa.CreatePDF(pdf_html, dest=result, encoding="utf-8")

    if pisa_status.err:
        return render(
            request,
            "analyzer/index.html",
            {
                "error": "Could not generate PDF for this report.",
                "repo_url": repo_url,
            },
        )

    filename = f"repoflow-report.pdf"
    response = HttpResponse(result.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
