"""CI-gated Coolify Cloud deployment. No deployment happens at import or dry-run.

Credentials are fetched ONLY from a protected production Doppler context.
This script deliberately does not synchronize external DNS/OAuth changes or
run database migrations. Those changes require a separate reviewed cutover.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from doppler_secret import SecretError, get_secret

REPOSITORY = "oaslananka/kicad-mcp-pro"
SHA = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)
ID = re.compile(r"[a-zA-Z0-9_-]{8,100}\Z", re.ASCII)
MAX_BODY = 262144
PENDING = {"queued", "in_progress", "building", "pending", "waiting"}
SUCCESS = {"finished", "success"}
FAILED = {"failed", "error", "cancelled", "canceled"}
DEADLINE_SECONDS = 1200
APPLICATION_API_PATH = "/applications/"

JsonGetter = Callable[..., dict[str, Any]]
SecretGetter = Callable[..., str]


class DeployError(RuntimeError):
    """Error messages never contain response bodies or credentials."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: object,
        file: object,
        code: int,
        message: str,
        headers: dict[str, str],
        newurl: str,
    ) -> None:
        return None


def origin(raw: str) -> str:
    parsed = urllib.parse.urlsplit(raw)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or not raw.endswith(parsed.netloc)
    ):
        raise DeployError("INVALID_HTTPS_ORIGIN")
    return raw.rstrip("/")


def client_request(
    url: str, *, token: str = "", method: str = "GET", payload: dict[str, str] | None = None
) -> dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": "kicad-cloud-deploy/1"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if payload is not None:
        headers["Content-Type"] = "application/json"
    body = (
        json.dumps(payload, separators=(",", ":")).encode("utf-8") if payload is not None else None
    )
    request = urllib.request.Request(url, data=body, headers=headers, method=method)  # noqa: S310 -- HTTPS-only upstreams with no redirects
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(request, timeout=15) as response:  # noqa: S310 -- HTTPS-only API and redirects explicitly disabled
            result = response.read(MAX_BODY + 1)
    except urllib.error.HTTPError as exc:
        raise DeployError("REMOTE_HTTP_" + str(exc.code)) from None
    except (urllib.error.URLError, TimeoutError):
        raise DeployError("REMOTE_UNAVAILABLE") from None
    if len(result) > MAX_BODY:
        raise DeployError("REMOTE_BODY_TOO_LARGE")
    try:
        parsed = json.loads(result)
        if not isinstance(parsed, dict):
            raise DeployError("REMOTE_JSON_INVALID")
        return parsed
    except ValueError:
        raise DeployError("REMOTE_JSON_INVALID") from None


def _workflow_push_runs(
    api_base: str,
    workflow: str,
    github_authorization: str,
    get: JsonGetter,
) -> list[dict[str, Any]]:
    url = (
        api_base
        + "/actions/workflows/"
        + workflow
        + "/runs?"
        + urllib.parse.urlencode({"branch": "main", "event": "push", "per_page": 10})
    )
    runs = get(url, token=github_authorization).get("workflow_runs")
    if not isinstance(runs, list):
        raise DeployError("CI_RUNS_RESPONSE_INVALID")
    return [
        run
        for run in runs
        if isinstance(run, dict)
        and run.get("head_branch") == "main"
        and run.get("event") == "push"
        and isinstance(run.get("head_sha"), str)
        and SHA.fullmatch(run["head_sha"])
    ]


def _successful_run(run: dict[str, Any]) -> bool:
    return run.get("status") == "completed" and run.get("conclusion") == "success"


