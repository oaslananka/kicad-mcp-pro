import { bench, describe } from "vitest";
import { Account, Landing, renderPage } from "../src/ui-shell.js";
import { renderDevicesPage } from "../src/devices-ui.js";

const devices = Array.from({ length: 50 }, (_, i) => ({
  id: `00000000-0000-4000-8000-${i.toString(16).padStart(12, "0")}`,
  alias: `Workstation ${i}`,
  enabled: i % 3 !== 0,
  revoked: i % 7 === 0,
  fingerprint: "ab".repeat(32),
  createdAt: new Date(1_780_000_000_000),
  csrf: "csrf-token-" + i
}));

describe("server-rendered UI", () => {
  bench("render landing page", () => {
    renderPage({ title: "Local-first KiCad engineering.", kind: "home", children: <Landing identityEnabled /> });
  });

  bench("render account page", () => {
    renderPage({ title: "Workspace", kind: "account", children: <Account name="Ada Lovelace" /> });
  });

  bench("render devices page (50 devices)", () => {
    renderDevicesPage(devices, "Device revoked.");
  });
});
