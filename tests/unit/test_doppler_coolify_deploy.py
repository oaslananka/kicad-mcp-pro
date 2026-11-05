"""Offline contract tests for Doppler secret injection and Coolify deploy guards."""

from __future__ import annotations

import json
import sys
import unittest
import urllib.error
from pathlib import Path
from typing import Any

EXAMPLE_SERVICE_VALUE = "nonsecret-stub"

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import cloud_deploy as cloud  # noqa: E402
import doppler_secret as secret  # noqa: E402

SHA = "a" * 40
OTHER = "b" * 40
UUID = "gd6kdgzjuukp2lbwedos4u9k"


class FakeResponse:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return False

    def read(self, _: object = None) -> bytes:
        return json.dumps(self.data).encode("utf-8")


class SecretContracts(unittest.TestCase):
    def test_protected_main_reader_fetches_single_key(self) -> None:
        requests = []

        def fake_open(request, timeout):
            self.assertEqual(timeout, 12)
            requests.append(request)
            return FakeResponse({"value": {"computed": "fixture-value"}})

        result = secret.get_secret(
            "COOLIFY_API_TOKEN", token=EXAMPLE_SERVICE_VALUE, opener=fake_open
        )
        self.assertEqual(result, "fixture-value")
        self.assertEqual(len(requests), 1)
        self.assertIn("config=main", requests[0].full_url)
        self.assertIn("name=COOLIFY_API_TOKEN", requests[0].full_url)

    def test_reader_rejects_every_other_config(self) -> None:
        for wrong in ("ci", "deploy", "release", "gui-signing", "prd_cloud", "live-eval"):
            with self.assertRaisesRegex(secret.SecretError, "UNEXPECTED_DOPPLER_SECRET_SCOPE"):
                secret.get_secret("SONAR_TOKEN", token=EXAMPLE_SERVICE_VALUE, config=wrong)

    def test_reader_rejects_unresolved_empty_and_log_injection(self) -> None:
        for bad in ("", "x\r", "abc\nline", "$" + "{UNRESOLVED}"):

            def fake(_request, timeout, value=bad):
                return FakeResponse({"value": {"computed": value}})

            with self.assertRaises(secret.SecretError):
                secret.get_secret("COOLIFY_API_TOKEN", token=EXAMPLE_SERVICE_VALUE, opener=fake)

    def test_reader_denies_redirects_and_hides_http_error(self) -> None:
        self.assertIsNone(
            secret.NoRedirect().redirect_request(
                object(), None, 302, "Found", {}, "https://untrusted.invalid"
            )
        )

        def failure(_request, timeout):
            raise urllib.error.HTTPError(
                "https://unused", 401, "response-contains-secret", {}, None
            )

        with self.assertRaisesRegex(secret.SecretError, "^DOPPLER_HTTP_401$"):
            secret.get_secret("COOLIFY_API_TOKEN", token=EXAMPLE_SERVICE_VALUE, opener=failure)


