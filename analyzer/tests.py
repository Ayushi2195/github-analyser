from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from analyzer.github_api import GitHubAPIError, fetch_best_practices_badge, fetch_osv_vulnerabilities, fetch_repo_snapshot, parse_repo_url
from analyzer.mongo_cache import cache_is_fresh, connect_mongo
from analyzer.views import _gallery_items, _render_markdown_report, download_pdf
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

    def test_best_practices_tries_fallback_queries_until_badge_found(self):
        calls = []

        class Response:
            ok = True

            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

        class Session:
            def get(self, url, params=None, timeout=None):
                calls.append(params)
                if len(calls) < 3:
                    return Response([])
                return Response([{
                    "repo_url": "https://github.com/django/django.git",
                    "badge_level": "silver",
                }])

        with patch("analyzer.github_api._session", return_value=Session()):
            badge = fetch_best_practices_badge("django", "django")

        self.assertEqual(calls[0], {"url": "https://github.com/django/django"})
        self.assertEqual(calls[1], {"url": "https://github.com/django/django.git"})
        self.assertEqual(calls[2], {"pq": "github.com/django/django"})
        self.assertTrue(badge["found"])
        self.assertEqual(badge["level"], "silver")

    def test_osv_uses_commit_body_and_15_second_timeout(self):
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
            fetch_osv_vulnerabilities("django", "django", "abc123")

        self.assertEqual(calls[0][0], "https://api.osv.dev/v1/query")
        self.assertEqual(calls[0][1], {"commit": "abc123"})
        self.assertEqual(calls[0][2], 15)

    def test_snapshot_queries_osv_with_default_branch_sha(self):
        calls = []

        def fake_get(path, params=None):
            if path == "/repos/django/django":
                return {
                    "name": "django",
                    "full_name": "django/django",
                    "default_branch": "main",
                    "license": {},
                }
            if path == "/repos/django/django/contents/":
                return []
            if path == "/repos/django/django/issues":
                return []
            if path == "/repos/django/django/pulls":
                return []
            if path == "/repos/django/django/branches":
                return [
                    {"name": "main", "protected": True, "commit": {"sha": "main-sha"}},
                    {"name": "dev", "protected": False, "commit": {"sha": "dev-sha"}},
                ]
            if path == "/repos/django/django/commits/main-sha":
                return {"commit": {"committer": {"date": "2026-06-01T00:00:00Z"}}}
            if path == "/repos/django/django/commits/dev-sha":
                return {"commit": {"committer": {"date": "2026-06-02T00:00:00Z"}}}
            return {}

        def fake_osv(owner, repo, commit_sha=None):
            calls.append((owner, repo, commit_sha))
            return {"available": True, "vulns": []}

        with patch("analyzer.github_api._snapshot_cache", {}), \
             patch("analyzer.github_api._get", side_effect=fake_get), \
             patch("analyzer.github_api.fetch_openssf_scorecard", return_value={"available": False}), \
             patch("analyzer.github_api.fetch_best_practices_badge", return_value={"found": False}), \
             patch("analyzer.github_api.fetch_security_insights", return_value={}), \
             patch("analyzer.github_api._search_total_count", return_value=0), \
             patch("analyzer.github_api.fetch_osv_vulnerabilities", side_effect=fake_osv):
            fetch_repo_snapshot("https://github.com/django/django")

        self.assertEqual(calls, [("django", "django", "main-sha")])

    def test_snapshot_builds_scorecard_fallback_when_api_missing(self):
        def fake_get(path, params=None):
            if path == "/repos/django/django":
                return {
                    "name": "django",
                    "full_name": "django/django",
                    "description": "A framework",
                    "default_branch": "main",
                    "license": {"spdx_id": "BSD-3-Clause"},
                }
            if path == "/repos/django/django/contents/":
                return [
                    {"name": ".github", "path": ".github", "type": "dir"},
                    {"name": "tests", "path": "tests", "type": "dir"},
                    {"name": "pyproject.toml", "path": "pyproject.toml", "type": "file"},
                    {"name": "SECURITY.md", "path": "SECURITY.md", "type": "file"},
                ]
            if path == "/repos/django/django/contents/.github":
                return [{"name": "workflows", "path": ".github/workflows", "type": "dir"}]
            if path == "/repos/django/django/contents/tests":
                return []
            if path == "/repos/django/django/issues":
                return []
            if path == "/repos/django/django/pulls":
                return []
            if path == "/repos/django/django/branches":
                return [{"name": "main", "protected": True, "commit": {"sha": "main-sha"}}]
            if path == "/repos/django/django/commits/main-sha":
                return {"commit": {"committer": {"date": "2026-06-01T00:00:00Z"}}}
            return {}

        with patch("analyzer.github_api._snapshot_cache", {}), \
             patch("analyzer.github_api._get", side_effect=fake_get), \
             patch("analyzer.github_api.fetch_openssf_scorecard", return_value={"available": False, "status_code": 404}), \
             patch("analyzer.github_api.fetch_best_practices_badge", return_value={"found": False}), \
             patch("analyzer.github_api.fetch_security_insights", return_value={"has_security_md": True}), \
             patch("analyzer.github_api._search_total_count", return_value=0), \
             patch("analyzer.github_api.fetch_osv_vulnerabilities", return_value={"available": True, "vulns": []}):
            snapshot = fetch_repo_snapshot("https://github.com/django/django")

        scorecard = snapshot["openssf_scorecard"]
        self.assertFalse(scorecard["available"])
        self.assertEqual(snapshot["repo_flow_security_checks"]["source"], "repoflow-fallback")
        self.assertIsInstance(snapshot["repo_flow_security_checks"]["score"], float)
        self.assertGreater(len(snapshot["repo_flow_security_checks"]["checks"]), 0)

    def test_snapshot_fetches_default_branch_sha_when_not_sampled(self):
        paths = []
        calls = []

        def fake_get(path, params=None):
            paths.append(path)
            if path == "/repos/django/django":
                return {
                    "name": "django",
                    "full_name": "django/django",
                    "default_branch": "release/stable",
                    "license": {},
                }
            if path == "/repos/django/django/contents/":
                return []
            if path == "/repos/django/django/issues":
                return []
            if path == "/repos/django/django/pulls":
                return []
            if path == "/repos/django/django/branches":
                return [{"name": "dev", "protected": False, "commit": {"sha": "dev-sha"}}]
            if path == "/repos/django/django/branches/release%2Fstable":
                return {"name": "release/stable", "commit": {"sha": "stable-sha"}}
            if path == "/repos/django/django/commits/dev-sha":
                return {"commit": {"committer": {"date": "2026-06-02T00:00:00Z"}}}
            return {}

        def fake_osv(owner, repo, commit_sha=None):
            calls.append((owner, repo, commit_sha))
            return {"available": True, "vulns": []}

        with patch("analyzer.github_api._snapshot_cache", {}), \
             patch("analyzer.github_api._get", side_effect=fake_get), \
             patch("analyzer.github_api.fetch_openssf_scorecard", return_value={"available": False}), \
             patch("analyzer.github_api.fetch_best_practices_badge", return_value={"found": False}), \
             patch("analyzer.github_api.fetch_security_insights", return_value={}), \
             patch("analyzer.github_api._search_total_count", return_value=0), \
             patch("analyzer.github_api.fetch_osv_vulnerabilities", side_effect=fake_osv):
            fetch_repo_snapshot("https://github.com/django/django")

        self.assertIn("/repos/django/django/branches/release%2Fstable", paths)
        self.assertEqual(calls, [("django", "django", "stable-sha")])


