/**
 * Cross-platform (Windows + Linux + macOS) read-only analyzer for the Skills sidecar.
 *
 * Inspects:
 * 1. Current conversation transcript (post-compaction active window, pre-compaction
 *    history, and spawned subagent transcripts) to determine which skills and
 *    auxiliary skill files were actually read into context.
 * 2. All discovered skills across Workspace, Global, Plugin, and Builtin scopes
 *    with YAML frontmatter descriptions, file metadata, and token accounting.
 * 3. All installed plugins (enabled & disabled) with descriptions, components
 *    (skills, rules, agents, MCP servers, sidecars, hooks), and total token impact.
 */

import { existsSync, readFileSync, readdirSync, realpathSync, statSync } from 'node:fs';
import { homedir } from 'node:os';
import { basename, dirname, isAbsolute, join, relative, resolve as resolvePath } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const ID_RE = /^[0-9a-f-]{8,}$/i;
const UUID_FIND_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;
const IS_WIN = process.platform === 'win32';
const IGNORED_DIRS = new Set(['.git', 'node_modules', '__pycache__', '.venv', 'dist', 'build']);

// ---------------------------------------------------------------------------
// Path & File Helpers (Cross-Platform)
// ---------------------------------------------------------------------------

export function normPathKey(p) {
  if (!p || typeof p !== 'string') return '';
  let resolved = p;
  try {
    resolved = realpathSync(p);
  } catch {
    try {
      resolved = resolvePath(p);
    } catch {
      resolved = p;
    }
  }
  return IS_WIN ? resolved.toLowerCase() : resolved;
}

function safeRealpath(p) {
  try {
    return realpathSync(p);
  } catch {
    return null;
  }
}

function safeReaddir(dir) {
  try {
    return readdirSync(dir);
  } catch {
    return [];
  }
}

function safeReaddirWithTypes(dir) {
  try {
    return readdirSync(dir, { withFileTypes: true });
  } catch {
    return [];
  }
}

export function statOf(p) {
  try {
    const s = statSync(p);
    return { mtime: s.mtimeMs, size: s.size, isFile: s.isFile(), isDir: s.isDirectory() };
  } catch {
    return { mtime: 0, size: -1, isFile: false, isDir: false };
  }
}

const fileCache = new Map();
function readCached(p, maxBytes = 2 * 1024 * 1024) {
  const s = statOf(p);
  if (s.size < 0 || !s.isFile) return { text: null, ...s };
  if (s.size > maxBytes) return { text: null, tooLarge: true, ...s };
  const key = `${s.mtime}:${s.size}`;
  const hit = fileCache.get(p);
  if (hit && hit.key === key) return { text: hit.text, ...s };
  let text = null;
  try {
    text = readFileSync(p, 'utf-8');
  } catch {
    return { text: null, ...s };
  }
  if (fileCache.size > 800) fileCache.clear();
  fileCache.set(p, { key, text });
  return { text, ...s };
}

function stripJsonc(raw) {
  if (!raw) return '';
  let out = '';
  let inStr = false;
  let esc = false;
  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i];
    const next = raw[i + 1];
    if (inStr) {
      out += ch;
      if (esc) {
        esc = false;
      } else if (ch === '\\') {
        esc = true;
      } else if (ch === '"') {
        inStr = false;
      }
      continue;
    }
    if (ch === '"') {
      inStr = true;
      out += ch;
    } else if (ch === '/' && next === '/') {
      while (i < raw.length && raw[i] !== '\n') i++;
      out += '\n';
    } else if (ch === '/' && next === '*') {
      i += 2;
      while (i < raw.length && !(raw[i] === '*' && raw[i + 1] === '/')) i++;
      i++;
    } else {
      out += ch;
    }
  }
  return out.replace(/,\s*([}\]])/g, '$1');
}

function readJsonSafe(p) {
  const { text } = readCached(p, 2 * 1024 * 1024);
  if (text == null) return null;
  try {
    return JSON.parse(text);
  } catch {
    try {
      return JSON.parse(stripJsonc(text));
    } catch {
      return null;
    }
  }
}

function unquote(v) {
  if (typeof v !== 'string') return v == null ? '' : String(v);
  const s = v.trim();
  if (s.length >= 2 && s.startsWith('"') && s.endsWith('"')) {
    try {
      return String(JSON.parse(s));
    } catch {
      return s.slice(1, -1);
    }
  }
  return s;
}

function uriToPath(uri) {
  if (!uri || typeof uri !== 'string') return null;
  if (uri.startsWith('file://')) {
    try {
      return fileURLToPath(uri);
    } catch {
      return decodeURIComponent(uri.slice(7));
    }
  }
  if (isAbsolute(uri)) return uri;
  return null;
}

// ---------------------------------------------------------------------------
// AppData & Conversation Discovery
// ---------------------------------------------------------------------------

export function findAppDataDirs() {
  const dataDir = process.env.ANTIGRAVITY_EXECUTABLE_DATA_DIR;
  if (dataDir) {
    for (let d = dataDir; d !== dirname(d); d = dirname(d)) {
      if (basename(d) !== 'sidecar_data') continue;
      const appData = dirname(d);
      return existsSync(join(appData, 'brain')) ? [appData] : [];
    }
    return [];
  }
  const root = join(homedir(), '.gemini');
  return safeReaddir(root)
    .sort()
    .map((name) => join(root, name))
    .filter((c) => existsSync(join(c, 'brain')));
}

