from django.test import SimpleTestCase

from analyzer.github_api import GitHubAPIError, parse_repo_url
from analyzer.health import compute_health_score
from analyzer.report_builder import (
    build_branches_section,
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
