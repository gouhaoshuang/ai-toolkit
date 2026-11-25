/**
 * Skills Panel frontend.
 * Dual-tab (Skills + Plugins) live inspector with ETag polling, host theme sync,
 * compaction/subagent tracking, search/filter, and one-click file/subagent open.
 */
(() => {
  const POLL_MS = 1400;
  const $ = (id) => document.getElementById(id);

  const state = {
    etag: '',
    snap: null,
    workspaces: [],
    fallbackConvId: new URLSearchParams(location.search).get('conversationId') || '',
    tab: localStorage.getItem('skills_panel_tab') === 'plugins' ? 'plugins' : 'skills',
    skillFilter: 'all',
    skillQuery: '',
    pluginFilter: 'all',
    pluginQuery: '',
    expandedSkills: new Set(), // `${section}:${skill.path}`
    expandedPlugins: new Set(), // plugin.path
    timer: null,
  };

  // ---------- Host Theme Sync ----------
  function syncScheme() {
    const probe = document.createElement('span');
    probe.style.cssText = 'position:absolute;visibility:hidden;color:var(--background, #f7f7f8)';
    document.documentElement.appendChild(probe);
    const c = getComputedStyle(probe).color;
    probe.remove();
    const nums = (c.match(/[\d.]+/g) || []).map(Number);
    if (nums.length < 3) return;
    const scale = c.startsWith('color(') ? 1 : 255;
    const [r, g, b] = nums.slice(0, 3).map((v) => v / scale);
    const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
    const theme = lum < 0.5 ? 'dark' : 'light';
    if (document.documentElement.dataset.theme !== theme) {
      document.documentElement.dataset.theme = theme;
    }
  }
  syncScheme();
  new MutationObserver(syncScheme).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['style'],
  });

  // ---------- Helpers ----------
  const esc = (s) =>
    String(s ?? '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[c]));

  function fmtTok(n) {
    const v = Number(n) || 0;
    if (v >= 1000000) return `${(v / 1000000).toFixed(1)}M`;
    if (v >= 1000) return `${(v / 1000).toFixed(1)}k`;
    return String(v);
  }

  function fmtBytes(b) {
    const v = Number(b) || 0;
    if (v >= 1024 * 1024) return `${(v / (1024 * 1024)).toFixed(1)} MB`;
    if (v >= 1024) return `${(v / 1024).toFixed(1)} KB`;
    return `${v} B`;
  }

  function fmtSteps(steps) {
    if (!Array.isArray(steps) || !steps.length) return '';
    if (steps.length <= 3) return `Step ${steps.join(', ')}`;
    return `Step ${steps[0]}…${steps[steps.length - 1]} (${steps.length}次)`;
  }

  const CHEV_SVG =
    '<svg class="chev" viewBox="0 0 12 12" aria-hidden="true"><path d="M4.2 2.5 7.8 6l-3.6 3.5"/></svg>';
  const OPEN_SVG =
    '<svg width="13" height="13" viewBox="0 0 16 16" aria-hidden="true"><path d="M6.5 3.5H4a1 1 0 0 0-1 1v7.5a1 1 0 0 0 1 1h7.5a1 1 0 0 0 1-1V9.5"/><path d="M9.5 3h3.5v3.5M13 3l-5.5 5.5"/></svg>';

  function openFile(path) {
    const uri = state.snap?.allowedFiles?.[path];
    if (!uri) return;
    window.sidecar?.ui?.toggleAuxPane?.({ tabType: 'fileView', uri });
  }

  function openConversation(convId) {
    if (!convId) return;
    window.sidecar?.ui?.toggleConversation?.(convId);
  }

  async function copyText(text, btn) {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.cssText = 'position:fixed;opacity:0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); } catch {}
      ta.remove();
    }
    if (btn) {
      const old = btn.textContent;
      btn.textContent = '已复制';
      setTimeout(() => { btn.textContent = old; }, 1200);
    }
  }

  // ---------- Skill Card Renderer ----------
  function renderStatusBadge(sk) {
    if (sk.loadState === 'active') {
      const st = fmtSteps(sk.activeSteps);
      return `<span class="tag tag-active" title="当前有效上下文窗口内已读入">已加载${st ? ' · ' + esc(st) : ''}</span>`;
    }
    if (sk.loadState === 'compacted') {
      const st = fmtSteps(sk.compactedSteps);
      return `<span class="tag tag-compacted" title="在 /compact 压缩之前曾读入，当前已被压缩摘要替代">压缩前曾加载${st ? ' · ' + esc(st) : ''}</span>`;
    }
    if (sk.loadState === 'subagent') {
      const cnt = sk.subagentLoads?.length || 1;
      return `<span class="tag tag-subagent" title="由当前会话派生的子 Agent 读取">子 Agent 加载${cnt > 1 ? ' ×' + cnt : ''}</span>`;
    }
    return '';
  }

  function renderSkillCard(sk, sectionPrefix) {
    const key = `${sectionPrefix}:${sk.path}`;
    const isOpen = state.expandedSkills.has(key);
    const stateCls = sk.loadState !== 'deferred' ? `state-${sk.loadState}` : '';
    const loadedTotal = sk.bodyTokens + (sk.loadedAuxTokens || 0);
    const rightTok =
      sk.loadState === 'active'
        ? `<span class="tok-idx">${fmtTok(sk.indexTokens)} idx</span> · <span class="tok-hi">${fmtTok(loadedTotal)} loaded</span>`
        : `<span class="tok-idx">${fmtTok(sk.indexTokens)} idx</span> · ${fmtTok(sk.bodyTokens)} def`;

    let detailHtml = '';
    if (isOpen) {
      const loadHistoryParts = [];
      if (sk.activeSteps?.length) {
        loadHistoryParts.push(`<span>当前窗口读取：<strong>${esc(fmtSteps(sk.activeSteps))}</strong></span>`);
      }
      if (sk.compactedSteps?.length) {
        loadHistoryParts.push(`<span>压缩前曾读取：<strong>${esc(fmtSteps(sk.compactedSteps))}</strong></span>`);
      }
      if (!loadHistoryParts.length && !sk.subagentLoads?.length) {
        loadHistoryParts.push('<span>本次会话尚未读取正文（仅系统提示词索引常驻）</span>');
      }

      const subagentHtml = sk.subagentLoads?.length
        ? `<div class="sub-list">
            <div class="sub-list-title">子 Agent 读取记录</div>
            <div class="comp-strip" style="margin-left:0">
              ${sk.subagentLoads
                .map(
                  (sub) =>
                    `<button type="button" class="link-chip" data-open-conv="${esc(sub.conversationId)}" title="点击打开子 Agent 会话">${esc(sub.role || sub.typeName)} · 主 Step ${sub.stepIndex}</button>`
                )
                .join('')}
            </div>
          </div>`
        : '';

      const pluginNoteHtml = sk.pluginName
        ? `<div class="detail-note">
            <strong>所属插件：${esc(sk.pluginDisplayName || sk.pluginName)}</strong>
            ${sk.pluginDescription ? ` — ${esc(sk.pluginDescription)}` : ''}
          </div>`
        : '';

      const auxHtml = sk.auxFiles?.length
        ? `<div>
            <div class="sub-list-title">附属文件（${sk.auxFiles.length}）</div>
            <div class="sub-list">
              ${sk.auxFiles
                .map((af) => {
                  const statusTag = af.readActive
                    ? `<span class="tag tag-active">已读 ${esc(fmtSteps(af.activeSteps))}</span>`
                    : af.readCompacted
                    ? `<span class="tag tag-compacted">压缩前已读</span>`
                    : '';
                  return `<div class="sub-row">
                    <div class="sub-row-left">
                      <span class="sub-row-name" title="${esc(af.relPath)}">${esc(af.relPath)}</span>
                      ${statusTag}
                    </div>
                    <div class="sub-row-right num">
                      <span>${fmtTok(af.tokens)} tok</span>
                      <button type="button" class="icon-btn" data-open-file="${esc(af.path)}" title="打开文件">${OPEN_SVG}</button>
                    </div>
                  </div>`;
                })
                .join('')}
            </div>
          </div>`
        : '';

      const shadowHtml = sk.shadowedAlternatives?.length
        ? `<div class="detail-note">
            <strong>同名覆盖提示：</strong>已优先使用当前 ${esc(sk.scope)} 版本，跳过低优先级同名项：
            ${sk.shadowedAlternatives.map((x) => esc(`${x.scope} (${x.path})`)).join('；')}
          </div>`
        : '';

      detailHtml = `<div class="item-detail">
        <p class="detail-desc">${esc(sk.description || '（无 description 说明）')}</p>
        ${pluginNoteHtml}
        <div class="detail-kv num">
          <span>索引常驻：<strong>${fmtTok(sk.indexTokens)} tok</strong></span>
          <span>正文大小：<strong>${fmtTok(sk.bodyTokens)} tok</strong></span>
          ${sk.loadedAuxTokens ? `<span>已读附属文件：<strong>${fmtTok(sk.loadedAuxTokens)} tok</strong></span>` : ''}
          <span>文件：<strong>${sk.lineCount} 行 · ${fmtBytes(sk.bytes)}</strong></span>
          <span>斜杠命令：<strong>${sk.disableSlashCommand ? '已禁用' : '/' + esc(sk.name)}</strong></span>
        </div>
        <div class="detail-kv num">${loadHistoryParts.join('')}</div>
        ${subagentHtml}
        <div class="path-row">
          <span class="path-text" title="${esc(sk.path)}">${esc(sk.path)}</span>
          <div class="path-actions">
            <button type="button" class="mini-btn" data-copy-text="${esc(sk.path)}">复制路径</button>
            <button type="button" class="mini-btn" data-open-file="${esc(sk.path)}">打开 SKILL.md</button>
          </div>
        </div>
        ${auxHtml}
        ${shadowHtml}
      </div>`;
    }

    return `<article class="item-card ${stateCls} ${isOpen ? 'open' : ''}" data-skill-key="${esc(key)}">
      <div class="item-head" data-toggle-skill="${esc(key)}">
        <div class="item-top">
          <div class="item-left">
            ${CHEV_SVG}
            <span class="item-name">${esc(sk.name)}</span>
            <span class="tag tag-scope">${esc(sk.scope)}</span>
            ${renderStatusBadge(sk)}
          </div>
          <div class="item-right">
            <span class="tok-meta num">${rightTok}</span>
            <button type="button" class="icon-btn" data-open-file="${esc(sk.path)}" title="打开 SKILL.md">${OPEN_SVG}</button>
          </div>
        </div>
        <div class="item-desc">${esc(sk.description || '暂无简介')}</div>
      </div>
      ${detailHtml}
    </article>`;
  }

  // ---------- Plugin Card Renderer ----------
  function renderPluginCard(pl) {
    const isOpen = state.expandedPlugins.has(pl.path);
    const statusBadge = pl.enabled
      ? '<span class="tag tag-active">已启用</span>'
      : '<span class="tag tag-disabled">已禁用</span>';

    const originLabel =
      pl.origin === 'Workspace' ? 'Workspace' : pl.origin === 'Builtin' ? 'Builtin' : 'User';

    const tokMeta = pl.enabled
      ? `<span class="tok-idx">${fmtTok(pl.tokens.active)} 占用</span>${
          pl.tokens.deferred > 0 ? ` · ${fmtTok(pl.tokens.deferred)} 延迟` : ''
        }`
      : `0 占用${pl.tokens.potential > 0 ? `（启用约 ${fmtTok(pl.tokens.potential)}）` : ''}`;

    const compChips = [];
    if (pl.components.skills.length) compChips.push(`${pl.components.skills.length} Skill`);
    if (pl.components.sidecars.length) compChips.push(`${pl.components.sidecars.length} Sidecar`);
    if (pl.components.rules.length) compChips.push(`${pl.components.rules.length} Rule`);
    if (pl.components.agents.length) compChips.push(`${pl.components.agents.length} Agent`);
    if (pl.components.mcpServers.length) compChips.push(`${pl.components.mcpServers.length} MCP`);
    if (pl.hasHooks) compChips.push('Hooks');
    if (!compChips.length) compChips.push('无内置组件');

    let detailHtml = '';
    if (isOpen) {
      const tokBoxes = [
        { label: 'Skill 索引', val: pl.tokens.skillIndex },
        { label: 'Skill 已加载正文', val: pl.tokens.skillLoaded },
        { label: 'Skill 延迟正文', val: pl.tokens.skillDeferred },
        { label: 'Rules 常驻', val: pl.tokens.rulesActive },
        { label: 'Agents 声明', val: pl.tokens.agentsDecl },
        { label: 'MCP Schema', val: pl.tokens.mcpActive },
      ].filter((x) => x.val > 0);

      const skillsHtml = pl.components.skills.length
        ? `<div>
            <div class="sub-list-title">包含 Skills（${pl.components.skills.length}）</div>
            <div class="sub-list">
              ${pl.components.skills
                .map((s) => {
                  const st =
                    s.loadState === 'active'
                      ? '<span class="tag tag-active">已加载</span>'
                      : s.loadState === 'compacted'
                      ? '<span class="tag tag-compacted">压缩前曾加载</span>'
                      : '';
                  return `<div class="sub-row">
                    <div class="sub-row-left">
                      <span class="sub-row-name">${esc(s.name)}</span>
                      ${st}
                    </div>
                    <div class="sub-row-right num">
                      <span>${fmtTok(s.indexTokens)} idx · ${fmtTok(s.bodyTokens)} body</span>
                      <button type="button" class="icon-btn" data-open-file="${esc(s.path)}" title="打开 SKILL.md">${OPEN_SVG}</button>
                    </div>
                  </div>`;
                })
                .join('')}
            </div>
          </div>`
        : '';

      const rulesHtml = pl.components.rules.length
        ? `<div>
            <div class="sub-list-title">Rules（${pl.components.rules.length}）</div>
            <div class="sub-list">
              ${pl.components.rules
                .map(
                  (r) => `<div class="sub-row">
                    <div class="sub-row-left">
                      <span class="sub-row-name">${esc(r.label)}</span>
                      <span class="tag tag-scope">${esc(r.trigger)}</span>
                    </div>
                    <div class="sub-row-right num">
                      <span>${fmtTok(r.tokens)} tok</span>
                      <button type="button" class="icon-btn" data-open-file="${esc(r.path)}" title="打开规则文件">${OPEN_SVG}</button>
                    </div>
                  </div>`
                )
                .join('')}
            </div>
          </div>`
        : '';

      const mcpHtml = pl.components.mcpServers.length
        ? `<div>
            <div class="sub-list-title">MCP Servers（${pl.components.mcpServers.length}）</div>
            <div class="sub-list">
              ${pl.components.mcpServers
                .map(
                  (m) => `<div class="sub-row">
                    <div class="sub-row-left">
                      <span class="sub-row-name">${esc(m.name)}</span>
                      ${m.disabled ? '<span class="tag tag-disabled">disabled</span>' : ''}
                    </div>
                    <div class="sub-row-right num">
                      <span>${m.toolCount ? `${m.toolCount} tools · ` : ''}${fmtTok(m.schemaTokens + m.instructionTokens)} tok</span>
                      <button type="button" class="icon-btn" data-open-file="${esc(m.configPath)}" title="打开 mcp_config.json">${OPEN_SVG}</button>
                    </div>
                  </div>`
                )
                .join('')}
            </div>
          </div>`
        : '';

      const sidecarsHtml = pl.components.sidecars.length
        ? `<div>
            <div class="sub-list-title">Sidecars（${pl.components.sidecars.length}）</div>
            <div class="sub-list">
              ${pl.components.sidecars
                .map(
                  (sc) => `<div class="sub-row">
                    <div class="sub-row-left">
                      <span class="sub-row-name">${esc(sc.displayName)}</span>
                      ${sc.hasWebUi ? '<span class="tag tag-scope">Web UI</span>' : ''}
                      ${sc.enabled === true ? '<span class="tag tag-active">已开启</span>' : sc.enabled === false ? '<span class="tag tag-disabled">未开启</span>' : ''}
                    </div>
                    <div class="sub-row-right">
                      <span class="item-subname">${esc(sc.id)}</span>
                      <button type="button" class="icon-btn" data-open-file="${esc(sc.manifestPath)}" title="打开 sidecar.json">${OPEN_SVG}</button>
                    </div>
                  </div>`
                )
                .join('')}
            </div>
          </div>`
        : '';

      const agentsHtml = pl.components.agents.length
        ? `<div>
            <div class="sub-list-title">Custom Agents（${pl.components.agents.length}）</div>
            <div class="sub-list">
              ${pl.components.agents
                .map(
                  (ag) => `<div class="sub-row">
                    <div class="sub-row-left"><span class="sub-row-name">${esc(ag.name)}</span></div>
                    <div class="sub-row-right num">
                      <span>${fmtTok(ag.declTokens)} decl</span>
                      <button type="button" class="icon-btn" data-open-file="${esc(ag.path)}" title="打开 Agent 定义">${OPEN_SVG}</button>
                    </div>
                  </div>`
                )
                .join('')}
            </div>
          </div>`
        : '';

      detailHtml = `<div class="item-detail">
        <p class="detail-desc">${esc(pl.description || '（plugin.json 未填写 description）')}</p>
        <div class="detail-kv num">
          <span>目录名：<strong>${esc(pl.dir)}</strong></span>
          ${pl.author ? `<span>作者：<strong>${esc(pl.author)}</strong></span>` : ''}
          ${pl.version ? `<span>版本：<strong>v${esc(pl.version)}</strong></span>` : ''}
          ${pl.repository ? `<span>仓库：<strong>${esc(pl.repository)}</strong></span>` : ''}
        </div>
        ${
          tokBoxes.length
            ? `<div class="tok-breakdown num">${tokBoxes
                .map((b) => `<span class="tok-box">${esc(b.label)} <strong>${fmtTok(b.val)}</strong></span>`)
                .join('')}</div>`
            : ''
        }
        <div class="path-row">
          <span class="path-text" title="${esc(pl.path)}">${esc(pl.path)}</span>
          <div class="path-actions">
            <button type="button" class="mini-btn" data-copy-text="${esc(pl.path)}">复制目录</button>
            ${
              pl.manifestPath
                ? `<button type="button" class="mini-btn" data-open-file="${esc(pl.manifestPath)}">打开 plugin.json</button>`
                : ''
            }
          </div>
        </div>
        ${skillsHtml}
        ${sidecarsHtml}
        ${rulesHtml}
        ${agentsHtml}
        ${mcpHtml}
      </div>`;
    }

    const nameDiff = pl.displayName !== pl.name ? `<span class="item-subname">${esc(pl.name)}</span>` : '';

    return `<article class="item-card ${pl.enabled ? '' : 'plugin-disabled'} ${isOpen ? 'open' : ''}">
      <div class="item-head" data-toggle-plugin="${esc(pl.path)}">
        <div class="item-top">
          <div class="item-left">
            ${CHEV_SVG}
            <span class="item-name">${esc(pl.displayName)}</span>
            ${nameDiff}
            ${pl.version ? `<span class="tag-ver">v${esc(pl.version)}</span>` : ''}
            ${statusBadge}
            <span class="tag tag-scope">${originLabel}</span>
          </div>
          <div class="item-right">
            <span class="tok-meta num">${tokMeta}</span>
            ${
              pl.manifestPath
                ? `<button type="button" class="icon-btn" data-open-file="${esc(pl.manifestPath)}" title="打开 plugin.json">${OPEN_SVG}</button>`
                : ''
            }
          </div>
        </div>
        <div class="item-desc">${esc(pl.description || '暂无插件简介')}${pl.author ? ` · by ${esc(pl.author)}` : ''}</div>
        <div class="comp-strip">${compChips.map((c) => `<span class="comp-chip">${esc(c)}</span>`).join('')}</div>
      </div>
      ${detailHtml}
    </article>`;
  }

  // ---------- Main Render ----------
  function renderSkillsTab(snap) {
    const sum = snap.summary;

    // Headline & compaction badge
    const subParts = [];
    if (sum.skillsCompacted > 0) subParts.push(`压缩前 ${sum.skillsCompacted}`);
    if (sum.skillsSubagent > 0) subParts.push(`子 Agent ${sum.skillsSubagent}`);
    $('sk-loaded-headline').textContent = `当前已加载 ${sum.skillsActive} / ${sum.skillsTotal} 个 Skill${
      subParts.length ? `（另 ${subParts.join(' · ')}）` : ''
    }`;
    $('sk-total-active-tok').textContent = `${fmtTok(sum.skillsActiveTotalTokens)} tok 占用`;

    const compPill = $('sk-compaction-pill');
    if (snap.compaction?.count > 0) {
      compPill.textContent = `已压缩 ${snap.compaction.count} 次`;
      compPill.title = snap.compaction.lastStep != null ? `最近一次压缩在 Step ${snap.compaction.lastStep}` : '';
      compPill.classList.remove('hidden');
    } else {
      compPill.classList.add('hidden');
    }

    // Stacked bar: loaded body+aux vs index vs deferred
    const loadedTok = sum.skillsLoadedBodyTokens + sum.skillsLoadedAuxTokens;
    const indexTok = sum.skillsIndexTokens;
    const deferredTok = sum.skillsDeferredTokens;
    const totalPool = Math.max(1, loadedTok + indexTok + deferredTok);
    const segs = [];
    if (loadedTok > 0) {
      segs.push(
        `<div class="bar-seg seg-loaded" style="width:${Math.max(1.5, (loadedTok / totalPool) * 100).toFixed(2)}%" title="已加载正文与附属文件: ${fmtTok(loadedTok)} tok"></div>`
      );
    }
    if (indexTok > 0) {
      segs.push(
        `<div class="bar-seg seg-index" style="width:${Math.max(1.5, (indexTok / totalPool) * 100).toFixed(2)}%" title="系统提示词索引常驻: ${fmtTok(indexTok)} tok"></div>`
      );
    }
    if (deferredTok > 0) {
      segs.push(
        `<div class="bar-seg seg-deferred" style="width:${Math.max(1.5, (deferredTok / totalPool) * 100).toFixed(2)}%" title="未加载延迟正文（未占用上下文）: ${fmtTok(deferredTok)} tok"></div>`
      );
    }
    $('sk-token-bar').innerHTML = segs.join('');
    $('leg-loaded').textContent = `${fmtTok(loadedTok)} tok`;
    $('leg-index').textContent = `${fmtTok(indexTok)} tok`;
    $('leg-deferred').textContent = `${fmtTok(deferredTok)} tok`;

    // Section 1: Active / Session Activity
    const activeSkills = snap.skills.filter((s) => s.loadState !== 'deferred');
    $('active-count-label').textContent = activeSkills.length
      ? `${sum.skillsActive} 当前有效${sum.skillsCompacted ? ` · ${sum.skillsCompacted} 压缩前` : ''}${
          sum.skillsSubagent ? ` · ${sum.skillsSubagent} 子 Agent` : ''
        }`
      : '0 条触发';

    if (activeSkills.length) {
      $('active-skills-list').innerHTML = activeSkills.map((s) => renderSkillCard(s, 'act')).join('');
    } else {
      $('active-skills-list').innerHTML = `<div class="empty-hint">
        当前会话尚未读取任何 Skill 正文，仅在系统提示词中常驻了 ${sum.skillsTotal} 个 Skill 索引（共 ${fmtTok(indexTok)} tok）。
      </div>`;
    }

    // Section 2: All Discovered Skills (filtered)
    const q = state.skillQuery.trim().toLowerCase();
    const filtered = snap.skills.filter((s) => {
      if (state.skillFilter === 'loaded' && s.loadState === 'deferred') return false;
      if (
        ['workspace', 'global', 'plugin', 'builtin'].includes(state.skillFilter) &&
        s.scopeKind !== state.skillFilter
      ) {
        return false;
      }
      if (q) {
        const hay = `${s.name} ${s.description} ${s.scope} ${s.pluginName || ''} ${s.pluginDisplayName || ''}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    $('all-skills-count').textContent = `${filtered.length} / ${snap.skills.length}`;
    if (filtered.length) {
      $('all-skills-list').innerHTML = filtered.map((s) => renderSkillCard(s, 'all')).join('');
    } else {
      $('all-skills-list').innerHTML = '<div class="empty-hint">没有匹配当前筛选条件的 Skill。</div>';
    }
  }

  function renderPluginsTab(snap) {
    const sum = snap.summary;
    $('pl-headline').textContent = `共 ${sum.pluginsTotal} 个插件（${sum.pluginsEnabled} 启用 · ${sum.pluginsDisabled} 禁用）`;
    $('pl-active-tok').textContent = `${fmtTok(sum.pluginsActiveTokens)} tok 占用`;
    $('pl-subline').textContent = `启用插件延迟未加载部分：${fmtTok(sum.pluginsDeferredTokens)} tok（按需读取后才计入上下文）`;

    const q = state.pluginQuery.trim().toLowerCase();
    const filtered = snap.plugins.filter((p) => {
      if (state.pluginFilter === 'enabled' && !p.enabled) return false;
      if (state.pluginFilter === 'disabled' && p.enabled) return false;
      if (state.pluginFilter === 'user' && p.isBuiltin) return false;
      if (state.pluginFilter === 'builtin' && !p.isBuiltin) return false;
      if (q) {
        const compNames = [
          ...p.components.skills.map((s) => s.name),
          ...p.components.mcpServers.map((m) => m.name),
          ...p.components.sidecars.map((sc) => sc.displayName),
        ].join(' ');
        const hay = `${p.displayName} ${p.name} ${p.dir} ${p.description} ${p.author} ${compNames}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    if (filtered.length) {
      $('plugins-list').innerHTML = filtered.map(renderPluginCard).join('');
    } else {
      $('plugins-list').innerHTML = '<div class="empty-hint">没有匹配当前筛选条件的插件。</div>';
    }
  }

  function applyTabUI() {
    const isSkills = state.tab === 'skills';
    $('tab-skills').classList.toggle('on', isSkills);
    $('tab-skills').setAttribute('aria-selected', String(isSkills));
    $('tab-plugins').classList.toggle('on', !isSkills);
    $('tab-plugins').setAttribute('aria-selected', String(!isSkills));
    $('view-skills').classList.toggle('hidden', !isSkills);
    $('view-plugins').classList.toggle('hidden', isSkills);
  }

  function render(snap) {
    state.snap = snap;
    $('loading').classList.add('hidden');
    $('panel').classList.remove('hidden');

    $('badge-skills').textContent = `${snap.summary.skillsActive} / ${snap.summary.skillsTotal}`;
    $('badge-plugins').textContent = `${snap.summary.pluginsEnabled}`;

    const plat = snap.platform === 'win32' ? 'Win' : snap.platform === 'darwin' ? 'macOS' : 'Linux';
    const convShort = snap.conversationId ? snap.conversationId.slice(0, 8) : '无会话';
    $('session-meta').textContent = `${plat} · ${convShort}`;
    $('session-meta').title = snap.conversationId ? `会话 ID: ${snap.conversationId}` : '未检测到活跃会话';

    applyTabUI();
    renderSkillsTab(snap);
    renderPluginsTab(snap);
  }

  // ---------- Polling ----------
  async function poll(force = false) {
    const conv = window.sidecar?.conversationId || state.fallbackConvId || '';
    const qs = new URLSearchParams();
    if (conv) qs.set('conversationId', conv);
    if (state.workspaces.length) qs.set('workspaces', state.workspaces.join('|'));
    if (!force && state.etag) qs.set('etag', state.etag);

    try {
      const f = window.sidecar?.fetch ? window.sidecar.fetch.bind(window.sidecar) : fetch;
      const res = await f(`/api/skills?${qs.toString()}`, { method: 'GET' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.unchanged) return;
      state.etag = data.etag || '';
      render(data);
    } catch {
      // keep existing UI during transient sidecar reconnect
    }
  }

  function schedulePoll() {
    clearTimeout(state.timer);
    const delay = document.hidden ? 6000 : POLL_MS;
    state.timer = setTimeout(async () => {
      await poll(false);
      schedulePoll();
    }, delay);
  }

  // ---------- Event Wiring ----------
  document.querySelectorAll('.tab-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      state.tab = btn.dataset.tab === 'plugins' ? 'plugins' : 'skills';
      try { localStorage.setItem('skills_panel_tab', state.tab); } catch {}
      applyTabUI();
    });
  });

  $('skill-filters').addEventListener('click', (e) => {
    const btn = e.target.closest('.pill');
    if (!btn) return;
    state.skillFilter = btn.dataset.filter || 'all';
    $('skill-filters').querySelectorAll('.pill').forEach((p) => p.classList.toggle('on', p === btn));
    if (state.snap) renderSkillsTab(state.snap);
  });

  $('skill-search').addEventListener('input', (e) => {
    state.skillQuery = e.target.value || '';
    if (state.snap) renderSkillsTab(state.snap);
  });

  $('plugin-filters').addEventListener('click', (e) => {
    const btn = e.target.closest('.pill');
    if (!btn) return;
    state.pluginFilter = btn.dataset.filter || 'all';
    $('plugin-filters').querySelectorAll('.pill').forEach((p) => p.classList.toggle('on', p === btn));
    if (state.snap) renderPluginsTab(state.snap);
  });

  $('plugin-search').addEventListener('input', (e) => {
    state.pluginQuery = e.target.value || '';
    if (state.snap) renderPluginsTab(state.snap);
  });

  document.addEventListener('click', (e) => {
    const fileBtn = e.target.closest('[data-open-file]');
    if (fileBtn) {
      e.stopPropagation();
      openFile(fileBtn.dataset.openFile);
      return;
    }
    const convBtn = e.target.closest('[data-open-conv]');
    if (convBtn) {
      e.stopPropagation();
      openConversation(convBtn.dataset.openConv);
      return;
    }
    const copyBtn = e.target.closest('[data-copy-text]');
    if (copyBtn) {
      e.stopPropagation();
      copyText(copyBtn.dataset.copyText, copyBtn);
      return;
    }
    const skHead = e.target.closest('[data-toggle-skill]');
    if (skHead) {
      const k = skHead.dataset.toggleSkill;
      if (state.expandedSkills.has(k)) state.expandedSkills.delete(k);
      else state.expandedSkills.add(k);
      if (state.snap) renderSkillsTab(state.snap);
      return;
    }
    const plHead = e.target.closest('[data-toggle-plugin]');
    if (plHead) {
      const k = plHead.dataset.togglePlugin;
      if (state.expandedPlugins.has(k)) state.expandedPlugins.delete(k);
      else state.expandedPlugins.add(k);
      if (state.snap) renderPluginsTab(state.snap);
    }
  });

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) poll(false);
    schedulePoll();
  });

  if (window.sidecar?.onWorkspaceChange) {
    window.sidecar.onWorkspaceChange((uris) => {
      state.workspaces = Array.isArray(uris) ? uris : [];
      state.etag = '';
      poll(true);
    });
  }

  // Initial boot
  (async () => {
    if (window.sidecar?.getWorkspaceUris) {
      try {
        state.workspaces = await window.sidecar.getWorkspaceUris();
      } catch {}
    }
    await poll(true);
    schedulePoll();
  })();
})();