export function resolveConversationAppData(convId) {
  if (!convId || !ID_RE.test(convId)) return null;
  for (const appData of findAppDataDirs()) {
    if (existsSync(join(appData, 'brain', convId))) return appData;
  }
  return null;
}

export function listRecentConversations(limit = 20) {
  const seen = new Set();
  const list = [];
  for (const appData of findAppDataDirs()) {
    const brainRoot = join(appData, 'brain');
    for (const id of safeReaddir(brainRoot)) {
      if (!ID_RE.test(id) || seen.has(id)) continue;
      const logsDir = join(brainRoot, id, '.system_generated', 'logs');
      const fullStat = statOf(join(logsDir, 'transcript_full.jsonl'));
      const activeStat = fullStat.size >= 0 ? fullStat : statOf(join(logsDir, 'transcript.jsonl'));
      if (activeStat.size < 0) continue;
      seen.add(id);
      list.push({ id, appData, mtime: activeStat.mtime, size: activeStat.size });
    }
  }
  list.sort((a, b) => b.mtime - a.mtime);
  return list.slice(0, limit);
}

// ---------------------------------------------------------------------------
// CJK-Aware Token Estimation & Frontmatter Parsing
// ---------------------------------------------------------------------------

export function estTextTokens(text) {
  if (!text || typeof text !== 'string') return 0;
  const len = text.length;
  if (len === 0) return 0;

  const sample = len > 4000 ? text.slice(0, 4000) : text;
  let cjk = 0;
  let punct = 0;
  for (let i = 0; i < sample.length; i++) {
    const c = sample.charCodeAt(i);
    if (
      (c >= 0x4e00 && c <= 0x9fff) ||
      (c >= 0x3400 && c <= 0x4dbf) ||
      (c >= 0x3000 && c <= 0x303f) ||
      (c >= 0xff00 && c <= 0xffef)
    ) {
      cjk++;
    } else if (
      c === 123 || c === 125 || c === 91 || c === 93 ||
      c === 58 || c === 34 || c === 60 || c === 62 || c === 92
    ) {
      punct++;
    }
  }
  const cjkRatio = cjk / sample.length;
  const nonCjkLen = len * (1 - cjkRatio);
  const cjkLen = len * cjkRatio;
  const nonCjkPunctRatio = sample.length > cjk ? punct / (sample.length - cjk) : 0;
  const nonCjkCharsPerToken = nonCjkPunctRatio > 0.08 ? 3.45 : 3.85;
  const tokens = cjkLen / 1.55 + nonCjkLen / nonCjkCharsPerToken;
  return Math.max(1, Math.ceil(tokens));
}

function parseYamlFrontmatter(text) {
  if (!text) return { meta: {}, body: '' };
  const normalized = text.replace(/\r\n/g, '\n');
  if (!normalized.startsWith('---')) return { meta: {}, body: normalized };
  const endIdx = normalized.indexOf('\n---', 3);
  if (endIdx < 0) return { meta: {}, body: normalized };
  const rawMeta = normalized.slice(3, endIdx).trim();
  const body = normalized.slice(endIdx + 4).trimStart();
  const meta = {};
  const lines = rawMeta.split('\n');
  for (let i = 0; i < lines.length; i++) {
    const m = /^([a-zA-Z0-9_-]+)\s*:\s*(.*)$/.exec(lines[i]);
    if (!m) continue;
    const key = m[1];
    let val = m[2].trim();
    if (val === '>-' || val === '>' || val === '|-' || val === '|') {
      const parts = [];
      while (i + 1 < lines.length && (/^\s+/.test(lines[i + 1]) || lines[i + 1].trim() === '')) {
        i++;
        const trimmed = lines[i].trim();
        if (trimmed) parts.push(trimmed);
      }
      val = parts.join(' ');
    } else if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1);
    }
    meta[key] = val;
  }
  return { meta, body };
}

function formatAuthor(author) {
  if (!author) return '';
  if (typeof author === 'string') return author.trim();
  if (typeof author === 'object' && author.name) return String(author.name).trim();
  return '';
}

function formatRepo(repo) {
  if (!repo) return '';
  if (typeof repo === 'string') return repo.trim();
  if (typeof repo === 'object' && repo.url) return String(repo.url).trim();
  return '';
}

// ---------------------------------------------------------------------------
// Transcript Parsing (Cached)
// ---------------------------------------------------------------------------

const transcriptCache = new Map();

function readTranscriptSteps(appData, convId) {
  const logsDir = join(appData, 'brain', convId, '.system_generated', 'logs');
  const fullPath = join(logsDir, 'transcript_full.jsonl');
  const compactPath = join(logsDir, 'transcript.jsonl');
  const fullStat = statOf(fullPath);
  const compactStat = statOf(compactPath);
  const targetPath = fullStat.size >= 0 ? fullPath : compactStat.size >= 0 ? compactPath : null;
  if (!targetPath) {
    return { found: false, steps: [], mtime: 0, size: 0 };
  }
  const st = targetPath === fullPath ? fullStat : compactStat;
  const cacheKey = `${targetPath}|${st.mtime}|${st.size}`;
  const hit = transcriptCache.get(targetPath);
  if (hit && hit.key === cacheKey) return hit.val;

  let raw = '';
  try {
    raw = readFileSync(targetPath, 'utf-8');
  } catch {
    return { found: false, steps: [], mtime: 0, size: 0 };
  }

  const steps = [];
  for (const line of raw.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      steps.push(JSON.parse(trimmed));
    } catch {
      // Ignore partial line while transcript is mid-write
    }
  }
  const val = {
    found: true,
    steps,
    mtime: Math.max(fullStat.mtime || 0, compactStat.mtime || 0),
    size: Math.max(0, fullStat.size) + Math.max(0, compactStat.size),
  };
  if (transcriptCache.size > 40) transcriptCache.clear();
  transcriptCache.set(targetPath, { key: cacheKey, val });
  return val;
}

