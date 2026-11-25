# agy-skills

A lightweight, cross-platform (Windows / Linux / macOS) side-pane UI plugin for **Antigravity** that inspects:

- **Skills Tab**
  - **Skill Token Distribution Bar**: Live breakdown of loaded skill bodies + auxiliary files, always-on system prompt index tokens, and deferred (unloaded) tokens.
  - **Session Activity**: Highlights every skill actually read in the current conversation, including step numbers, skills loaded **before `/compact` compaction**, and skills loaded by **spawned subagents** (with one-click jump to subagent conversations).
  - **All Discovered Skills**: Search and filter across `Workspace`, `Global`, `Plugin`, and `Builtin` scopes, showing 1–2 lines of description + `idx / body` tokens inline, with expandable detail drawers for full descriptions, auxiliary files (`references/`, `scripts/`, etc.), paths, and one-click `SKILL.md` open.
- **Plugins Tab**
  - Lists all installed plugins (enabled and disabled) across `Workspace`, `User`, and `Builtin` roots.
  - Displays each plugin's description, version, author, component chips (`Skill`, `Sidecar`, `Rule`, `Agent`, `MCP`, `Hooks`), and live vs. deferred context token impact.

Zero external npm dependencies — runs directly on Node.js ESM with Antigravity's built-in `sidecar_sdk`.

## Install

### From local directory (Windows / Linux / macOS)

```bash
agy plugin install /path/to/agy-skills
```

### Deploy locally & sync to remote Linux server (PowerShell)

```powershell
# Install/update into local ~/.gemini/config/plugins/skills
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1

# Deploy locally AND sync to a remote SSH host (e.g. L40)
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1 -RemoteHost L40
```

## Usage

1. Enable the **Skills** sidecar once from **Customizations → Skills** (or Sidecars Dashboard).
2. Open it anytime from the side panel `+` menu or by typing `/skills`.
3. Right-click the tab → **Pin Tab** to keep it visible across conversations.
