from __future__ import annotations

import os
from datetime import timedelta
from typing import Any

from django.utils import timezone
from mongoengine import (
    DateTimeField,
    DictField,
    Document,
    IntField,
    ListField,
    StringField,
    connect,
)
from mongoengine.connection import get_connection
from pymongo.errors import PyMongoError

from analyzer.github_api import GitHubAPIError, parse_repo_url


class RepoAnalysisCache(Document):
    repo_url = StringField(required=True, unique=True)
    owner = StringField()
    repo_name = StringField()

    analyzed_at = DateTimeField()

    health_score = IntField()
    health_label = StringField()
    health_signals = ListField(StringField())

    stars = IntField()
    forks = IntField()
    primary_language = StringField()

    open_issues_count = IntField()
    open_prs_count = IntField()

    tech_stack = ListField(StringField())

    report_sections = DictField()

    pdf_path = StringField()

    meta = {
        "collection": "analyzed-reports",
        "indexes": ["repo_url", "-analyzed_at", "primary_language", "health_label"],
    }


def connect_mongo() -> None:
    try:
        get_connection()
    except Exception:
        connect(host=os.environ.get("MONGO_URI", "mongodb://localhost:27017/github-analyser"))


def normalize_repo_url(repo_url: str) -> str:
    owner, repo = parse_repo_url(repo_url)
    return f"https://github.com/{owner}/{repo}"


def get_cached_analysis(repo_url: str) -> RepoAnalysisCache | None:
    connect_mongo()
    normalized_url = normalize_repo_url(repo_url)
    return RepoAnalysisCache.objects(repo_url=normalized_url).first()


def _tech_stack(snapshot: dict[str, Any]) -> list[str]:
    meta = snapshot.get("meta", {})
    stack = []
    for value in [meta.get("language"), *(meta.get("topics") or [])[:2], meta.get("license")]:
        if value and value not in stack:
            stack.append(value)
    return stack[:4]


def save_analysis_cache(
    repo_url: str,
    snapshot: dict[str, Any],
    health: dict[str, Any],
    report_sections: dict[str, str],
    pdf_path: str = "",
) -> RepoAnalysisCache:
    connect_mongo()
    normalized_url = normalize_repo_url(repo_url)
    meta = snapshot.get("meta", {})
    owner = snapshot.get("owner", "")
    repo = snapshot.get("repo", "")
    open_issues_count = len(snapshot.get("issues", []))
    open_prs_count = len(snapshot.get("pull_requests", []))
    analyzed_at = timezone.localtime(timezone.now()).replace(tzinfo=None)

    return RepoAnalysisCache.objects(repo_url=normalized_url).modify(
        upsert=True,
        new=True,
        set__repo_url=normalized_url,
        set__owner=owner,
        set__repo_name=repo,
        set__analyzed_at=analyzed_at,
        set__health_score=health.get("score", 0),
        set__health_label=health.get("label", "Unknown"),
        set__health_signals=health.get("notes", []),
        set__stars=meta.get("stars") or 0,
        set__forks=meta.get("forks") or 0,
        set__primary_language=meta.get("language") or "",
        set__open_issues_count=open_issues_count,
        set__open_prs_count=open_prs_count,
        set__tech_stack=_tech_stack(snapshot),
        set__report_sections=report_sections,
        set__pdf_path=pdf_path,
    )


def cached_markdown(cached: RepoAnalysisCache) -> str:
    sections = cached.report_sections or {}
    return sections.get("markdown", "")


def cached_html(cached: RepoAnalysisCache) -> str:
    sections = cached.report_sections or {}
    return sections.get("html", "")


def cached_branch_count(cached: RepoAnalysisCache) -> int:
    sections = cached.report_sections or {}
    return int(sections.get("branch_count") or 0)


def local_analyzed_at(cached: RepoAnalysisCache):
    analyzed_at = cached.analyzed_at
    if analyzed_at is None:
        return None
    if timezone.is_naive(analyzed_at):
        analyzed_at = timezone.make_aware(analyzed_at, timezone.get_current_timezone())
    return timezone.localtime(analyzed_at)


def analyzed_ago_label(cached: RepoAnalysisCache) -> str:
    analyzed_at = local_analyzed_at(cached)
    if analyzed_at is None:
        return "Not analyzed yet"

    delta = timezone.localtime(timezone.now()) - analyzed_at
    if delta < timedelta(minutes=1):
        return "just now"
    if delta < timedelta(hours=1):
        minutes = max(1, int(delta.total_seconds() // 60))
        return f"{minutes}m ago"
    if delta < timedelta(days=1):
        hours = max(1, int(delta.total_seconds() // 3600))
        return f"{hours}h ago"
    days = max(1, delta.days)
    return f"{days}d ago"


def analyzed_at_label(cached: RepoAnalysisCache) -> str:
    analyzed_at = local_analyzed_at(cached)
    if analyzed_at is None:
        return "Not analyzed yet"
    return analyzed_at.strftime("%d %b %Y, %I:%M %p")


def mongo_is_available() -> bool:
    try:
        connect_mongo()
        RepoAnalysisCache.objects.count()
        return True
    except (PyMongoError, OSError):
        return False


def safe_cached_analyses(limit: int = 5) -> list[RepoAnalysisCache]:
    try:
        connect_mongo()
        return list(RepoAnalysisCache.objects.order_by("-analyzed_at")[:limit])
    except (GitHubAPIError, PyMongoError, OSError):
        return []
