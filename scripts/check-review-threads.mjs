#!/usr/bin/env node
import fs from "node:fs";
import process from "node:process";

const ACTIONABLE_BOT_TERMS = [
  "Bug:",
  "Potential issue:",
  "Suggested Fix",
  "security",
  "vulnerability",
  "correctness",
  "release",
  "publish",
  "workflow",
  "secret",
  "token",
  "unsafe",
];

const INFORMATIONAL_BOTS = new Set([
  "github-actions",
  "github-actions[bot]",
  "renovate",
  "renovate[bot]",
  "sentry",
  "sentry[bot]",
  "gemini-code-assist",
  "gemini-code-assist[bot]",
  "github-code-review",
  "github-code-review[bot]",
  "codeql",
  "codeql[bot]",
  "socket",
  "socket[bot]",
]);

function usage() {
  return `Usage: node scripts/check-review-threads.mjs [options]

Collect unresolved pull request review threads with GitHub GraphQL.

Rules:
  - resolved threads are ignored
  - outdated threads are ignored
  - unresolved human threads block
  - bot threads block only when they contain actionable release/security/workflow terms

Options:
  --repo <owner/name>       Repository. Default: GITHUB_REPOSITORY.
  --pr <number>             Pull request number. Default: PR_NUMBER or event payload.
  --json-out <path>         JSON output path. Default: review-thread-summary.json.
  --markdown-out <path>     Markdown output path. Default: review-thread-summary.md.
  --fixture <path>          Read a saved pullRequest object instead of calling GitHub.
  --fail-on-blocked         Exit 1 when actionable threads remain.
  --help                    Show this help.
`;
}