function extractReadPathsFromSteps(steps) {
  // Detect compactions (explicit CHECKPOINT or sharp prompt-token drop)
  let lastCompactionStepIdx = -1;
  let lastCompactionStepNumber = null;
  let compactionCount = 0;
  let prevPromptTokens = 0;
  let sawExplicitSinceLastPlanner = false;

  for (let i = 0; i < steps.length; i++) {
    const s = steps[i];
    if (s.type === 'CHECKPOINT') {
      lastCompactionStepIdx = i;
      lastCompactionStepNumber = s.step_index ?? i;
      compactionCount++;
      sawExplicitSinceLastPlanner = true;
    } else if (s.type === 'PLANNER_RESPONSE') {
      const prompt = (s.input_tokens || 0) + (s.cache_read_tokens || 0);
      if (prompt > 0) {
        if (prevPromptTokens > 0 && !sawExplicitSinceLastPlanner) {
          const drop = prevPromptTokens - prompt;
          if (drop > Math.max(5000, prevPromptTokens * 0.12)) {
            lastCompactionStepIdx = i - 1;
            lastCompactionStepNumber = s.step_index ?? i;
            compactionCount++;
          }
        }
        prevPromptTokens = prompt;
        sawExplicitSinceLastPlanner = false;
      }
    }
  }

  const activeReads = new Map(); // normKey -> { steps: number[], createdAt }
  const compactedReads = new Map(); // normKey -> { steps: number[], createdAt }
  const spawnedSubagents = [];
  const seenSubIds = new Set();

  const recordRead = (map, rawPath, stepNum, createdAt) => {
    if (!rawPath) return;
    const keys = new Set();
    const norm = normPathKey(rawPath);
    if (norm) keys.add(norm);
    // Also record unresolved normalized path (handles symlinks if target changed)
    try {
      const res = resolvePath(rawPath);
      keys.add(IS_WIN ? res.toLowerCase() : res);
    } catch {}
    for (const k of keys) {
      let entry = map.get(k);
      if (!entry) {
        entry = { steps: [], createdAt: createdAt || null };
        map.set(k, entry);
      }
      if (!entry.steps.includes(stepNum)) entry.steps.push(stepNum);
      if (createdAt) entry.createdAt = createdAt;
    }
  };

  for (let i = 0; i < steps.length; i++) {
    const s = steps[i];
    if (s.type !== 'PLANNER_RESPONSE' || !Array.isArray(s.tool_calls)) continue;
    const stepNum = s.step_index ?? i;
    const inActive = i > lastCompactionStepIdx;
    const targetMap = inActive ? activeReads : compactedReads;

    for (let tIdx = 0; tIdx < s.tool_calls.length; tIdx++) {
      const tc = s.tool_calls[tIdx];
      const name = tc?.name || '';
      const args = tc?.args && typeof tc.args === 'object' ? tc.args : {};

      if (name === 'read_file' || name === 'view_file') {
        const p = unquote(args.Path || args.AbsolutePath || '');
        if (p) recordRead(targetMap, p, stepNum, s.created_at);
      } else if (name === 'invoke_subagent') {
        const resultStep = steps[i + 1 + tIdx];
        const resultText = typeof resultStep?.content === 'string' ? resultStep.content : '';
        const matches = resultText.match(UUID_FIND_RE) || [];
        const subId = matches[0] || null;
        if (subId && !seenSubIds.has(subId)) {
          seenSubIds.add(subId);
          spawnedSubagents.push({
            conversationId: subId,
            typeName: unquote(args.TypeName || 'subagent'),
            role: unquote(args.Role || ''),
            stepIndex: stepNum,
            inActiveWindow: inActive,
          });
        }
      }
    }
  }

  return {
    compactionCount,
    lastCompactionStepNumber,
    activeReads,
    compactedReads,
    spawnedSubagents,
  };
}

function collectSubagentReads(appData, spawnedSubagents) {
  const subagentReads = new Map(); // normKey -> Array<{ conversationId, role, typeName, stepIndex, subStepIndex }>
  const subagentMeta = [];

  for (const sub of spawnedSubagents) {
    const tr = readTranscriptSteps(appData, sub.conversationId);
    subagentMeta.push({
      conversationId: sub.conversationId,
      mtime: tr.mtime,
      size: tr.size,
    });
    if (!tr.found) continue;

    const seenInThisSub = new Set();
    for (let i = 0; i < tr.steps.length; i++) {
      const s = tr.steps[i];
      if (s.type !== 'PLANNER_RESPONSE' || !Array.isArray(s.tool_calls)) continue;
      const subStepIndex = s.step_index ?? i;
      for (const tc of s.tool_calls) {
        const name = tc?.name || '';
        if (name !== 'read_file' && name !== 'view_file') continue;
        const args = tc?.args && typeof tc.args === 'object' ? tc.args : {};
        const p = unquote(args.Path || args.AbsolutePath || '');
        if (!p) continue;
        const k = normPathKey(p);
        if (!k || seenInThisSub.has(k)) continue;
        seenInThisSub.add(k);
        let arr = subagentReads.get(k);
        if (!arr) {
          arr = [];
          subagentReads.set(k, arr);
        }
        arr.push({
          conversationId: sub.conversationId,
          role: sub.role || sub.typeName || 'Subagent',
          typeName: sub.typeName || 'subagent',
          stepIndex: sub.stepIndex,
          subStepIndex,
        });
      }
    }
  }

  return { subagentReads, subagentMeta };
}

