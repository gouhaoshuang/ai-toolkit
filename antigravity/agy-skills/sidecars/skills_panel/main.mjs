/**
 * Skills Panel sidecar backend.
 *
 * Cross-platform (Windows / Linux / macOS) read-only HTTP server powered by
 * Antigravity's SidecarApp SDK. Zero external npm dependencies.
 */

import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import {
  ID_RE,
  analyzeSkillsAndPlugins,
  findAppDataDirs,
  listRecentConversations,
  resolveConversationAppData,
} from './analyzer.mjs';

const sdkFallbackUrl = pathToFileURL(
  join(homedir(), '.gemini', 'antigravity', 'lib', 'node_modules', 'sidecar_sdk', 'index.mjs')
).href;

const { SidecarApp, Response } = await import('sidecar_sdk').catch(() => import(sdkFallbackUrl));

const __dirname = dirname(fileURLToPath(import.meta.url));
const STATIC = {
  '/styles.css': ['styles.css', 'text/css; charset=utf-8'],
  '/app.js': ['app.js', 'application/javascript; charset=utf-8'],
};
const NO_STORE = { 'Cache-Control': 'no-store' };

function parseWorkspaceUris(raw) {
  if (!raw || typeof raw !== 'string') return [];
  const trimmed = raw.trim();
  if (!trimmed) return [];
  if (trimmed.startsWith('[')) {
    try {
      const arr = JSON.parse(trimmed);
      return Array.isArray(arr) ? arr.filter((u) => typeof u === 'string' && u) : [];
    } catch {
      return [];
    }
  }
  return trimmed
    .split('|')
    .map((s) => s.trim())
    .filter(Boolean);
}

const app = new SidecarApp();

app.page('/', () =>
  new Response(readFileSync(join(__dirname, 'index.html'), 'utf-8'), {
    contentType: 'text/html; charset=utf-8',
    headers: NO_STORE,
  })
);

for (const [route, [file, contentType]] of Object.entries(STATIC)) {
  app.api(
    route,
    () =>
      new Response(readFileSync(join(__dirname, file), 'utf-8'), {
        contentType,
        headers: NO_STORE,
      }),
    'GET'
  );
}

app.api(
  '/api/skills',
  async (data) => {
    const requestedConv = typeof data.conversationId === 'string' ? data.conversationId.trim() : '';
    const hostConv = app.config.conversationId || '';
    const conv = requestedConv || hostConv || listRecentConversations(1)[0]?.id || '';
    const workspaceUris = parseWorkspaceUris(data.workspaces);

    let appData = conv && ID_RE.test(conv) ? resolveConversationAppData(conv) : null;
    if (!appData) {
      appData = findAppDataDirs()[0] || join(homedir(), '.gemini', 'antigravity');
    }

    const snap = await analyzeSkillsAndPlugins(appData, conv && ID_RE.test(conv) ? conv : '', {
      workspaceUris,
    });

    const subSig = (snap.subagentMeta || [])
      .map((m) => `${m.conversationId}:${m.mtime}:${m.size}`)
      .join(',');
    const pluginSig = (snap.plugins || [])
      .map((p) => `${p.dir}:${p.enabled ? 1 : 0}:${p.tokens.active}`)
      .join(',');
    const skillSig = (snap.skills || [])
      .map((s) => `${s.name}:${s.loadState}:${s.activeSteps.length}:${s.loadedAuxTokens}`)
      .join(',');

    const etag = [
      snap.conversationId || '',
      workspaceUris.join(','),
      snap.transcriptStats.mtime,
      snap.transcriptStats.size,
      snap.compaction.count,
      subSig,
      pluginSig,
      skillSig,
    ].join('|');

    if (data.etag && data.etag === etag) {
      return { conversationId: snap.conversationId, found: true, unchanged: true, etag };
    }

    return { ...snap, etag };
  },
  'GET'
);

app.run();
