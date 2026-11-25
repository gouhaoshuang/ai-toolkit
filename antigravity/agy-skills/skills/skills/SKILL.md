---
name: skills
description: Open the native Skills side-pane panel to inspect skills loaded in the current conversation (including pre-compaction and subagent loads), all discovered skills across scopes, and installed plugin details with token usage. Use when the user runs /skills or asks to open the skills panel.
---

# Skills panel

Open or guide the user to the **Skills** side-pane panel (`skills/skills_panel`).

## Instructions

1. Determine the install directory `<dir>` of this plugin (normally `skills`, or `agy-skills` if cloned directly). The sidecar ID is `<dir>/skills_panel`.
2. Check read-only whether `<dir>/skills_panel` is active:
   - Look up `.sidecars["<dir>/skills_panel"].enabled == true` in `~/.gemini/config/config.json`, or
   - Check if `~/.gemini/antigravity/sidecar_data/<dir>/skills_panel/logs/sidecar.log` exists and is non-empty.
3. **If active**, output the one-click pill on its own line:
   `[Skills](sidecar://<dir>/skills_panel/)`
   Tell the user they can also open it from the `+` button in the side panel, and pin the tab via **Right-click tab -> Pin Tab**.
4. **If not yet enabled**, do not output a `sidecar://` link. Instead, provide:
   - `[Skills](customization://<dir>)`
   - `[Open Sidecars Dashboard](sidecar://dashboard)`
   Tell them to enable the **Skills** sidecar once so it appears in the side panel `+` menu.