class AnalysisCacheTests(SimpleTestCase):
    def test_connect_mongo_uses_production_timeout_settings(self):
        captured = {}

        def fake_connect(**kwargs):
            captured.update(kwargs)

        class Connection:
            class Admin:
                @staticmethod
                def command(name):
                    return {"ok": 1}

            admin = Admin()

        with patch.dict("os.environ", {"MONGO_URI": "mongodb://localhost:27017/github-analyser"}), \
             patch("analyzer.mongo_cache._CONNECTED_URI", None), \
             patch("analyzer.mongo_cache.get_connection", side_effect=[Exception("none"), Connection()]), \
             patch("analyzer.mongo_cache.disconnect"), \
             patch("analyzer.mongo_cache.connect", side_effect=fake_connect):
            connect_mongo()

        self.assertEqual(captured["serverSelectionTimeoutMS"], 30000)

    def test_gallery_excludes_django_and_prefers_curl(self):
        from types import SimpleNamespace
        from datetime import datetime, timezone

        django_analysis = SimpleNamespace(
            owner="django",
            repo_name="django",
            repo_url="https://github.com/django/django",
            openssf_sections={"scorecard": {"score": 9.0}},
            primary_language="Python",
            tech_stack=["Django"],
            stars=200000,
            analyzed_at=datetime.now(timezone.utc),
        )
        curl_analysis = SimpleNamespace(
            owner="curl",
            repo_name="curl",
            repo_url="https://github.com/curl/curl",
            openssf_sections={"scorecard": {"score": 7.1}},
            primary_language="C",
            tech_stack=["C"],
            stars=80000,
            analyzed_at=datetime.now(timezone.utc),
        )
        other_analysis = SimpleNamespace(
            owner="example",
            repo_name="example",
            repo_url="https://github.com/example/example",
            openssf_sections={"scorecard": {"score": 6.5}},
            primary_language="Python",
            tech_stack=["Python"],
            stars=1000,
            analyzed_at=datetime.now(timezone.utc),
        )

        def fake_safe_cached_analyses(limit=5, is_featured=None):
            if is_featured is False:
                return [django_analysis, curl_analysis, other_analysis]
            return []

        with patch("analyzer.views.safe_cached_analyses", side_effect=fake_safe_cached_analyses):
            items = _gallery_items()

        self.assertTrue(all(item["full_name"] != "django/django" for item in items))
        self.assertTrue(any(item["full_name"] == "curl/curl" for item in items))
        self.assertEqual(items[0]["full_name"], "curl/curl")

    def test_analysis_younger_than_24_hours_is_fresh(self):
        cached = SimpleNamespace(analyzed_at=datetime.now(timezone.utc) - timedelta(hours=23))
        self.assertTrue(cache_is_fresh(cached))

    def test_analysis_older_than_24_hours_is_stale(self):
        cached = SimpleNamespace(analyzed_at=datetime.now(timezone.utc) - timedelta(hours=25))
        self.assertFalse(cache_is_fresh(cached))

    def test_rendered_report_does_not_save_user_analysis_to_mongodb(self):
        result = {
            "markdown": "# RepoFlow\n\nReport body",
            "snapshot": {"meta": {}, "issues": [], "pull_requests": [], "branches": []},
            "health": {},
            "sections": {},
        }

        with patch("analyzer.views.get_cached_analysis", return_value=None), \
             patch("analyzer.views.run_analysis_result", return_value=result):
            md_report, html_report = _render_markdown_report("https://github.com/django/django")

        self.assertIn("Report body", md_report)
        self.assertIn("<h1>RepoFlow</h1>", html_report)

    def test_download_pdf_returns_browserless_pdf_bytes(self):
        request = RequestFactory().get("/download/", {"repo_url": "https://github.com/django/django"})

        with patch("analyzer.views.get_cached_analysis", return_value=None), \
             patch("analyzer.views._render_markdown_report", return_value=("# RepoFlow", "<h1>RepoFlow</h1>")), \
             patch("analyzer.views._browserless_pdf_bytes", return_value=b"%PDF-test") as browserless:
            response = download_pdf(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="repoflow-report.pdf"')
        self.assertEqual(response.content, b"%PDF-test")
        self.assertTrue(browserless.called)


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
        self.assertIn("### Key Files and Folders", report)
        self.assertIn("<strong>student/demo</strong>", report)
        self.assertIn("**`README.md` (file):**", report)
        self.assertIn("Django web framework", report)
        self.assertIn("Verified Tech Stack", report)
        self.assertNotIn("```text", report)
        self.assertNotIn("├──", report)
        self.assertNotIn("Repository root item", report)
        self.assertNotIn("可能", report)

    def test_structure_tree_uses_snapshot_annotations(self):
        snapshot = {
            "repo": "demo",
            "meta": {"full_name": "student/demo", "language": "Python", "default_branch": "main"},
            "files": [
                {
                    "name": "api",
                    "path": "api",
                    "type": "dir",
                    "annotation": "API layer",
                    "children": [
                        {
                            "name": "routes",
                            "path": "api/routes",
                            "type": "dir",
                            "annotation": "API endpoints",
                        }
                    ],
                },
                {
                    "name": "requirements.txt",
                    "path": "requirements.txt",
                    "type": "file",
                    "annotation": "Python dependencies",
                    "children": [],
                },
            ],
        }
        report = build_structure_section(snapshot, "")
        self.assertIn("**`api` (dir):**", report)
        self.assertIn("Visible entries include `routes`", report)
        self.assertIn("**`requirements.txt` (file):** Python dependency list.", report)

    def test_structure_tree_uses_readme_and_source_context(self):
        snapshot = {
            "repo": "demo",
            "meta": {
                "full_name": "student/demo",
                "language": "Python",
                "description": "FastAPI service with React dashboard",
                "default_branch": "main",
            },
            "files": [
                {
                    "name": "README.md",
                    "path": "README.md",
                    "type": "file",
                    "content_preview": "FastAPI backend with a React Vite frontend.",
                    "children": [],
                },
                {"name": "api", "path": "api", "type": "dir", "children": []},
                {
                    "name": "app",
                    "path": "app",
                    "type": "dir",
                    "children": [
                        {"name": "components", "path": "app/components", "type": "dir"},
                    ],
                },
            ],
        }
        report = build_structure_section(snapshot, "")
        self.assertIn("**`api` (dir):**", report)
        self.assertIn("**`app` (dir):**", report)
        self.assertNotIn("├──", report)

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
        self.assertNotIn("RepoFlow sampled", report)

    def test_zero_issues_only_shows_external_tracker_message(self):
        snapshot = {
            "issues": [],
            "stats": {"open_issues_total": 0, "issues_sampled": 0},
        }
        report = build_good_first_issues_section(snapshot)
        self.assertIn("No open GitHub issues found", report)
        self.assertNotIn("RepoFlow sampled **0** of **0**", report)

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
            "openssf_scorecard": {"available": False, "status_code": 404},
            "repo_flow_security_checks": {
                "available": True,
                "score": 7.2,
                "checks": [
                    {"name": "Branch-Protection", "score": 10, "reason": "Protected branches found."},
                ],
            },
        })
        self.assertIn("OpenSSF Scorecard Not Available, this repository has not been scanned by OpenSSF.", report)
        self.assertIn("RepoFlow Security Checks", report)
        self.assertIn("Branch-Protection", report)

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
