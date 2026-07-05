import os

from crewai import Agent, LLM


def _llm() -> LLM:
    return LLM(
        model=os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant"),
        provider="openai",
        api_key=os.environ.get("GROQ_API_KEY"),
        base_url="https://api.groq.com/openai/v1",
        max_tokens=350,
        temperature=0.2,
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
        max_iter=1,
    )
