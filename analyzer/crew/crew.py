import os
import json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from crewai import Crew, Agent, Task, Process, LLM
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json"
}

def get_session():
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    return session

def parse_repo_url(repo_url: str):
    parts = repo_url.rstrip("/").split("/")
    return parts[-2], parts[-1]

def fetch_github_data(repo_url: str) -> dict:
    owner, repo = parse_repo_url(repo_url)
    base = f"https://api.github.com/repos/{owner}/{repo}"
    session = get_session()

    meta = session.get(base, headers=HEADERS, timeout=15).json()
    contents = session.get(f"{base}/contents/", headers=HEADERS, timeout=15).json()
    issues_raw = session.get(f"{base}/issues", headers=HEADERS, params={"state": "open", "per_page": 10}, timeout=15).json()
    prs_raw = session.get(f"{base}/pulls", headers=HEADERS, params={"state": "open", "per_page": 10}, timeout=15).json()
    branches_raw = session.get(f"{base}/branches", headers=HEADERS, params={"per_page": 20}, timeout=15).json()

    files = [f["name"] for f in contents] if isinstance(contents, list) else []
    issues = [
        {"number": i.get("number"), "title": i.get("title"),
         "labels": [l["name"] for l in i.get("labels", [])],
         "user": i.get("user", {}).get("login")}
        for i in (issues_raw if isinstance(issues_raw, list) else [])
        if "pull_request" not in i
    ]
    prs = [
        {"number": p.get("number"), "title": p.get("title"),
         "user": p.get("user", {}).get("login"),
         "head": p.get("head", {}).get("ref"),
         "base": p.get("base", {}).get("ref")}
        for p in (prs_raw if isinstance(prs_raw, list) else [])
    ]
    branches = [
        {"name": b["name"], "protected": b.get("protected", False)}
        for b in (branches_raw if isinstance(branches_raw, list) else [])
    ]

    return {
        "meta": {
            "name": meta.get("name"),
            "description": meta.get("description"),
            "language": meta.get("language"),
            "stars": meta.get("stargazers_count"),
            "forks": meta.get("forks_count"),
            "default_branch": meta.get("default_branch"),
            "topics": meta.get("topics", []),
        },
        "files": files,
        "issues": issues,
        "prs": prs,
        "branches": branches,
    }


def run_analysis(repo_url: str) -> str:
    llm = LLM(
        model="groq/llama-3.3-70b-versatile",
        api_key=os.environ.get("GROQ_API_KEY")
    )

    try:
        data = fetch_github_data(repo_url)
    except Exception as e:
        return f"Error fetching GitHub data: {str(e)}"

    meta_str = json.dumps(data["meta"], indent=2)
    files_str = json.dumps(data["files"], indent=2)
    issues_str = json.dumps(data["issues"], indent=2)
    prs_str = json.dumps(data["prs"], indent=2)
    branches_str = json.dumps(data["branches"], indent=2)

    a1 = Agent(
        role="Repository Structure Analyzer",
        goal="Analyze and document the repository structure",
        backstory="Expert software architect who understands codebases at a glance.",
        llm=llm, verbose=True
    )
    t1 = Task(
        description=f"""Analyze this GitHub repository and write a detailed Markdown report about its structure.

Repository metadata:
{meta_str}

Root files and folders:
{files_str}

Write a clear Markdown section with headings covering: project overview, tech stack, key files, and repository stats.""",
        expected_output="Markdown report section about repository structure.",
        agent=a1,
        context=[]
    )

    a2 = Agent(
        role="Issue Analyzer",
        goal="Summarize open issues clearly",
        backstory="QA engineer skilled at triaging bugs and feature requests.",
        llm=llm, verbose=True
    )
    t2 = Task(
        description=f"""Analyze these open GitHub issues and write a Markdown report summarizing them.

Open Issues:
{issues_str}

Group them by type (bug, feature, etc.) if labels are present. If there are no issues, say so.""",
        expected_output="Markdown report section about open issues.",
        agent=a2,
        context=[]
    )

    a3 = Agent(
        role="Pull Request Analyst",
        goal="Review and summarize pull requests",
        backstory="Senior developer experienced in code review workflows.",
        llm=llm, verbose=True
    )
    t3 = Task(
        description=f"""Analyze these open pull requests and write a Markdown report.

Open Pull Requests:
{prs_str}

Summarize each PR, who submitted it, and what branch it targets. If no PRs, say so.""",
        expected_output="Markdown report section about pull requests.",
        agent=a3,
        context=[]
    )

    a4 = Agent(
        role="Branch Tracker",
        goal="Document all active branches",
        backstory="DevOps specialist who tracks development workflows.",
        llm=llm, verbose=True
    )
    t4 = Task(
        description=f"""Analyze these branches and write a Markdown report.

Branches:
{branches_str}

Identify the main branch, feature branches, release branches, and any protected branches.""",
        expected_output="Markdown report section about branches.",
        agent=a4,
        context=[]
    )

    crew = Crew(
        agents=[a1, a2, a3, a4],
        tasks=[t1, t2, t3, t4],
        process=Process.sequential,
        verbose=True
    )

    crew.kickoff()

    full_report = f"""# 📊 GitHub Repository Analysis Report

---

## 🗂️ Repository Structure

{t1.output.raw if t1.output else 'No data'}

---

## 🐛 Open Issues

{t2.output.raw if t2.output else 'No data'}

---

## 🔀 Pull Requests

{t3.output.raw if t3.output else 'No data'}

---

## 🌿 Branch Analysis

{t4.output.raw if t4.output else 'No data'}
"""
    return full_report