def require_successful_ci(sha: str, gh_token: str, get: JsonGetter = client_request) -> None:
    if not SHA.fullmatch(sha) or not gh_token:
        raise DeployError("CI_IDENTITY_MISSING")
    base = "https://api.github.com/repos/" + REPOSITORY
    branch = get(base + "/branches/main", token=gh_token)
    if branch.get("commit", {}).get("sha") != sha:
        raise DeployError("MAIN_SHA_CHANGED")

    if not any(
        _successful_run(r) and r["head_sha"] == sha
        for r in _workflow_push_runs(base, "ci.yml", gh_token, get)
    ):
        raise DeployError("MAIN_CI_NOT_SUCCESSFUL")

    # Cloud CI has a path filter and deliberately does NOT run for commits
    # outside apps/cloud. Do not burn CI minutes or block unrelated main SHAs.
    cloud_runs = _workflow_push_runs(base, "cloud-ci.yml", gh_token, get)
    if any(_successful_run(r) and r["head_sha"] == sha for r in cloud_runs):
        return
    previous = next((r for r in cloud_runs if _successful_run(r)), None)
    if previous is None:
        raise DeployError("CLOUD_CI_BASELINE_ABSENT")
    comparison = get(base + "/compare/" + previous["head_sha"] + "..." + sha, token=gh_token)
    if comparison.get("status") not in ("ahead", "identical"):
        raise DeployError("CLOUD_CI_BASELINE_NOT_ANCESTOR")
    files = comparison.get("files")
    # GitHub compare may truncate changed files at 300; fail closed.
    if not isinstance(files, list) or len(files) >= 300:
        raise DeployError("CLOUD_COMPARE_INCOMPLETE")
    cloud_paths = ("apps/cloud/", ".github/workflows/cloud-ci.yml")
    if any(
        isinstance(f, dict)
        and (
            f.get("filename", "").startswith(cloud_paths[0]) or f.get("filename") == cloud_paths[1]
        )
        for f in files
    ):
        raise DeployError("CLOUD_CI_NOT_SUCCESSFUL_FOR_CHANGED_CODE")
    # No Cloud files changed since the last passing Cloud CI. The exact-main
    # standard CI run was already verified above.


def verify_application(
    api: str, token: str, uuid: str, get: JsonGetter = client_request
) -> dict[str, Any]:
    app = get(api + APPLICATION_API_PATH + uuid, token=token)
    repository = app.get("git_repository", "")
    if repository not in (REPOSITORY, "https://github.com/" + REPOSITORY):
        raise DeployError("COOLIFY_REPOSITORY_MISMATCH")
    if app.get("git_branch") != "main":
        raise DeployError("COOLIFY_BRANCH_MISMATCH")
    if app.get("build_pack") != "dockercompose":
        raise DeployError("COOLIFY_BUILD_PACK_MISMATCH")
    if (
        app.get("base_directory") != "/apps/cloud"
        or app.get("docker_compose_location") != "/compose.coolify.yml"
    ):
        raise DeployError("COOLIFY_COMPOSE_LOCATION_MISMATCH")
    if app.get("settings", {}).get("is_auto_deploy_enabled") is not False:
        raise DeployError("COOLIFY_AUTO_DEPLOY_MUST_BE_OFF")
    if app.get("settings", {}).get("is_preview_deployments_enabled") is not False:
        raise DeployError("COOLIFY_PREVIEW_DEPLOY_MUST_BE_OFF")
    return app


def wait_deployment(
    api: str,
    token: str,
    uuid: str,
    sha: str,
    get: JsonGetter = client_request,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    seconds: int = DEADLINE_SECONDS,
) -> dict[str, Any]:
    end = clock() + seconds
    while clock() < end:
        state = get(api + "/deployments/" + uuid, token=token)
        status = str(state.get("status", "")).lower()
        commit = state.get("commit")
        if status in SUCCESS:
            if commit != sha:
                raise DeployError("COOLIFY_DEPLOYED_WRONG_COMMIT")
            return state
        if status in FAILED:
            raise DeployError("COOLIFY_DEPLOYMENT_FAILED")
        if status not in PENDING:
            raise DeployError("COOLIFY_UNKNOWN_DEPLOYMENT_STATUS")
        sleep(15)
    raise DeployError("COOLIFY_DEPLOYMENT_TIMEOUT")


def health(url: str, expected: str, get: JsonGetter = client_request) -> dict[str, Any]:
    if not SHA.fullmatch(expected):
        raise DeployError("INVALID_EXPECTED_SHA")
    result = get(origin(url) + "/health")
    if result.get("revision") != expected:
        raise DeployError("LIVE_REVISION_MISMATCH")
    return result


def verified_live_revision(
    app: dict[str, Any], public_origin: str, get: JsonGetter = client_request
) -> str:
    """Require Coolify's active application to match the public live revision.

    A deployment must not target a stale, stopped, or misrouted application.
    This check is read-only and runs before the deploy POST.
    """
    if app.get("status") != "running:healthy" or app.get("container_present") is not True:
        raise DeployError("COOLIFY_BASELINE_NOT_HEALTHY")
    live_sha = app.get("git_commit_sha")
    if not isinstance(live_sha, str) or not SHA.fullmatch(live_sha):
        raise DeployError("COOLIFY_BASELINE_SHA_UNKNOWN")
    health(public_origin, live_sha, get)
    return live_sha