// ---------------------------------------------------------------------------
// Language Server Plugin Query (Optional Read-Only Enhancement)
// ---------------------------------------------------------------------------

const LS_PLUGINS_TTL_MS = 10000;
let lsPluginsCache = { key: '', fetchedAt: 0, plugins: null };

async function fetchLsPlugins(workspaceUris) {
  const addr = process.env.ANTIGRAVITY_LS_ADDRESS;
  const csrf = process.env.ANTIGRAVITY_CSRF_TOKEN;
  if (!addr || !csrf) return null;
  const key = workspaceUris.join('|');
  const now = Date.now();
  if (lsPluginsCache.plugins && lsPluginsCache.key === key && now - lsPluginsCache.fetchedAt < LS_PLUGINS_TTL_MS) {
    return lsPluginsCache.plugins;
  }
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 1500);
    const res = await fetch(`http://${addr}/exa.language_server_pb.LanguageServerService/GetAllPlugins`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-codeium-csrf-token': csrf,
      },
      body: JSON.stringify(workspaceUris.length ? { workspaceUris } : {}),
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!res.ok) return null;
    const data = await res.json();
    if (Array.isArray(data?.plugins)) {
      lsPluginsCache = { key, fetchedAt: now, plugins: data.plugins };
      return data.plugins;
    }
  } catch {
    // Fall back to filesystem discovery
  }
  return null;
}

// ---------------------------------------------------------------------------
// MCP Cached Schema Estimator (for Plugin MCP Token Breakdown)
// ---------------------------------------------------------------------------

function scanMcpSchemaTokens(appData) {
  const byServer = new Map(); // serverName -> { schemaTokens, instructionTokens, toolCount }
  const mcpDir = join(appData, 'mcp');
  for (const entry of safeReaddirWithTypes(mcpDir)) {
    if (!entry.isFile() || !entry.name.endsWith('.json')) continue;
    const full = join(mcpDir, entry.name);
    const data = readJsonSafe(full);
    if (!data || typeof data !== 'object') continue;
    const name = data.name || data.serverName || basename(entry.name, '.json');
    const tools = Array.isArray(data.tools) ? data.tools : [];
    const schemaTokens = tools.length ? estTextTokens(JSON.stringify(tools)) : 0;
    const instructionTokens = typeof data.instructions === 'string' ? estTextTokens(data.instructions) : 0;
    byServer.set(name, { schemaTokens, instructionTokens, toolCount: tools.length });
  }
  return byServer;
}

// ---------------------------------------------------------------------------
// Plugin & Skill Discovery
// ---------------------------------------------------------------------------

function readConfigPluginOverrides(configDir) {
  const cfg = readJsonSafe(join(configDir, 'config.json'));
  const pluginEnabled = new Map();
  const sidecarEnabled = new Map();
  if (cfg?.plugins && typeof cfg.plugins === 'object') {
    for (const [dir, entry] of Object.entries(cfg.plugins)) {
      if (entry && typeof entry.enabled === 'boolean') {
        pluginEnabled.set(dir, entry.enabled);
      }
    }
  }
  if (cfg?.sidecars && typeof cfg.sidecars === 'object') {
    for (const [id, entry] of Object.entries(cfg.sidecars)) {
      if (entry && typeof entry.enabled === 'boolean') {
        sidecarEnabled.set(id, entry.enabled);
      }
    }
  }
  return { pluginEnabled, sidecarEnabled };
}

function findMarkdownFiles(dir, recursive = false) {
  const out = [];
  for (const entry of safeReaddirWithTypes(dir)) {
    if (IGNORED_DIRS.has(entry.name)) continue;
    const full = join(dir, entry.name);
    if (entry.isFile() && entry.name.endsWith('.md')) {
      out.push(full);
    } else if (recursive && (entry.isDirectory() || entry.isSymbolicLink())) {
      out.push(...findMarkdownFiles(full, true));
    }
  }
  return out;
}

function collectSkillAuxFiles(skillDir, activeReads, compactedReads, subagentReads) {
  const files = [];
  const walk = (dir, depth) => {
    if (depth > 2) return;
    for (const entry of safeReaddirWithTypes(dir)) {
      if (IGNORED_DIRS.has(entry.name) || entry.name.startsWith('.')) continue;
      const full = join(dir, entry.name);
      if (entry.isDirectory() || entry.isSymbolicLink()) {
        // Avoid following broken symlinks or recursing endlessly
        const st = statOf(full);
        if (st.isDir) walk(full, depth + 1);
        else if (st.isFile && entry.name !== 'SKILL.md') {
          addFile(full);
        }
      } else if (entry.isFile() && !(depth === 0 && entry.name === 'SKILL.md')) {
        addFile(full);
      }
    }
  };

  const addFile = (full) => {
    const real = safeRealpath(full) || resolvePath(full);
    const key = normPathKey(real);
    const st = statOf(real);
    if (!st.isFile) return;
    const { text } = readCached(real, 256 * 1024);
    const tokens = text != null ? estTextTokens(text) : Math.ceil(st.size / 4);
    const act = activeReads.get(key);
    const comp = compactedReads.get(key);
    const subs = subagentReads.get(key) || [];
    const relPath = relative(skillDir, full).replace(/\\/g, '/');
    files.push({
      relPath,
      path: real,
      bytes: st.size,
      tokens,
      readActive: Boolean(act),
      activeSteps: act ? act.steps : [],
      readCompacted: Boolean(comp),
      compactedSteps: comp ? comp.steps : [],
      subagentLoads: subs,
    });
  };

  walk(skillDir, 0);
  files.sort((a, b) => {
    if (a.readActive !== b.readActive) return a.readActive ? -1 : 1;
    return a.relPath.localeCompare(b.relPath);
  });
  return files;
}

