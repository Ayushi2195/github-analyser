import os

os.environ.setdefault("CREWAI_DISABLE_CACHE", "true")
os.environ.setdefault("LITELLM_DISABLE_CACHE", "true")
os.environ.setdefault("LITELLM_CACHE", "false")

from crewai import Agent, LLM

from analyzer.tools import (
    get_repo_branches,
    get_repo_issues,
    get_repo_pull_requests,
    get_repo_structure,
)


def _llm() -> LLM:
    return LLM(
        model="groq/llama-3.3-70b-versatile",
        api_key=os.environ.get("GROQ_API_KEY"),
    )


def structure_agent() -> Agent:
    return Agent(
        role="Repository Structure Analyzer",
        goal="Produce detailed, file-by-file documentation of repository layout and stats.",
        backstory=(
            "Senior architect who writes thorough onboarding docs. "
            "You never give vague summaries — you cite every root path and metadata field."
        ),
        tools=[get_repo_structure],
        llm=_llm(),
        cache=False,
        verbose=True,
    )


def issue_agent() -> Agent:
    return Agent(
        role="Issue Triage Analyst",
        goal="List every open issue grouped by labels with authors and links.",
        backstory=(
            "QA lead who writes release notes. You include every issue number, "
            "title, author, and label group — nothing is omitted."
        ),
        tools=[get_repo_issues],
        llm=_llm(),
        cache=False,
        verbose=True,
    )


def pull_request_agent() -> Agent:
    return Agent(
        role="Pull Request Reviewer",
        goal="Document each open PR with author, branches, URL, and intent.",
        backstory=(
            "Staff engineer who writes detailed code review summaries. "
            "You analyze every PR individually with branch flow and purpose."
        ),
        tools=[get_repo_pull_requests],
        llm=_llm(),
        cache=False,
        verbose=True,
    )


def branch_agent() -> Agent:
    return Agent(
        role="Branch Workflow Specialist",
        goal="Classify every branch and recommend git workflow improvements.",
        backstory=(
            "DevOps engineer who audits branch sprawl. "
            "You name every branch and explain main vs feature vs release vs protected."
        ),
        tools=[get_repo_branches],
        llm=_llm(),
        cache=False,
        verbose=True,
    )
