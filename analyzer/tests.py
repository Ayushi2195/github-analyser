from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from django.test import SimpleTestCase

from analyzer.github_api import GitHubAPIError, parse_repo_url
from analyzer.health import compute_health_score
from analyzer.mongo_cache import cache_is_fresh
from analyzer.report_builder import (
    build_branch_snapshot,
    build_branches_section,
    build_executive_summary,
    build_issues_section,
    build_structure_section,
)


class GitHubURLTests(SimpleTestCase):
    def test_parse_valid_url(self):
        owner, repo = parse_repo_url("https://github.com/django/django")
        self.assertEqual(owner, "django")
        self.assertEqual(repo, "django")

    def test_reject_invalid_url(self):
        with self.assertRaises(GitHubAPIError):
            parse_repo_url("https://gitlab.com/foo/bar")


class HealthScoreTests(SimpleTestCase):
    def test_healthy_repo_scores_high(self):
        snapshot = {
            "meta": {"description": "Test", "license": "MIT"},
            "files": [{"name": "README.md", "type": "file"}],
            "issues": [],
            "pull_requests": [],
            "branches": [{"name": "main", "protected": True}],
        }
        result = compute_health_score(snapshot)
        self.assertGreaterEqual(result["score"], 80)

    def test_popular_repo_is_not_penalized_for_raw_issue_count(self):
        snapshot = {
            "meta": {"description": "Large project", "license": "BSD", "stars": 40000},
            "files": [{"name": "README.md", "type": "file"}],
            "issues": [{}] * 50,
            "pull_requests": [],
            "branches": [{"name": "main", "protected": False}],
            "stats": {"open_issues_total": 200},
        }
        result = compute_health_score(snapshot)
        issue_signal = next(
            item for item in result["breakdown"]
            if item["criterion"] == "Normalized issue load"
        )
        self.assertGreaterEqual(issue_signal["change"], 0)

    def test_issue_load_is_penalized_relative_to_small_community(self):
        snapshot = {
            "meta": {"description": "Small project", "license": "MIT", "stars": 10},
            "files": [{"name": "README.md", "type": "file"}],
            "issues": [{}] * 50,
            "pull_requests": [],
            "branches": [{"name": "main", "protected": False}],
            "stats": {"open_issues_total": 50},
        }
        result = compute_health_score(snapshot)
        issue_signal = next(
            item for item in result["breakdown"]
            if item["criterion"] == "Normalized issue load"
        )
        self.assertLess(issue_signal["change"], 0)

    def test_stale_prs_score_lower_than_recent_prs(self):
        now = datetime(2026, 6, 22, tzinfo=timezone.utc)
        base = {
            "meta": {"description": "Project", "license": "MIT", "stars": 100},
            "files": [{"name": "README.md", "type": "file"}],
            "issues": [],
            "branches": [{"name": "main", "protected": False}],
        }
        recent = {**base, "pull_requests": [{"created_at": "2026-06-15T00:00:00Z"}] * 10}
        stale = {**base, "pull_requests": [{"created_at": "2024-01-01T00:00:00Z"}] * 10}
        self.assertGreater(
            compute_health_score(recent, now=now)["score"],
            compute_health_score(stale, now=now)["score"],
        )

    def test_missing_branch_protection_never_deducts_points(self):
        snapshot = {
            "meta": {"description": "Student project", "license": "MIT"},
            "files": [{"name": "README.md", "type": "file"}],
            "issues": [],
            "pull_requests": [],
            "branches": [{"name": "main", "protected": False}],
        }
        result = compute_health_score(snapshot)
        protection = next(
            item for item in result["breakdown"]
            if item["criterion"] == "Branch protection"
        )
        self.assertEqual(protection["change"], 0)
        self.assertIn("no score deducted", " ".join(result["notes"]).lower())


class AnalysisCacheTests(SimpleTestCase):
    def test_analysis_younger_than_24_hours_is_fresh(self):
        cached = SimpleNamespace(analyzed_at=datetime.now(timezone.utc) - timedelta(hours=23))
        self.assertTrue(cache_is_fresh(cached))

    def test_analysis_older_than_24_hours_is_stale(self):
        cached = SimpleNamespace(analyzed_at=datetime.now(timezone.utc) - timedelta(hours=25))
        self.assertFalse(cache_is_fresh(cached))


class StudentReportTests(SimpleTestCase):
    def test_structure_separates_technology_from_configuration(self):
        snapshot = {
            "repo": "demo",
            "meta": {"full_name": "student/demo", "language": "Python", "default_branch": "main"},
            "files": [
                {"name": "README.md", "type": "file", "children": []},
                {
                    "name": "pyproject.toml",
                    "type": "file",
                    "children": [],
                    "content_preview": '[project]\ndependencies=["django>=5"]',
                },
                {"name": "gemini-extension.json", "type": "file", "children": []},
            ],
        }
        report = build_structure_section(snapshot, "可能 related to something")
        self.assertIn("Django web framework", report)
        self.assertIn("Configuration Files (Not Technologies)", report)
        self.assertNotIn("可能", report)

    def test_beginner_issue_has_reason_and_first_step(self):
        snapshot = {
            "issues": [{
                "number": 7,
                "title": "Fix README.md typo",
                "labels": ["good first issue", "documentation"],
                "body": "Correct the setup command in README.md.",
                "assignees": [],
                "comments": 0,
                "author": "student",
                "url": "https://example.test/issues/7",
            }],
            "stats": {"open_issues_total": 1, "issues_sampled": 1, "api_page_size": 100},
        }
        report = build_issues_section(snapshot)
        self.assertIn("Estimated difficulty", report)
        self.assertIn("documentation-only edit", report)

    def test_branch_guidance_uses_source_pr_and_commit_age(self):
        snapshot = {
            "meta": {"default_branch": "main"},
            "stats": {"branches_sampled": 3},
            "pull_requests": [{"head": "feat/current", "base": "main"}],
            "branches": [
                {"name": "main", "protected": True, "last_commit_date": "2026-06-18T00:00:00Z"},
                {"name": "feat/current", "protected": False, "last_commit_date": "2026-06-18T00:00:00Z"},
                {"name": "fix/abandoned", "protected": False, "last_commit_date": "2024-01-01T00:00:00Z"},
            ],
        }
        report = build_branches_section(snapshot)
        self.assertIn("source branch", report)
        self.assertIn("Likely abandoned", report)

    def test_assessment_cards_and_branch_snapshot_are_visual(self):
        snapshot = {
            "meta": {"default_branch": "main"},
            "issues": [],
            "pull_requests": [],
            "branches": [{"name": "main", "protected": False}],
            "stats": {"open_issues_total": 0, "open_prs_total": 0},
        }
        assessment = build_executive_summary(
            snapshot,
            {"score": 65, "label": "Needs attention", "notes": []},
        )
        branch_snapshot = build_branch_snapshot(snapshot)
        self.assertEqual(assessment.count("assessment-card assessment-"), 3)
        self.assertIn("Repository Assessment", assessment)
        self.assertIn("branch-snapshot-card", branch_snapshot)