function inspectPluginSidecars(pluginPath, pluginDirKey, sidecarEnabledMap) {
  const sidecars = [];
  const scRoot = join(pluginPath, 'sidecars');
  for (const entry of safeReaddirWithTypes(scRoot)) {
    if (!entry.isDirectory() && !entry.isSymbolicLink()) continue;
    const manifestPath = join(scRoot, entry.name, 'sidecar.json');
    const manifest = readJsonSafe(manifestPath);
    if (!manifest) continue;
    const id = `${pluginDirKey}/${entry.name}`;
    sidecars.push({
      id,
      folder: entry.name,
      displayName: manifest.display_name || manifest.ui_config?.display_name || entry.name,
      description: manifest.description || '',
      hasWebUi: Boolean(manifest.has_web_ui),
      enabled: sidecarEnabledMap.get(id) ?? null,
      manifestPath: safeRealpath(manifestPath) || manifestPath,
    });
  }
  return sidecars;
}

function discoverAllPlugins(appData, configDir, workspaceDirs, lsPlugins) {
  const { pluginEnabled, sidecarEnabled } = readConfigPluginOverrides(configDir);
  const byPathKey = new Map();
  const byNameSeen = new Set();
  const list = [];

  const registerPlugin = (pPath, origin, lsInfo = null) => {
    const realDir = safeRealpath(pPath) || resolvePath(pPath);
    const key = normPathKey(realDir);
    if (!key || byPathKey.has(key)) return;

    const manifestCandidates = [
      join(realDir, 'plugin.json'),
      join(realDir, '.antigravity-plugin', 'plugin.json'),
      join(realDir, '.gemini-plugin', 'plugin.json'),
    ];
    let manifestPath = null;
    let manifest = null;
    for (const c of manifestCandidates) {
      if (existsSync(c)) {
        manifestPath = c;
        manifest = readJsonSafe(c);
        break;
      }
    }
    if (!manifest && !lsInfo) return;

    const dirKey = basename(pPath);
    const name = manifest?.name || lsInfo?.name || dirKey;
    const displayName = manifest?.displayName || lsInfo?.displayName || name;
    const override = pluginEnabled.get(dirKey);
    let enabled;
    if (lsInfo && typeof lsInfo.disabled === 'boolean') {
      enabled = !lsInfo.disabled;
    } else if (override !== undefined) {
      enabled = override;
    } else {
      enabled = !manifest?.disabled;
    }

    const shadowed = enabled && byNameSeen.has(name);
    if (enabled && !shadowed) byNameSeen.add(name);

    const record = {
      name,
      displayName,
      dir: dirKey,
      path: realDir,
      manifestPath,
      origin, // 'Workspace' | 'User' | 'Builtin'
      isBuiltin: origin === 'Builtin' || Boolean(lsInfo?.isBuiltin),
      enabled,
      shadowed,
      version: manifest?.version || lsInfo?.version || '',
      description: manifest?.description || lsInfo?.description || '',
      author: formatAuthor(manifest?.author || lsInfo?.author),
      homepage: manifest?.homepage || '',
      repository: formatRepo(manifest?.repository),
      sidecars: inspectPluginSidecars(realDir, dirKey, sidecarEnabled),
      hasHooks: existsSync(join(realDir, 'hooks.json')),
    };

    byPathKey.set(key, record);
    list.push(record);
  };

  // 1. Seed from Language Server if available (most authoritative enabled/disabled state)
  if (Array.isArray(lsPlugins)) {
    for (const p of lsPlugins) {
      if (!p) continue;
      const pPath = uriToPath(p.path);
      if (!pPath || !existsSync(pPath)) continue;
      const normP = normPathKey(pPath);
      const builtinRoot = normPathKey(join(appData, 'builtin', 'plugins'));
      const userRoot = normPathKey(join(configDir, 'plugins'));
      let origin = 'Workspace';
      if (p.isBuiltin || (builtinRoot && normP.startsWith(builtinRoot))) origin = 'Builtin';
      else if (userRoot && normP.startsWith(userRoot)) origin = 'User';
      registerPlugin(pPath, origin, p);
    }
  }

  // 2. Scan filesystem roots so disabled/newly added plugins are always visible
  const roots = [
    ...workspaceDirs.map((w) => ({ dir: join(w, '.agents', 'plugins'), origin: 'Workspace' })),
    { dir: join(configDir, 'plugins'), origin: 'User' },
    { dir: join(appData, 'builtin', 'plugins'), origin: 'Builtin' },
  ];
  for (const root of roots) {
    for (const entry of safeReaddirWithTypes(root.dir)) {
      if (!entry.isDirectory() && !entry.isSymbolicLink()) continue;
      const pPath = join(root.dir, entry.name);
      if (!statOf(pPath).isDir) continue;
      registerPlugin(pPath, root.origin, null);
    }
  }

  return list;
}

