# GitHub Repository Analyzer

Django web app that analyzes public GitHub repositories using a **multi-agent CrewAI workflow** and **CrewAI tools** (GitHub REST API).

## Architecture

```
Browser → Django views → Crew (4 agents) → CrewAI tools → github_api.py → GitHub REST API
                              ↓
                    health.py (deterministic score, no LLM)
```

| Layer | File | Responsibility |
|-------|------|----------------|
| UI | `analyzer/views.py`, `templates/` | Form, render HTML report |
| Orchestration | `analyzer/crew/crew.py` | Run sequential agent workflow |
| Agents | `analyzer/crew/agents.py` | One agent per domain (structure, issues, PRs, branches) |
| Tasks | `analyzer/crew/tasks.py` | Prompts that force tool use |
| Tools | `analyzer/tools/github_tools.py` | CrewAI `@tool` wrappers |
| Data | `analyzer/github_api.py` | GitHub API only — testable without AI |
| Metrics | `analyzer/health.py` | Rule-based health score |

## Setup

```bash
cd github-analyser
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# Edit .env — set GROQ_API_KEY (required)
python manage.py runserver
```

Open http://127.0.0.1:8000/ and try `https://github.com/django/django`.

### PDF export

Reports download as PDF through the **Browserless API**, so deployment hosts do not need local Chromium or Playwright.
Set `BROWSERLESS_API_TOKEN` in your environment before using PDF export.

## Tests

```bash
python manage.py test analyzer
```

## Environment

| Variable | Required | Purpose |
|----------|----------|---------|
| `GROQ_API_KEY` | Yes | LLM for CrewAI agents |
| `GITHUB_PERSONAL_ACCESS_TOKEN` | No | Higher GitHub API rate limits |
| `BROWSERLESS_API_TOKEN` | Yes for PDF | Browserless PDF generation |

## Interview prep

Be ready to explain:

1. Why tools exist (agents must not invent issue/PR data).
2. Why four agents vs one prompt (specialized prompts + tools per domain).
3. What `health.py` does without an LLM.
4. How snapshot caching avoids 4× duplicate API calls during one analysis.
