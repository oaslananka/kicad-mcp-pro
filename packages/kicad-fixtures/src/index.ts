import fs from "node:fs";
import path from "node:path";

export const KICAD_FIXTURE_IDS = [
  "clean-led-kicad10",
  "stale-diagnostics-kicad10",
  "kicad-10-0-3-regressions",
  "erc-power-pin-error",
  "drc-courtyard-error",
  "unconnected-pcb",
  "missing-netlist",
  "empty-board",
  "empty-project-kicad10",
  "no-dru-file",
  "multi-sheet-schematic",
  "large-board",
  "malformed-sch",
  "malformed-pcb",
  "paths-with-spaces",
  "unicode-path-çöğü",
] as const;

export const KICAD_EXPECTED_FILES = [
  "project-tree.snapshot.json",
  "diagnostics.snapshot.json",
  "status.snapshot.json",
  "erc-report.json",
  "drc-report.json",
  "bom.csv",
  "netlist.net",
  "board-stats.txt",
] as const;

export type KicadFixtureId = (typeof KICAD_FIXTURE_IDS)[number];
export type KicadExpectedFile = (typeof KICAD_EXPECTED_FILES)[number];
export type KicadFixtureOutcome = "pass" | "warn" | "fail";

export interface KicadRegressionCoverage {
  kicadVersion: string;
  source: string;
  cli: string[];
  importers: string[];
  pcb: string[];
}

export interface KicadFixtureManifestEntry {
  id: KicadFixtureId;
  semanticName: KicadFixtureId;
  path: string;
  projectFile: string;
  schematicFiles: string[];
  boardFile: string | null;
  designRulesFile: string | null;
  expectedPath: string;
  expectedFiles: KicadExpectedFile[];
  expectedOutcome: KicadFixtureOutcome;
  tags: string[];
  regressionCoverage?: KicadRegressionCoverage;
}

export interface KicadFixtureManifest {
  schemaVersion: 1;
  generatedBy: string;
  trackingIssue: "OASLANA-53";
  githubIssue: 54;
  root: string;
  expectedRoot: string;
  fixtureCount: number;
  expectedFiles: KicadExpectedFile[];
  fixtures: KicadFixtureManifestEntry[];
}

function isKicadFixturesPackageRoot(candidate: string): boolean {
  const packageJsonPath = path.join(candidate, "package.json");
  if (!fs.existsSync(packageJsonPath)) {
    return false;
  }
  try {
    const packageJson = JSON.parse(
      fs.readFileSync(packageJsonPath, "utf8"),
    ) as {
      name?: unknown;
    };
    return packageJson.name === "@oaslananka/kicad-fixtures";
  } catch {
    return false;
  }
}

export function findKicadFixturesPackageRoot(startDir = __dirname): string {
  let current = path.resolve(startDir);

  while (true) {
    if (isKicadFixturesPackageRoot(current)) {
      return current;
    }
    const parent = path.dirname(current);
    if (parent === current) {
      throw new Error(
        `Could not find @oaslananka/kicad-fixtures package root from ${startDir}`,
      );
    }
    current = parent;
  }
}

export function kicadFixturesRoot(
  packageRoot = findKicadFixturesPackageRoot(),
): string {
  return path.join(packageRoot, "fixtures");
}

export function kicadExpectedRoot(
  packageRoot = findKicadFixturesPackageRoot(),
): string {
  return path.join(packageRoot, "expected");
}

export function kicadFixtureManifestPath(
  packageRoot = findKicadFixturesPackageRoot(),
): string {
  return path.join(packageRoot, "manifest.json");
}

export function loadKicadFixtureManifest(
  packageRoot = findKicadFixturesPackageRoot(),
): KicadFixtureManifest {
  return JSON.parse(
    fs.readFileSync(kicadFixtureManifestPath(packageRoot), "utf8"),
  ) as KicadFixtureManifest;
}

export function getKicadFixture(
  fixtureId: KicadFixtureId | (string & {}),
  manifest = loadKicadFixtureManifest(),
): KicadFixtureManifestEntry {
  const fixture = manifest.fixtures.find((entry) => entry.id === fixtureId);
  if (!fixture) {
    throw new Error(`Unknown KiCad fixture id: ${fixtureId}`);
  }
  return fixture;
}

export function kicadFixturePath(
  fixtureId: KicadFixtureId | (string & {}),
  ...segments: string[]
): string {
  return path.join(kicadFixturesRoot(), fixtureId, ...segments);
}

export function kicadExpectedPath(
  fixtureId: KicadFixtureId | (string & {}),
  ...segments: string[]
): string {
  return path.join(kicadExpectedRoot(), fixtureId, ...segments);
}
