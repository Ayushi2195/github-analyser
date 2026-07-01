from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from analyzer.github_api import GitHubAPIError, fetch_best_practices_badge, fetch_osv_vulnerabilities, parse_repo_url
from analyzer.mongo_cache import cache_is_fresh
from analyzer.report_builder import (
    build_branch_snapshot,
    build_branches_section,
    build_good_first_issues_section,
    build_recommendations_section,
    build_security_section,
    build_security_insights_section,
    build_structure_section,
    build_vulnerabilities_section,
)


class GitHubURLTests(SimpleTestCase):
    def test_parse_valid_url(self):
        owner, repo = parse_repo_url("https://github.com/django/django")
        self.assertEqual(owner, "django")
        self.assertEqual(repo, "django")

    def test_reject_invalid_url(self):
        with self.assertRaises(GitHubAPIError):
            parse_repo_url("https://gitlab.com/foo/bar")

    def test_best_practices_uses_url_query_parameter(self):
        calls = []

        class Response:
            ok = True

            def json(self):
                return []

        class Session:
            def get(self, url, params=None, timeout=None):
                calls.append((url, params, timeout))
                return Response()

        with patch("analyzer.github_api._session", return_value=Session()):
            fetch_best_practices_badge("django", "django")

        self.assertEqual(calls[0][1], {"url": "https://github.com/django/django"})
        self.assertNotIn("pq", calls[0][1])

    def test_osv_uses_repo_url_body_and_15_second_timeout(self):
        calls = []

        class Response:
            status_code = 200
            ok = True

            def json(self):
                return {"vulns": []}

        class Session:
            def post(self, url, json=None, headers=None, timeout=None):
                calls.append((url, json, timeout))
                return Response()

        with patch("analyzer.github_api._session", return_value=Session()):
            fetch_osv_vulnerabilities("django", "django")

        self.assertEqual(calls[0][0], "https://api.osv.dev/v1/query")
        self.assertEqual(calls[0][1], {"url": "https://github.com/django/django"})
        self.assertEqual(calls[0][2], 15)


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
                {"name": "random.bin", "type": "file", "children": []},
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
        self.assertIn("```text", report)
        self.assertIn("student/demo/", report)
        self.assertIn("Django web framework", report)
        self.assertIn("Verified Tech Stack", report)
        self.assertNotIn("Repository root item", report)
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
        report = build_good_first_issues_section(snapshot)
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

    def test_protected_branches_are_summarized(self):
        snapshot = {
            "meta": {"default_branch": "main"},
            "stats": {"branches_sampled": 3},
            "pull_requests": [],
            "branches": [
                {"name": "main", "protected": True},
                {"name": "release", "protected": True},
                {"name": "scratch", "protected": False},
            ],
        }
        report = build_branches_section(snapshot)
        self.assertIn("2 of 3 sampled branches are protected", report)
        self.assertIn("Unprotected sampled branches", report)
        self.assertIn("scratch", report)
        self.assertNotIn("main** — protected", report)

    def test_recommendations_and_branch_snapshot_are_generated(self):
        snapshot = {
            "meta": {"default_branch": "main"},
            "issues": [],
            "pull_requests": [],
            "branches": [{"name": "main", "protected": False}],
            "stats": {"open_issues_total": 0, "open_prs_total": 0},
            "security_insights": {},
            "best_practices_badge": {"found": False},
            "osv_vulnerabilities": {"vulns": []},
        }
        recommendations = build_recommendations_section(snapshot)
        branch_snapshot = build_branch_snapshot(snapshot)
        self.assertIn("Recommendations", recommendations)
        self.assertIn("SECURITY.md", recommendations)
        self.assertIn("branch-snapshot-card", branch_snapshot)