class LocalEntryContracts(unittest.TestCase):
    def test_dispatch_does_not_supply_secrets_to_pr_jobs(self) -> None:
        package = json.loads((SCRIPTS.parent / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(
            package["scripts"]["deploy"],
            "gh workflow run cloud-deploy.yml --repo oaslananka/kicad-mcp-pro --ref main",
        )

    def test_bash_sync_has_explicit_scope_and_opt_in_apply(self) -> None:
        source = (SCRIPTS / "sync_doppler_github.sh").read_text(encoding="utf-8")
        self.assertIn('config="main"', source)
        self.assertIn('case "$1" in', source)
        self.assertIn("[[ $# -eq 1 ]]", source)
        self.assertIn("GITHUB_ACTIONS", source)
        self.assertIn("gh secret set", source)


class DeployContracts(unittest.TestCase):
    @staticmethod
    def ci_get(url: str, token: str | None = None) -> dict[str, Any]:
        if url.endswith("/branches/main"):
            return {"commit": {"sha": SHA}}
        if "/runs?" in url:
            return {
                "workflow_runs": [
                    {
                        "head_sha": SHA,
                        "head_branch": "main",
                        "event": "push",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ]
            }
        raise AssertionError("Unexpected API: " + url)

    def test_ci_requires_exact_successful_push_main(self) -> None:
        cloud.require_successful_ci(SHA, "github", self.ci_get)
        with self.assertRaisesRegex(cloud.DeployError, "^CI_IDENTITY_MISSING$"):
            cloud.require_successful_ci("invalid", "github", self.ci_get)

        def wrong_run(url, token=None):
            if "/runs?" in url:
                return {
                    "workflow_runs": [
                        {
                            "head_sha": OTHER,
                            "head_branch": "main",
                            "event": "push",
                            "status": "completed",
                            "conclusion": "success",
                        }
                    ]
                }
            return self.ci_get(url, token)

        with self.assertRaisesRegex(cloud.DeployError, "MAIN_CI_NOT_SUCCESSFUL"):
            cloud.require_successful_ci(SHA, "github", wrong_run)

    def test_cloud_ci_path_filtered_clean_main_is_accepted(self) -> None:
        def fake(url, token=None):
            if "/cloud-ci.yml/runs?" in url:
                return {
                    "workflow_runs": [
                        {
                            "head_sha": OTHER,
                            "head_branch": "main",
                            "event": "push",
                            "status": "completed",
                            "conclusion": "success",
                        }
                    ]
                }
            if "/compare/" in url:
                self.assertIn(OTHER + "..." + SHA, url)
                return {
                    "status": "ahead",
                    "files": [
                        {"filename": "docs/intro.md"},
                        {"filename": ".github/workflows/ci.yml"},
                    ],
                }
            return self.ci_get(url, token)

        cloud.require_successful_ci(SHA, "github", fake)

    def test_cloud_ci_path_filtered_changed_cloud_blocks(self) -> None:
        def fake(url, token=None):
            if "/cloud-ci.yml/runs?" in url:
                return {
                    "workflow_runs": [
                        {
                            "head_sha": OTHER,
                            "head_branch": "main",
                            "event": "push",
                            "status": "completed",
                            "conclusion": "success",
                        }
                    ]
                }
            if "/compare/" in url:
                return {"status": "ahead", "files": [{"filename": "apps/cloud/src/http.ts"}]}
            return self.ci_get(url, token)

        with self.assertRaisesRegex(cloud.DeployError, "CLOUD_CI_NOT_SUCCESSFUL_FOR_CHANGED_CODE"):
            cloud.require_successful_ci(SHA, "github", fake)

    def test_cloud_ci_nonancestor_and_truncated_diff_block(self) -> None:
        def build_getter(comparison: dict[str, Any]):
            def fake(url: str, token: str | None = None):
                if "/cloud-ci.yml/runs?" in url:
                    return {
                        "workflow_runs": [
                            {
                                "head_sha": OTHER,
                                "head_branch": "main",
                                "event": "push",
                                "status": "completed",
                                "conclusion": "success",
                            }
                        ]
                    }
                if "/compare/" in url:
                    return comparison
                return self.ci_get(url, token)

            return fake

        for comparison in (
            {"status": "diverged", "files": []},
            {"status": "ahead", "files": [{"filename": "docs/readme.md"}] * 300},
        ):
            getter = build_getter(comparison)
            with self.assertRaises(cloud.DeployError):
                cloud.require_successful_ci(SHA, "github", getter)

    def test_ci_rechecks_moving_main_branch(self) -> None:
        def stale(url, token=None):
            if url.endswith("/branches/main"):
                return {"commit": {"sha": OTHER}}
            return self.ci_get(url, token)

        with self.assertRaisesRegex(cloud.DeployError, "^MAIN_SHA_CHANGED$"):
            cloud.require_successful_ci(SHA, "github", stale)

    def test_coolify_wrong_target_or_autodeploy_is_denied(self) -> None:
        data = {
            "git_repository": cloud.REPOSITORY,
            "git_branch": "main",
            "build_pack": "dockercompose",
            "base_directory": "/apps/cloud",
            "docker_compose_location": "/compose.coolify.yml",
            "settings": {"is_auto_deploy_enabled": False, "is_preview_deployments_enabled": False},
        }

        def get(url, token=None):
            return data

        cloud.verify_application("https://coolify.example/api/v1", "token", UUID, get)
        data["git_repository"] = "other/repo"
        with self.assertRaisesRegex(cloud.DeployError, "COOLIFY_REPOSITORY_MISMATCH"):
            cloud.verify_application("https://coolify.example/api/v1", "token", UUID, get)
        data["git_repository"] = cloud.REPOSITORY
        data["settings"]["is_auto_deploy_enabled"] = True
        with self.assertRaisesRegex(cloud.DeployError, "COOLIFY_AUTO_DEPLOY_MUST_BE_OFF"):
            cloud.verify_application("https://coolify.example/api/v1", "token", UUID, get)

    def test_rejects_coolify_unexpected_compose_directory(self) -> None:
        data = {
            "git_repository": cloud.REPOSITORY,
            "git_branch": "main",
            "build_pack": "dockercompose",
            "base_directory": "/apps/other",
            "docker_compose_location": "/compose.coolify.yml",
            "settings": {"is_auto_deploy_enabled": False, "is_preview_deployments_enabled": False},
        }
        with self.assertRaisesRegex(cloud.DeployError, "COOLIFY_COMPOSE_LOCATION_MISMATCH"):
            cloud.verify_application(
                "https://coolify.example/api/v1", "token", UUID, lambda *_a, **_k: data
            )

    def test_rollback_rejects_ambiguous_or_partial_sha_tags(self) -> None:
        def get(url, token=None):
            return {"images": [{"tag": "app:" + OTHER + "-" + SHA, "is_current": False}]}

        with self.assertRaisesRegex(cloud.DeployError, "ROLLBACK_IMAGE_NOT_VERIFIED"):
            cloud.rollback_if_available(
                "https://coolify.example/api/v1",
                "token",
                UUID,
                SHA,
                "https://cloud.example",
                get,
                lambda *_a, **_k: None,
            )

    def test_coolify_poll_fails_on_wrong_commit(self) -> None:
        def fake(url, token=None):
            return {"status": "finished", "commit": OTHER}

        with self.assertRaisesRegex(cloud.DeployError, "COOLIFY_DEPLOYED_WRONG_COMMIT"):
            cloud.wait_deployment("https://coolify.example/api/v1", "token", UUID, SHA, fake)

    def test_coolify_poll_fails_on_deployment_error(self) -> None:
        def fake(url, token=None):
            return {"status": "failed", "commit": SHA}

        with self.assertRaisesRegex(cloud.DeployError, "COOLIFY_DEPLOYMENT_FAILED"):
            cloud.wait_deployment("https://coolify.example/api/v1", "token", UUID, SHA, fake)

    def test_coolify_poll_returns_only_exact_success(self) -> None:
        calls = []

        def fake(url, token=None):
            calls.append(url)
            return {"status": "finished", "commit": SHA}

        result = cloud.wait_deployment("https://coolify.example/api/v1", "token", UUID, SHA, fake)
        self.assertEqual(result["commit"], SHA)
        self.assertEqual(len(calls), 1)

    def test_public_health_checks_revision(self) -> None:
        def good(url, token=None):
            self.assertEqual(url, "https://cloud.example.com/health")
            return {"revision": SHA}

        cloud.health("https://cloud.example.com", SHA, good)
        with self.assertRaisesRegex(cloud.DeployError, "LIVE_REVISION_MISMATCH"):
            cloud.health("https://cloud.example.com", SHA, lambda url: {"revision": OTHER})

    def test_rejects_http_or_credential_urls(self) -> None:
        for bad in (
            "http://coolify.example",
            "https://user:password@coolify.example",
            "https://coolify.example/path",
        ):
            with self.assertRaises(cloud.DeployError):
                cloud.origin(bad)


if __name__ == "__main__":
    unittest.main()
