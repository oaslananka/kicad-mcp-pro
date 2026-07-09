#!/usr/bin/env node
import fs from "node:fs";
import { execFileSync } from "node:child_process";
import process from "node:process";

const CLASSES = [
  {
    id: "trusted-publisher-mismatch",
    patterns: [
      /trusted publisher/i,
      /invalid-publisher/i,
      /publisher .* configured/i,
      /id-token/i,
      /oidc/i,
      /OpenID Connect/i,
    ],
    root_cause:
      "The PyPI/TestPyPI trusted publisher identity does not match the repository, workflow, environment, or ref used by the release run.",
    safe_fix:
      "Verify the PyPI/TestPyPI trusted publisher owner, repository, workflow filename, environment, and project name. Do not add long-lived tokens as a workaround.",
    auto_fix_allowed: false,
    publish_must_stop: true,
    human_approval_required: true,
  },
  {
    id: "non-python-asset-uploaded-to-pypi",
    patterns: [
      /InvalidDistribution/i,
      /SHA256SUMS\.txt/i,
      /bom\.json/i,
      /not a valid (wheel|sdist|distribution)/i,
      /Unknown distribution format/i,
    ],
    root_cause:
      "The package-index upload included non-Python release assets instead of only wheel and source distribution files.",
    safe_fix:
      "Stage only dist/*.whl and dist/*.tar.gz for pypa/gh-action-pypi-publish; keep SBOM, checksums, signatures, and attestations as GitHub Release assets.",
    auto_fix_allowed: true,
    publish_must_stop: true,
    human_approval_required: false,
  },
  {
    id: "artifact-quota-exhausted",
    patterns: [
      /Artifact storage quota has been hit/i,
      /Failed to CreateArtifact: .*quota/i,
      /Unable to upload any new artifacts/i,
    ],
    root_cause:
      "The release workflow attempted to store inter-job artifacts in GitHub Actions after the repository or account artifact quota was exhausted.",
    safe_fix:
      "Remove actions/upload-artifact and actions/download-artifact from the release publish path; build, sign, publish, and attach release files in one job or use an external artifact backend.",
    auto_fix_allowed: false,
    publish_must_stop: true,
    human_approval_required: true,
  },
  {
    id: "sigstore-uv-config-conflict",
    patterns: [
      /gh-action-sigstore-python/i,
      /sigstore/i,
      /UV_NO_CONFIG/i,
      /uv.*config/i,
      /No interpreter found/i,
    ],
    root_cause:
      "Repository uv configuration leaked into the pinned Sigstore action runtime or changed the action-managed Python environment.",
    safe_fix:
      "Isolate the signing action with UV_NO_CONFIG=1 and runner-temp uv cache/Python settings.",
    auto_fix_allowed: true,
    publish_must_stop: true,
    human_approval_required: false,
  },
  {
    id: "release-metadata-drift",
    patterns: [
      /metadata.*drift/i,
      /version.*mismatch/i,
      /server\.json/i,
      /mcp\.json/i,
      /pyproject\.toml/i,
    ],
    root_cause:
      "Release metadata sources disagree on version, package identity, or canonical repository URL.",
    safe_fix:
      "Run the metadata sync/check tooling, inspect the diff, and commit only the intended metadata alignment.",
    auto_fix_allowed: true,
    publish_must_stop: true,
    human_approval_required: false,
  },
  {
    id: "changelog-release-please-noise",
    patterns: [
      /release-please/i,
      /CHANGELOG\.md/i,
      /stale release/i,
      /Bump version to/i,
    ],
    root_cause:
      "Release-please generated or retained stale changelog/version text that made release preflight noisy.",
    safe_fix:
      "Refresh the release-please branch or remove only the stale generated noise after confirming the release notes remain accurate.",
    auto_fix_allowed: true,
    publish_must_stop: false,
    human_approval_required: false,
  },
  {
    id: "post-publish-smoke-propagation-delay",
    patterns: [
      /Post-publish smoke/i,
      /No matching distribution found/i,
      /simple index/i,
      /index propagation/i,
      /Retrying/i,
      /Could not find a version that satisfies/i,
    ],
    root_cause:
      "The package publish completed but the selected index had not propagated the exact version to install clients yet, or the smoke used the wrong index settings.",
    safe_fix:
      "Keep bounded retries, use PyPI as TestPyPI dependency fallback, and verify the exact version from a clean virtual environment before retrying release publish.",
    auto_fix_allowed: true,
    publish_must_stop: false,
    human_approval_required: false,
  },
  {
    id: "release-tag-collision",
    patterns: [
      /would clobber existing tag/i,
      /stale tag/i,
      /refs\/tags\/v[\w.-]+.*rejected/i,
      /tag .* already exists/i,
    ],
    root_cause:
      "The repository already has a version tag with the same name pointing at a different object.",
    safe_fix:
      "Leave package release state alone and repair the divergent tag through a reviewed maintenance change.",
    auto_fix_allowed: false,
    publish_must_stop: false,
    human_approval_required: true,
  },
  {
    id: "workflow-syntax",
    patterns: [
      /Invalid workflow file/i,
      /actionlint/i,
      /YAML/i,
      /unexpected key/i,
      /Unrecognized named-value/i,
      /workflow syntax/i,
    ],
    root_cause:
      "A GitHub Actions workflow has invalid YAML, invalid expression syntax, or unsupported inputs.",
    safe_fix:
      "Run workflow lint locally, fix the exact syntax or action input error, and keep action refs pinned.",
    auto_fix_allowed: true,
    publish_must_stop: true,
    human_approval_required: false,
  },
  {
    id: "test-failure",
    patterns: [
      /pytest/i,
      /FAILED/i,
      /AssertionError/i,
      /tests\/.*\.py/i,
      /tests\\.*\.py/i,
    ],
    root_cause: "A unit, integration, or smoke test failed.",
    safe_fix:
      "Fix the regression first. Update tests only when behavior intentionally changed and the new expectation is documented.",
    auto_fix_allowed: true,
    publish_must_stop: false,
    human_approval_required: false,
  },
  {
    id: "typecheck-failure",
    patterns: [
      /mypy/i,
      /pyright/i,
      /typecheck/i,
      /incompatible type/i,
      /not assignable/i,
    ],
    root_cause: "Static type checking failed.",
    safe_fix:
      "Fix annotations or implementation types; add ignores only for narrow false positives with context.",
    auto_fix_allowed: true,
    publish_must_stop: false,
    human_approval_required: false,
  },
  {
    id: "lint-failure",
    patterns: [
      /ruff/i,
      /eslint/i,
      /lint/i,
      /format --check/i,
      /would reformat/i,
    ],
    root_cause: "Formatting or lint rules failed.",
    safe_fix:
      "Run the repo formatter/linter and commit the minimal resulting diff.",
    auto_fix_allowed: true,
    publish_must_stop: false,
    human_approval_required: false,
  },
  {
    id: "infra-flake",
    patterns: [
      /timed out/i,
      /TLS/i,
      /ECONNRESET/i,
      /rate limit/i,
      /5\d\d/i,
      /temporarily unavailable/i,
      /runner.*lost/i,
    ],
    root_cause:
      "The log resembles transient runner, network, or external service instability.",
    safe_fix:
      "Rerun only after confirming no deterministic project failure appears in the failed logs.",
    auto_fix_allowed: false,
    publish_must_stop: false,
    human_approval_required: false,
  },
  {
    id: "unknown",
    patterns: [/.*/],
    root_cause:
      "The failure did not match a known repository operations class.",
    safe_fix:
      "Inspect the failed job log and classify the root cause before applying a fix or rerunning release steps.",
    auto_fix_allowed: false,
    publish_must_stop: true,
    human_approval_required: true,
  },
];

