import os

from crewai import Agent, LLM

from analyzer.tools import get_repo_structure


def _llm() -> LLM:
    return LLM(
        model="llama-3.3-70b-versatile",
        provider="openai",
        api_key=os.environ.get("GROQ_API_KEY"),
        base_url="https://api.groq.com/openai/v1",
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
        verbose=False,
    )


def security_agent() -> Agent:
    return Agent(
        role="Security Posture Analyst",
        goal="Write a plain-English security summary for developers",
        backstory=(
            "Senior security engineer who explains complex security signals clearly to developers of all levels. "
            "You never use jargon without explaining it."
        ),
        llm=_llm(),
        cache=False,
        verbose=False,
    )