def load_settings(fetch: SecretGetter = get_secret) -> dict[str, str]:
    env = os.environ
    if env.get("DOPPLER_CONFIG", "main") != "main":
        raise DeployError("PRODUCTION_DOPPLER_CONFIG_MISMATCH")
    token = env.get("DOPPLER_TOKEN", "")
    if not token:
        raise DeployError("PRODUCTION_DOPPLER_TOKEN_REQUIRED")
    needed = (
        "COOLIFY_URL",
        "COOLIFY_API_TOKEN",
        "COOLIFY_APPLICATION_UUID",
        "PUBLIC_ORIGIN",
        "OAUTH_ISSUER",
        "OAUTH_JWKS_URL",
        "OAUTH_AUDIENCE",
    )
    values = {
        key: fetch(key, token=token, project="kicad-mcp-pro", config="main") for key in needed
    }
    if not ID.fullmatch(values["COOLIFY_APPLICATION_UUID"]):
        raise DeployError("COOLIFY_APPLICATION_ID_INVALID")
    values["COOLIFY_URL"] = origin(values["COOLIFY_URL"]) + "/api/v1"
    values["PUBLIC_ORIGIN"] = origin(values["PUBLIC_ORIGIN"])
    expected = values["PUBLIC_ORIGIN"]
    if (
        values["OAUTH_ISSUER"] != expected + "/api/auth"
        or values["OAUTH_JWKS_URL"] != expected + "/api/auth/jwks"
        or values["OAUTH_AUDIENCE"] != expected + "/mcp"
    ):
        raise DeployError("OAUTH_DOMAIN_CONFIG_MISMATCH")
    return values


def rollback_if_available(
    api: str,
    token: str,
    app_uuid: str,
    old_sha: str,
    public_origin: str,
    get: JsonGetter = client_request,
    post: JsonGetter = client_request,
) -> None:
    # Only a known retained image matching the exact previous live revision
    # may be selected. No database or configuration migration is reversed.
    images = get(api + APPLICATION_API_PATH + app_uuid + "/rollback-images", token=token)
    available = images.get("images", [])
    matching = [
        item["tag"]
        for item in available
        if isinstance(item, dict)
        and not item.get("is_current")
        and isinstance(item.get("tag"), str)
        and item["tag"].rsplit(":", 1)[-1] == old_sha
    ]
    if len(matching) != 1:
        raise DeployError("ROLLBACK_IMAGE_NOT_VERIFIED")
    result = post(
        api + APPLICATION_API_PATH + app_uuid + "/rollback",
        token=token,
        method="POST",
        payload={"commit": matching[0]},
    )
    rollback_uuid = result.get("deployment_uuid", "")
    if not isinstance(rollback_uuid, str) or not ID.fullmatch(rollback_uuid):
        raise DeployError("ROLLBACK_RESPONSE_INVALID")
    wait_deployment(api, token, rollback_uuid, old_sha, get)
    health(public_origin, old_sha, get)


def preflight(
    sha: str,
    github_authorization: str,
    get: JsonGetter = client_request,
    fetch: SecretGetter = get_secret,
) -> str:
    """Read-only production acceptance: protected secrets, Coolify and live revision."""
    require_successful_ci(sha, github_authorization, get)
    values = load_settings(fetch)
    api, token, uuid = (
        values[key] for key in ("COOLIFY_URL", "COOLIFY_API_TOKEN", "COOLIFY_APPLICATION_UUID")
    )
    app = verify_application(api, token, uuid, get)
    live_sha = verified_live_revision(app, values["PUBLIC_ORIGIN"], get)
    print("Read-only production preflight accepted, live revision " + live_sha)
    return live_sha