class SecurityReportTests(SimpleTestCase):
    def test_scorecard_404_is_graceful(self):
        report = build_security_section({
            "openssf_scorecard": {"available": False, "status_code": 404}
        })
        self.assertIn("OpenSSF Scorecard data not available", report)

    def test_scorecard_checks_include_score_reason_and_indicator(self):
        report = build_security_section({
            "openssf_scorecard": {
                "available": True,
                "score": 8.4,
                "checks": [
                    {"name": "Maintained", "score": 10, "reason": "30 commits found"},
                    {"name": "Branch-Protection", "score": 0, "reason": "No protection found"},
                ],
            }
        })
        self.assertIn("8.4/10", report)
        self.assertIn("Pass", report)
        self.assertIn("Maintained", report)
        self.assertIn("Fail", report)
        self.assertIn("Branch-Protection", report)
        self.assertIn("No protection found", report)

    def test_scorecard_translates_common_raw_findings(self):
        report = build_security_section({
            "openssf_scorecard": {
                "available": True,
                "score": 5.1,
                "checks": [
                    {
                        "name": "Branch-Protection",
                        "score": 0,
                        "reason": "internal error: github tokens can't read classic branch protection rules",
                    },
                    {
                        "name": "Pinned-Dependencies",
                        "score": 0,
                        "reason": "dependency not pinned by hash",
                    },
                    {
                        "name": "Signed-Releases",
                        "score": 0,
                        "reason": "no releases found",
                    },
                ],
            }
        })
        self.assertIn("classic branch protection", report)
        self.assertIn("stricter security", report)
        self.assertIn("supply-chain risk", report)
        self.assertIn("may publish through npm", report)
        self.assertNotIn("internal error", report.lower())

    def test_best_practices_falls_back_to_scorecard_check(self):
        report = build_security_section({
            "openssf_scorecard": {
                "available": True,
                "score": 7,
                "checks": [
                    {"name": "CII-Best-Practices", "score": 6, "reason": "Badge criteria met"},
                ],
            },
            "best_practices_badge": {"found": False},
        })
        self.assertIn("Best Practices signal found in Scorecard", report)
        self.assertIn("Passing", report)

    def test_security_section_includes_best_practices_badge(self):
        report = build_security_section({
            "openssf_scorecard": {"available": False, "status_code": 404},
            "best_practices_badge": {"found": True, "level": "silver"},
            "security_insights": {},
        })
        self.assertIn("OpenSSF Best Practices Badge", report)
        self.assertIn("Silver", report)

    def test_security_insights_recommends_security_policy_when_missing(self):
        report = build_security_insights_section({
            "security_insights": {
                "has_security_insights": False,
                "has_security_md": False,
                "has_github_security_md": False,
            }
        })
        self.assertIn("SECURITY-INSIGHTS.yml/yaml", report)
        self.assertIn("Missing", report)
        self.assertIn("Add a SECURITY.md file", report)

    def test_security_insights_shows_checks_when_present(self):
        report = build_security_insights_section({
            "security_insights": {
                "has_security_insights": True,
                "has_security_md": False,
                "has_github_security_md": True,
            }
        })
        self.assertIn("SECURITY-INSIGHTS.yml/yaml", report)
        self.assertIn(".github/SECURITY.md", report)
        self.assertIn("Present", report)
        self.assertNotIn("Add a SECURITY.md file", report)

    def test_osv_no_vulnerabilities_message(self):
        report = build_vulnerabilities_section({"osv_vulnerabilities": {"vulns": []}})
        self.assertIn("No known vulnerabilities found", report)
        self.assertIn("clean vulnerability record", report)

    def test_osv_raw_api_errors_are_hidden(self):
        report = build_vulnerabilities_section({
            "osv_vulnerabilities": {
                "available": False,
                "vulns": [],
                "error": '{"code":3,"message":"Invalid query."}',
            }
        })
        self.assertIn("OSV scan could not be completed", report)
        self.assertIn("try again later", report)
        self.assertNotIn("Invalid query", report)
        self.assertNotIn('"code"', report)

    def test_osv_vulnerability_lists_id_severity_and_summary(self):
        report = build_vulnerabilities_section({
            "osv_vulnerabilities": {
                "available": True,
                "vulns": [{
                    "id": "GHSA-test",
                    "aliases": ["CVE-2026-1234"],
                    "summary": "Example vulnerability",
                    "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N"}],
                }],
            }
        })
        self.assertIn("CVE-2026-1234", report)
        self.assertIn("CVSS_V3", report)
        self.assertIn("Example vulnerability", report)
