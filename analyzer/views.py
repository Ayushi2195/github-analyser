import markdown
from django.shortcuts import render

from analyzer.github_api import GitHubAPIError
from .crew import run_analysis


def index(request):
    return render(request, "analyzer/index.html")


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
        md_report = run_analysis(repo_url)
        html_report = markdown.markdown(
            md_report,
            extensions=["tables", "fenced_code", "nl2br"],
        )
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
