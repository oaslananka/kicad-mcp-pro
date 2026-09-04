const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const testRoot = path.resolve(__dirname, "..", "dist-test", "test");

function collectTests(directory) {
  const files = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const fullPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectTests(fullPath));
    } else if (entry.isFile() && entry.name.endsWith(".test.js")) {
      files.push(fullPath);
    }
  }
  return files.sort((left, right) =>
    left < right ? -1 : left > right ? 1 : 0,
  );
}

const testFiles = collectTests(testRoot);
if (testFiles.length === 0) {
  console.error(`No compiled test files found under ${testRoot}`);
  process.exit(1);
}

const result = spawnSync(process.execPath, ["--test", ...testFiles], {
  stdio: "inherit",
});

process.exit(result.status ?? 1);
