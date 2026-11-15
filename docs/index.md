---
title: KiCad MCP Pro — Documentation
hide:
  - toc
---

<div class="kmcp-home-hero">
  <p class="kmcp-home-eyebrow">KiCad MCP Pro · Documentation</p>
  <h1>Connect your KiCad project to an AI client.</h1>
  <p class="kmcp-home-lead">Install the local MCP server, connect your preferred client, and inspect schematics or PCBs. Start read-only and enable write operations explicitly when needed. Your local projects do not require a Cloud account.</p>
  <div class="kmcp-home-actions">
    <a class="kmcp-home-button kmcp-home-button--primary" href="installation/">Install locally</a>
    <a class="kmcp-home-button" href="client-configuration/">Connect an AI client</a>
  </div>
</div>

<div class="kmcp-home-grid">
  <a class="kmcp-home-card" href="installation/">
    <strong>1 · Install and check</strong>
    <span>Set up the CLI, find KiCad, and check the environment with the built-in doctor.</span>
  </a>
  <a class="kmcp-home-card" href="client-configuration/">
    <strong>2 · Choose an AI client</strong>
    <span>Connect through local stdio or Streamable HTTP. Review project access before enabling writes.</span>
  </a>
  <a class="kmcp-home-card" href="installation/#optional-cloud-access">
    <strong>3 · Optional Cloud access</strong>
    <span>Use remote access only when needed. Device pairing and project permissions are separate steps.</span>
  </a>
</div>

## Local quick start

Install using [uv](https://docs.astral.sh/uv/) and follow the guided setup:

```powershell
uv tool install kicad-mcp-pro
kicad-mcp-pro setup
kicad-mcp-pro doctor
```

KiCad 10.x is needed for live project integration. A local installation works without signing in. See [Installation](installation.md) for Windows, macOS, Linux and local HTTP options.

## Find what you need

<div class="kmcp-home-shortcuts">
  <a href="tutorials/getting-started/">Getting started tutorial</a>
  <a href="tools-reference/">Explore MCP tools</a>
  <a href="workflows/first-pcb/">First PCB workflow</a>
  <a href="troubleshooting/">Troubleshooting</a>
  <a href="agents/">AI client guides</a>
  <a href="security/requirements/">Security and permissions</a>
</div>

<div class="kmcp-home-support">
  <span>Support this open-source project:</span>
  <a href="https://github.com/sponsors/oaslananka" target="_blank" rel="noopener noreferrer">GitHub Sponsors</a>
  <a href="https://www.buymeacoffee.com/oaslananka" target="_blank" rel="noopener noreferrer">Buy Me a Coffee</a>
</div>
