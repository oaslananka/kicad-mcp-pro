# ChatGPT Web Integration

ChatGPT web users can connect to KiCad via a custom GPT app powered by the KiCad MCP remote server.

## Prerequisites

- ChatGPT Plus/Pro/Business/Enterprise account
- Enable **Developer Mode**: Settings → Apps → Advanced → Developer mode
- A publicly hosted KiCad MCP remote server

## Setup

1. Enable Developer Mode in ChatGPT
2. Create a new app with the MCP server URL
3. Configure auth (no-auth for dev, OAuth for production)
4. The app appears in your ChatGPT interface

## Mode A — Public-safe (V1)

- No local filesystem access
- Upload KiCad project zip for analysis
- Cloud static analysis only
- Report generation and config snippet generation

## Mode B — Developer/Local Bridge (V2)

- User runs `kicad-mcp-pro bridge` locally
- ChatGPT app pairs with local bridge via pairing code
- Write tools require local approval
- Short-lived tokens and project access

## UI Widgets

The ChatGPT app includes optional web UI components:
- Project Overview Card
- Board Health Dashboard
- ERC/DRC Issue Table
- BOM Summary
- Manufacturing Export Checklist

## Example Prompt

> Analyze this KiCad project. Use the kicad MCP tools to inspect the uploaded project, run quality checks, and summarize board readiness for manufacturing.
