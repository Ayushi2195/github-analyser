from django.test import SimpleTestCase

from analyzer.github_api import GitHubAPIError, parse_repo_url
from analyzer.health import compute_health_score


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