function usage() {
  return `Usage: node scripts/classify-gh-failure.mjs [options]

Classify failed GitHub Actions logs into repository operations failure classes.

Options:
  --file <path>       Read log text from a file.
  --text <text>       Classify the provided text.
  --run-id <id>       Read failed logs with gh run view <id> --log-failed.
  --repo <owner/name> Repository for --run-id. Default: GITHUB_REPOSITORY.
  --json              Emit JSON instead of Markdown.
  --help              Show this help.
`;
}

function parseArgs(argv) {
  const args = {
    json: false,
    repo: process.env.GITHUB_REPOSITORY || "oaslananka/kicad-mcp-pro",
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--help" || arg === "-h") {
      args.help = true;
    } else if (arg === "--json") {
      args.json = true;
    } else if (["--file", "--text", "--run-id", "--repo"].includes(arg)) {
      const value = argv[index + 1];
      if (!value) throw new Error(`${arg} requires a value`);
      args[arg.slice(2).replace(/-([a-z])/g, (_, char) => char.toUpperCase())] =
        value;
      index += 1;
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  return args;
}

function readRunLog(repo, runId) {
  return execFileSync(
    "gh",
    ["run", "view", runId, "--repo", repo, "--log-failed"],
    {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      maxBuffer: 20 * 1024 * 1024,
    },
  );
}

function classify(text) {
  return (
    CLASSES.find((entry) =>
      entry.patterns.some((pattern) => pattern.test(text)),
    ) || CLASSES.at(-1)
  );
}

function markdown(result) {
  return `# Failure Classification

- Class: \`${result.classification}\`
- Auto-fix allowed: ${result.auto_fix_allowed ? "true" : "false"}
- Publish must stop: ${result.publish_must_stop ? "true" : "false"}
- Human approval required: ${result.human_approval_required ? "true" : "false"}

## Root Cause

${result.root_cause}

## Safe Fix

${result.safe_fix}
`;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    process.stdout.write(usage());
    return;
  }

  let text = "";
  if (args.file) text = fs.readFileSync(args.file, "utf8");
  else if (args.text) text = args.text;
  else if (args.runId) text = readRunLog(args.repo, args.runId);
  else text = fs.readFileSync(0, "utf8");

  const match = classify(text);
  const result = {
    classification: match.id,
    root_cause: match.root_cause,
    safe_fix: match.safe_fix,
    auto_fix_allowed: match.auto_fix_allowed,
    publish_must_stop: match.publish_must_stop,
    human_approval_required: match.human_approval_required,
  };

  process.stdout.write(
    args.json ? `${JSON.stringify(result, null, 2)}\n` : markdown(result),
  );
}

try {
  main();
} catch (error) {
  console.error(`classify-gh-failure: ${error.message}`);
  process.exitCode = 2;
}