function parseArgs(argv) {
  const args = {
    repo: process.env.GITHUB_REPOSITORY || "oaslananka/kicad-mcp-pro",
    jsonOut: "review-thread-summary.json",
    markdownOut: "review-thread-summary.md",
    failOnBlocked: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--help" || arg === "-h") {
      args.help = true;
    } else if (arg === "--fail-on-blocked") {
      args.failOnBlocked = true;
    } else if (
      ["--repo", "--pr", "--json-out", "--markdown-out", "--fixture"].includes(
        arg,
      )
    ) {
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

function splitRepo(repo) {
  const [owner, name] = repo.split("/");
  if (!owner || !name)
    throw new Error(`Repository must be owner/name, got ${repo}`);
  return { owner, name };
}

function prFromEvent() {
  if (process.env.PR_NUMBER) return Number(process.env.PR_NUMBER);
  const eventPath = process.env.GITHUB_EVENT_PATH;
  if (!eventPath || !fs.existsSync(eventPath)) return null;
  const event = JSON.parse(fs.readFileSync(eventPath, "utf8"));
  const number = event.pull_request?.number || event.issue?.number;
  return number ? Number(number) : null;
}

function authToken() {
  return process.env.GITHUB_TOKEN || process.env.GH_TOKEN;
}

async function graphql(query, variables) {
  const token = authToken();
  if (!token)
    throw new Error("GITHUB_TOKEN or GH_TOKEN is required for GitHub GraphQL");
  const response = await fetch("https://api.github.com/graphql", {
    method: "POST",
    headers: {
      "user-agent": "check-review-threads-script",
      authorization: `Bearer ${token}`,
      accept: "application/vnd.github+json",
      "content-type": "application/json",
      "x-github-api-version": "2022-11-28",
    },
    body: JSON.stringify({ query, variables }),
  });
  const payload = await response.json();
  if (!response.ok || payload.errors) {
    throw new Error(
      `GitHub GraphQL request failed: ${JSON.stringify(payload.errors || payload)}`,
    );
  }
  return payload.data;
}

async function fetchPullRequest(owner, name, number) {
  const query = `
    query ReviewThreadGate($owner: String!, $name: String!, $number: Int!, $cursor: String) {
      repository(owner: $owner, name: $name) {
        pullRequest(number: $number) {
          id
          url
          isDraft
          reviewThreads(first: 100, after: $cursor) {
            pageInfo {
              hasNextPage
              endCursor
            }
            nodes {
              id
              isResolved
              isOutdated
              path
              line
              originalLine
              diffSide
              comments(first: 100) {
                nodes {
                  author {
                    login
                  }
                  body
                  url
                  createdAt
                  updatedAt
                }
              }
            }
          }
        }
      }
    }
  `;
  const threads = [];
  let pullRequest = null;
  let cursor = null;
  do {
    const data = await graphql(query, {
      owner,
      name,
      number: Number(number),
      cursor,
    });
    pullRequest = data.repository?.pullRequest;
    if (!pullRequest)
      throw new Error(`Pull request #${number} not found in ${owner}/${name}`);
    threads.push(...(pullRequest.reviewThreads?.nodes || []));
    cursor = pullRequest.reviewThreads?.pageInfo?.hasNextPage
      ? pullRequest.reviewThreads.pageInfo.endCursor
      : null;
  } while (cursor);
  return { ...pullRequest, reviewThreads: { nodes: threads } };
}

function normalizedLogin(comment) {
  return (comment.author?.login || "unknown").toLowerCase();
}

function isBot(comment) {
  const login = normalizedLogin(comment);
  return INFORMATIONAL_BOTS.has(login) || login.endsWith("[bot]");
}

function containsActionableTerm(text) {
  const lower = (text || "").toLowerCase();
  return ACTIONABLE_BOT_TERMS.some((term) =>
    lower.includes(term.toLowerCase()),
  );
}

function summarizeThread(thread) {
  const comments = thread.comments?.nodes || [];
  const unresolvedCurrent = !thread.isResolved && !thread.isOutdated;
  const humanComments = comments.filter((comment) => !isBot(comment));
  const actionableBotComments = comments.filter(
    (comment) => isBot(comment) && containsActionableTerm(comment.body),
  );
  const blocking =
    unresolvedCurrent &&
    (humanComments.length > 0 || actionableBotComments.length > 0);
  const reason = thread.isResolved
    ? "resolved"
    : thread.isOutdated
      ? "outdated"
      : humanComments.length > 0
        ? "human-review"
        : actionableBotComments.length > 0
          ? "actionable-bot"
          : "informational-bot";

  return {
    id: thread.id,
    isResolved: Boolean(thread.isResolved),
    isOutdated: Boolean(thread.isOutdated),
    path: thread.path || null,
    line: thread.line || null,
    originalLine: thread.originalLine || null,
    diffSide: thread.diffSide || null,
    blocking,
    reason,
    comments: comments.map((comment) => ({
      author: comment.author?.login || "unknown",
      body: comment.body || "",
      url: comment.url || null,
      createdAt: comment.createdAt || null,
      updatedAt: comment.updatedAt || null,
      bot: isBot(comment),
      actionable: containsActionableTerm(comment.body),
    })),
  };
}

function buildSummary(repo, number, pullRequest) {
  const threads = (pullRequest.reviewThreads?.nodes || []).map(summarizeThread);
  const blockingThreads = threads.filter((thread) => thread.blocking);
  return {
    repository: repo,
    pull_request: {
      number: Number(number),
      id: pullRequest.id,
      url: pullRequest.url,
      isDraft: Boolean(pullRequest.isDraft),
    },
    counts: {
      total: threads.length,
      blocking: blockingThreads.length,
      ignored: threads.length - blockingThreads.length,
      resolved: threads.filter((thread) => thread.reason === "resolved").length,
      outdated: threads.filter((thread) => thread.reason === "outdated").length,
      human: threads.filter((thread) => thread.reason === "human-review")
        .length,
      actionable_bot: threads.filter(
        (thread) => thread.reason === "actionable-bot",
      ).length,
    },
    blocked: blockingThreads.length > 0,
    blocking_threads: blockingThreads,
    ignored_threads: threads.filter((thread) => !thread.blocking),
  };
}

function markdown(summary) {
  const rows = summary.blocking_threads
    .map((thread) => {
      const firstComment = thread.comments[0];
      const location = `${thread.path || "(file)"}:${thread.line || thread.originalLine || "-"}`;
      const url = firstComment?.url || summary.pull_request.url;
      const author = firstComment?.author || "unknown";
      return `| [${thread.id}](${url}) | ${thread.reason} | \`${location}\` | ${author} |`;
    })
    .join("\n");
  return `# Review Thread Gate

Pull request: ${summary.pull_request.url}

- Total review threads: ${summary.counts.total}
- Blocking unresolved, current threads: ${summary.counts.blocking}
- Ignored resolved/outdated/informational threads: ${summary.counts.ignored}

${
  summary.blocked
    ? `| Thread | Reason | Location | First author |
|---|---|---|---|
${rows}
`
    : "No actionable unresolved, non-outdated review threads remain.\n"
}
`;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    process.stdout.write(usage());
    return;
  }
  const prNumber = args.pr ? Number(args.pr) : prFromEvent();
  if (!Number.isInteger(prNumber) || prNumber <= 0) {
    throw new Error(
      "--pr, PR_NUMBER, or a pull_request/issue event payload is required",
    );
  }
  const { owner, name } = splitRepo(args.repo);
  const pullRequest = args.fixture
    ? JSON.parse(fs.readFileSync(args.fixture, "utf8"))
    : await fetchPullRequest(owner, name, prNumber);
  const summary = buildSummary(args.repo, prNumber, pullRequest);
  const markdownText = markdown(summary);

  fs.writeFileSync(
    args.jsonOut,
    `${JSON.stringify(summary, null, 2)}\n`,
    "utf8",
  );
  fs.writeFileSync(args.markdownOut, markdownText, "utf8");
  process.stdout.write(markdownText);
  if (process.env.GITHUB_STEP_SUMMARY)
    fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, markdownText, "utf8");
  process.exitCode = args.failOnBlocked && summary.blocked ? 1 : 0;
}

main().catch((error) => {
  console.error(`check-review-threads: ${error.message}`);
  process.exitCode = 2;
});