def deploy(
    sha: str, gh_token: str, get: JsonGetter = client_request, post: JsonGetter = client_request
) -> None:
    require_successful_ci(sha, gh_token, get)
    values = load_settings()
    api, token, uuid = (
        values[k] for k in ("COOLIFY_URL", "COOLIFY_API_TOKEN", "COOLIFY_APPLICATION_UUID")
    )
    app = verify_application(api, token, uuid, get)
    previous_sha = verified_live_revision(app, values["PUBLIC_ORIGIN"], get)
    if previous_sha == sha:
        print("Cloud already runs the intended main SHA: " + sha)
        return

    # Coolify's deployment API uses the application's pinned git_commit_sha,
    # NOT the latest branch SHA. A /deploy POST without updating this pin
    # silently rebuilds the old commit and must never count as a release.
    require_successful_ci(sha, gh_token, get)
    latest = verify_application(api, token, uuid, get)
    if latest.get("git_commit_sha") != previous_sha:
        raise DeployError("COOLIFY_SOURCE_PIN_CHANGED")

    pin_changed = False
    deploy_requested = False
    try:
        post(
            api + APPLICATION_API_PATH + uuid,
            token=token,
            method="PATCH",
            payload={"git_commit_sha": sha},
        )
        pin_changed = True
        pinned = verify_application(api, token, uuid, get)
        if pinned.get("git_commit_sha") != sha:
            raise DeployError("COOLIFY_TARGET_PIN_NOT_VERIFIED")
        if pinned.get("status") != "running:healthy" or pinned.get("container_present") is not True:
            raise DeployError("COOLIFY_BASELINE_UNHEALTHY_AFTER_PIN")
        # Changing the source pin must not have restarted or rerouted the live app.
        health(values["PUBLIC_ORIGIN"], previous_sha, get)
        require_successful_ci(sha, gh_token, get)

        deploy_requested = True
        response = post(
            api
            + "/deploy?"
            + urllib.parse.urlencode({"uuid": uuid, "force": "false", "cancel_previous": "none"}),
            token=token,
            method="POST",
        )
        deployments = response.get("deployments", [])
        selected = [d for d in deployments if d.get("resource_uuid") == uuid]
        if len(selected) != 1 or not ID.fullmatch(selected[0].get("deployment_uuid", "")):
            raise DeployError("COOLIFY_DEPLOY_RESPONSE_INVALID")
        deployment = selected[0]["deployment_uuid"]
        print("Coolify deployment queued; waiting for exact-SHA verification")
        wait_deployment(api, token, deployment, sha, get)
        require_successful_ci(sha, gh_token, get)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                health(values["PUBLIC_ORIGIN"], sha, get)
                print("Verified Cloud commit " + sha)
                return
            except DeployError:
                time.sleep(8)
        raise DeployError("POST_DEPLOY_HEALTH_FAILED")
    except DeployError:
        if pin_changed and not deploy_requested:
            # No deployment was requested. Restore only if this is still our
            # source pin and the original live container is proven healthy.
            try:
                current = verify_application(api, token, uuid, get)
                if current.get("git_commit_sha") == sha:
                    if (
                        current.get("status") != "running:healthy"
                        or current.get("container_present") is not True
                    ):
                        raise DeployError("COOLIFY_PIN_RECOVERY_UNSAFE")
                    health(values["PUBLIC_ORIGIN"], previous_sha, get)
                    post(
                        api + APPLICATION_API_PATH + uuid,
                        token=token,
                        method="PATCH",
                        payload={"git_commit_sha": previous_sha},
                    )
                    if (
                        verify_application(api, token, uuid, get).get("git_commit_sha")
                        != previous_sha
                    ):
                        raise DeployError("COOLIFY_PIN_RECOVERY_NOT_VERIFIED")
                    print("Restored prior Coolify source pin " + previous_sha)
            except DeployError:
                print("::error::Source pin restoration could not be verified", file=sys.stderr)
        if deploy_requested and os.environ.get("COOLIFY_ROLLBACK_AUTO") == "true":
            try:
                rollback_if_available(
                    api, token, uuid, previous_sha, values["PUBLIC_ORIGIN"], get, post
                )
                print("Restored prior live Cloud revision " + previous_sha)
            except DeployError:
                print("::error::Automatic rollback could not be verified", file=sys.stderr)
        else:
            print(
                "::error::Deploy failed; automatic rollback remains disabled until verified",
                file=sys.stderr,
            )
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify-only", action="store_true")
    mode.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    try:
        if not SHA.fullmatch(args.sha):
            raise DeployError("INVALID_SOURCE_SHA")
        gh_token = os.environ.get("GH_TOKEN", "")
        if args.verify_only:
            require_successful_ci(args.sha, gh_token)
            print("Exact-main CI and Cloud CI gates confirmed; no deploy requested")
        else:
            if os.environ.get("GITHUB_REF") != "refs/heads/main":
                raise DeployError("MAIN_ONLY")
            if os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
                raise DeployError("MANUAL_DEPLOY_ONLY")
            if args.preflight_only:
                preflight(args.sha, gh_token)
            else:
                deploy(args.sha, gh_token)
        return 0
    except (DeployError, SecretError) as exc:
        print("::error::" + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