// ---------------------------------------------------------------------------
// Main Analysis Entrypoint
// ---------------------------------------------------------------------------

export async function analyzeSkillsAndPlugins(appData, convId, { workspaceUris = [] } = {}) {
  const home = homedir();
  const configDir = join(home, '.gemini', 'config');
  const workspaceDirs = workspaceUris.map(uriToPath).filter((p) => p && existsSync(p));

  const transcript = convId ? readTranscriptSteps(appData, convId) : { found: false, steps: [], mtime: 0, size: 0 };
  const readSummary = transcript.found
    ? extractReadPathsFromSteps(transcript.steps)
    : {
        compactionCount: 0,
        lastCompactionStepNumber: null,
        activeReads: new Map(),
        compactedReads: new Map(),
        spawnedSubagents: [],
      };

  const { subagentReads, subagentMeta } = transcript.found
    ? collectSubagentReads(appData, readSummary.spawnedSubagents)
    : { subagentReads: new Map(), subagentMeta: [] };

  const lsPlugins = await fetchLsPlugins(workspaceUris);
  const allPlugins = discoverAllPlugins(appData, configDir, workspaceDirs, lsPlugins);
  const enabledPlugins = allPlugins.filter((p) => p.enabled && !p.shadowed);
  const mcpSchemaByServer = scanMcpSchemaTokens(appData);

  const allowedFiles = {};
  const allowFile = (p) => {
    if (!p) return;
    try {
      allowedFiles[p] = pathToFileURL(p).href;
    } catch {}
  };

  // --- Discover all active-scope Skills ---
  const skillRoots = [
    ...workspaceDirs.map((w) => ({
      dir: join(w, '.agents', 'skills'),
      scope: 'Workspace',
      scopeKind: 'workspace',
      plugin: null,
    })),
    {
      dir: join(configDir, 'skills'),
      scope: 'Global',
      scopeKind: 'global',
      plugin: null,
    },
    ...enabledPlugins.flatMap((p) => {
      const items = [
        {
          dir: join(p.path, 'skills'),
          scope: `Plugin:${p.name}`,
          scopeKind: 'plugin',
          plugin: p,
        },
      ];
      if (existsSync(join(p.path, 'SKILL.md'))) {
        items.push({
          directSkillDir: p.path,
          scope: `Plugin:${p.name}`,
          scopeKind: 'plugin',
          plugin: p,
        });
      }
      return items;
    }),
    {
      dir: join(appData, 'builtin', 'skills'),
      scope: 'Builtin',
      scopeKind: 'builtin',
      plugin: null,
    },
  ];

  const seenSkillNames = new Map(); // name -> primary skill record
  const seenSkillPaths = new Set();
  const skills = [];
  const skillsByPlugin = new Map(); // plugin.path -> Skill[]

  const inspectSkillDir = (skillDir, rootInfo, fromDisabledPlugin = false) => {
    const skillFile = join(skillDir, 'SKILL.md');
    if (!existsSync(skillFile)) return null;
    const real = safeRealpath(skillFile) || resolvePath(skillFile);
    const realKey = normPathKey(real);
    const linkKey = normPathKey(resolvePath(skillFile));

    const { text, size } = readCached(real, 512 * 1024);
    if (text == null) return null;

    const { meta, body } = parseYamlFrontmatter(text);
    const name = (meta.name || basename(skillDir)).trim();
    const description = (meta.description || '').trim();
    const disableSlashCommand = String(meta['disable-slash-command'] || '').toLowerCase() === 'true';
    const lineCount = text.split('\n').length;

    const indexTokens = estTextTokens(`- ${name} (${skillFile}): ${description}`);
    const bodyTokens = estTextTokens(body);

    const activeHit = readSummary.activeReads.get(realKey) || readSummary.activeReads.get(linkKey) || null;
    const compactedHit = readSummary.compactedReads.get(realKey) || readSummary.compactedReads.get(linkKey) || null;
    const subHits = [
      ...(subagentReads.get(realKey) || []),
      ...(linkKey !== realKey ? subagentReads.get(linkKey) || [] : []),
    ];

    const auxFiles = collectSkillAuxFiles(
      safeRealpath(skillDir) || skillDir,
      readSummary.activeReads,
      readSummary.compactedReads,
      subagentReads
    );
    const loadedAuxTokens = auxFiles.reduce((acc, f) => acc + (f.readActive ? f.tokens : 0), 0);
    const anyAuxActive = auxFiles.some((f) => f.readActive);

    let loadState = 'deferred';
    if (activeHit || anyAuxActive) loadState = 'active';
    else if (compactedHit) loadState = 'compacted';
    else if (subHits.length > 0) loadState = 'subagent';

    allowFile(real);
    for (const af of auxFiles) allowFile(af.path);

    const record = {
      name,
      description,
      disableSlashCommand,
      scope: rootInfo.scope,
      scopeKind: rootInfo.scopeKind,
      pluginName: rootInfo.plugin?.name || null,
      pluginDisplayName: rootInfo.plugin?.displayName || null,
      pluginDescription: rootInfo.plugin?.description || null,
      path: real,
      displayPath: skillFile,
      dirPath: safeRealpath(skillDir) || skillDir,
      bytes: size,
      lineCount,
      indexTokens,
      bodyTokens,
      loadedAuxTokens,
      loadState,
      loaded: loadState === 'active',
      activeSteps: activeHit ? activeHit.steps : [],
      compactedSteps: compactedHit ? compactedHit.steps : [],
      subagentLoads: subHits,
      auxFiles,
      shadowedBy: null,
      shadowedAlternatives: [],
    };

    if (fromDisabledPlugin) {
      return record;
    }

    if (seenSkillPaths.has(realKey)) return null;
    seenSkillPaths.add(realKey);

    const existing = seenSkillNames.get(name);
    if (existing) {
      existing.shadowedAlternatives.push({
        scope: rootInfo.scope,
        path: real,
      });
      return null;
    }

    seenSkillNames.set(name, record);
    skills.push(record);
    if (rootInfo.plugin) {
      let arr = skillsByPlugin.get(rootInfo.plugin.path);
      if (!arr) {
        arr = [];
        skillsByPlugin.set(rootInfo.plugin.path, arr);
      }
      arr.push(record);
    }
    return record;
  };

  for (const sr of skillRoots) {
    if (sr.directSkillDir) {
      inspectSkillDir(sr.directSkillDir, sr);
      continue;
    }
    for (const entry of safeReaddirWithTypes(sr.dir)) {
      if (!entry.isDirectory() && !entry.isSymbolicLink()) continue;
      inspectSkillDir(join(sr.dir, entry.name), sr);
    }
  }

  // Compute aggregate skill token stats
  let totalIndexTokens = 0;
  let totalLoadedBodyTokens = 0;
  let totalLoadedAuxTokens = 0;
  let totalDeferredBodyTokens = 0;
  let activeCount = 0;
  let compactedCount = 0;
  let subagentCount = 0;

  for (const sk of skills) {
    totalIndexTokens += sk.indexTokens;
    if (sk.loadState === 'active') {
      activeCount++;
      totalLoadedBodyTokens += sk.bodyTokens;
      totalLoadedAuxTokens += sk.loadedAuxTokens;
    } else {
      totalDeferredBodyTokens += sk.bodyTokens;
      if (sk.loadState === 'compacted') compactedCount++;
      else if (sk.loadState === 'subagent') subagentCount++;
    }
  }

  // Sort skills: active -> compacted -> subagent -> deferred, then by bodyTokens desc
  const loadRank = { active: 0, compacted: 1, subagent: 2, deferred: 3 };
  skills.sort((a, b) => {
    const r = loadRank[a.loadState] - loadRank[b.loadState];
    if (r !== 0) return r;
    const scopeRank = { workspace: 0, global: 1, plugin: 2, builtin: 3 };
    if (a.loadState === 'deferred' && scopeRank[a.scopeKind] !== scopeRank[b.scopeKind]) {
      return scopeRank[a.scopeKind] - scopeRank[b.scopeKind];
    }
    return b.bodyTokens - a.bodyTokens || a.name.localeCompare(b.name);
  });

  // --- Inspect detailed Plugin inventory & token breakdown ---
  const pluginsDetailed = [];
  let totalPluginActiveTokens = 0;
  let totalPluginDeferredTokens = 0;

  for (const p of allPlugins) {
    if (p.manifestPath) allowFile(p.manifestPath);
    for (const sc of p.sidecars) allowFile(sc.manifestPath);

    // Skills belonging to this plugin (including if plugin is disabled)
    let pSkills = skillsByPlugin.get(p.path) || [];
    if (!p.enabled) {
      const disabledSkills = [];
      const rootInfo = { scope: `Plugin:${p.name}`, scopeKind: 'plugin', plugin: p };
      for (const entry of safeReaddirWithTypes(join(p.path, 'skills'))) {
        if (!entry.isDirectory() && !entry.isSymbolicLink()) continue;
        const sk = inspectSkillDir(join(p.path, 'skills', entry.name), rootInfo, true);
        if (sk) disabledSkills.push(sk);
      }
      if (existsSync(join(p.path, 'SKILL.md'))) {
        const sk = inspectSkillDir(p.path, rootInfo, true);
        if (sk) disabledSkills.push(sk);
      }
      pSkills = disabledSkills;
    }

    // Rules
    const pRules = [];
    for (const f of findMarkdownFiles(join(p.path, 'rules'), true)) {
      const real = safeRealpath(f) || f;
      const { text } = readCached(real, 512 * 1024);
      if (text == null) continue;
      const { meta } = parseYamlFrontmatter(text);
      const trigger = meta.trigger || 'always_on';
      const tokens = estTextTokens(text);
      const loaded = p.enabled && (trigger === 'always_on' || readSummary.activeReads.has(normPathKey(real)));
      allowFile(real);
      pRules.push({
        label: basename(f),
        path: real,
        trigger,
        tokens,
        loaded,
      });
    }

    // Agents
    const pAgents = [];
    for (const f of findMarkdownFiles(join(p.path, 'agents'), false)) {
      const real = safeRealpath(f) || f;
      const { text } = readCached(real, 256 * 1024);
      if (text == null) continue;
      const { meta } = parseYamlFrontmatter(text);
      const aName = meta.name || basename(f, '.md');
      const declTokens = estTextTokens(`- ${aName}: ${meta.description || text.slice(0, 200)}`);
      allowFile(real);
      pAgents.push({
        name: aName,
        description: (meta.description || '').trim(),
        path: real,
        declTokens,
        fullTokens: estTextTokens(text),
      });
    }

    // MCP servers
    const pMcpServers = [];
    const mcpCfgPath = join(p.path, 'mcp_config.json');
    const mcpCfg = readJsonSafe(mcpCfgPath);
    if (mcpCfg?.mcpServers && typeof mcpCfg.mcpServers === 'object') {
      allowFile(mcpCfgPath);
      for (const [sName, sDef] of Object.entries(mcpCfg.mcpServers)) {
        const schema =
          mcpSchemaByServer.get(`${p.name}_${sName}`) ||
          mcpSchemaByServer.get(sName) ||
          { schemaTokens: 0, instructionTokens: 0, toolCount: 0 };
        pMcpServers.push({
          name: sName,
          disabled: Boolean(sDef?.disabled),
          toolCount: schema.toolCount,
          schemaTokens: schema.schemaTokens,
          instructionTokens: schema.instructionTokens,
          configPath: mcpCfgPath,
        });
      }
    }

    // Token totals for this plugin
    const skillIndexTok = pSkills.reduce((a, s) => a + s.indexTokens, 0);
    const skillLoadedTok = pSkills.reduce(
      (a, s) => a + (s.loadState === 'active' ? s.bodyTokens + s.loadedAuxTokens : 0),
      0
    );
    const skillDeferredTok = pSkills.reduce(
      (a, s) => a + (s.loadState === 'active' ? 0 : s.bodyTokens),
      0
    );
    const rulesActiveTok = pRules.reduce((a, r) => a + (r.trigger === 'always_on' || r.loaded ? r.tokens : 0), 0);
    const rulesDeferredTok = pRules.reduce((a, r) => a + (r.trigger === 'always_on' || r.loaded ? 0 : r.tokens), 0);
    const agentsDeclTok = pAgents.reduce((a, ag) => a + ag.declTokens, 0);
    const mcpActiveTok = pMcpServers.reduce(
      (a, m) => a + (m.disabled ? 0 : m.schemaTokens + m.instructionTokens),
      0
    );

    const activeTokens = p.enabled
      ? skillIndexTok + skillLoadedTok + rulesActiveTok + agentsDeclTok + mcpActiveTok
      : 0;
    const deferredTokens = p.enabled ? skillDeferredTok + rulesDeferredTok : 0;
    const potentialTokens = !p.enabled
      ? skillIndexTok + rulesActiveTok + agentsDeclTok + mcpActiveTok
      : 0;

    totalPluginActiveTokens += activeTokens;
    totalPluginDeferredTokens += deferredTokens;

    pluginsDetailed.push({
      name: p.name,
      displayName: p.displayName,
      dir: p.dir,
      path: p.path,
      manifestPath: p.manifestPath,
      origin: p.origin,
      isBuiltin: p.isBuiltin,
      enabled: p.enabled,
      shadowed: p.shadowed,
      version: p.version,
      description: p.description,
      author: p.author,
      homepage: p.homepage,
      repository: p.repository,
      hasHooks: p.hasHooks,
      tokens: {
        active: activeTokens,
        deferred: deferredTokens,
        potential: potentialTokens,
        skillIndex: skillIndexTok,
        skillLoaded: skillLoadedTok,
        skillDeferred: skillDeferredTok,
        rulesActive: rulesActiveTok,
        agentsDecl: agentsDeclTok,
        mcpActive: mcpActiveTok,
      },
      components: {
        skills: pSkills.map((s) => ({
          name: s.name,
          description: s.description,
          path: s.path,
          indexTokens: s.indexTokens,
          bodyTokens: s.bodyTokens,
          loadState: s.loadState,
        })),
        rules: pRules,
        agents: pAgents,
        mcpServers: pMcpServers,
        sidecars: p.sidecars,
      },
    });
  }

  // Sort plugins: enabled user/workspace -> enabled builtin -> disabled
  const originRank = { Workspace: 0, User: 1, Builtin: 2 };
  pluginsDetailed.sort((a, b) => {
    if (a.enabled !== b.enabled) return a.enabled ? -1 : 1;
    if (originRank[a.origin] !== originRank[b.origin]) return originRank[a.origin] - originRank[b.origin];
    return b.tokens.active - a.tokens.active || a.displayName.localeCompare(b.displayName);
  });

  const enabledPluginCount = pluginsDetailed.filter((p) => p.enabled).length;
  const disabledPluginCount = pluginsDetailed.length - enabledPluginCount;

  return {
    found: true,
    conversationId: convId || null,
    hasTranscript: transcript.found,
    platform: process.platform,
    transcriptStats: {
      mtime: transcript.mtime,
      size: transcript.size,
      stepCount: transcript.steps.length,
    },
    compaction: {
      count: readSummary.compactionCount,
      lastStep: readSummary.lastCompactionStepNumber,
    },
    subagentMeta,
    summary: {
      skillsTotal: skills.length,
      skillsActive: activeCount,
      skillsCompacted: compactedCount,
      skillsSubagent: subagentCount,
      skillsIndexTokens: totalIndexTokens,
      skillsLoadedBodyTokens: totalLoadedBodyTokens,
      skillsLoadedAuxTokens: totalLoadedAuxTokens,
      skillsDeferredTokens: totalDeferredBodyTokens,
      skillsActiveTotalTokens: totalIndexTokens + totalLoadedBodyTokens + totalLoadedAuxTokens,
      pluginsTotal: pluginsDetailed.length,
      pluginsEnabled: enabledPluginCount,
      pluginsDisabled: disabledPluginCount,
      pluginsActiveTokens: totalPluginActiveTokens,
      pluginsDeferredTokens: totalPluginDeferredTokens,
    },
    skills,
    plugins: pluginsDetailed,
    allowedFiles,
  };
}
