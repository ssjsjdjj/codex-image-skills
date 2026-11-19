(function () {
  'use strict';
  const isLogo = i => i.group === 'D' && i.feature === 'logo';
  const isTexture = i => i.group === 'Q';
  const isStructure = i => i.group === 'D' && !isLogo(i);
  const peopleKey = i => JSON.stringify([String(i.scene || ''), String(i.person === undefined ? i.id || '' : i.person)]);
  const fieldStatus = (i, field) => i[field] && typeof i[field] === 'object' ? i[field].status : undefined;
  function issueState(i) {
    const diagnosis = fieldStatus(i, 'diagnosis'), repair = fieldStatus(i, 'repair'), review = fieldStatus(i, 'review'), adoption = fieldStatus(i, 'adoption');
    if (i.legacy_readonly || i.state === 'readonly') return 'readonly';
    if (Array.isArray(i.dependency_blockers) && i.dependency_blockers.length) return 'blocked';
    if (Array.isArray(i.dependencies) && i.dependencies.length && !Array.isArray(i.dependency_blockers)) return 'needs_review';
    if (i.group === 'R' || ['uncertain', 'withdrawn', 'no_difference'].includes(diagnosis)) return 'blocked';
    if (diagnosis !== 'confirmed') return 'unknown';
    if (!['not_adopted', 'adopted', 'withdrawn'].includes(adoption)) return 'unknown';
    if (['needs_review', 'insufficient', 'revoked'].includes(review)) return 'needs_review';
    if (adoption === 'adopted') return i.current_output ? 'adopted' : 'needs_review';
    if (review === 'passed') return i.current_output ? 'verified' : 'needs_review';
    if (!['not_reviewed', 'failed'].includes(review)) return 'unknown';
    if (review === 'failed' && ['pending', 'failed', 'executed', 'not_executed'].includes(repair)) return 'pending';
    if (repair === 'executed') return 'repaired';
    if (repair === 'in_progress') return 'in_progress';
    if (['pending', 'failed', 'not_executed'].includes(repair)) return 'pending';
    return 'unknown';
  }
  function eligible(i, redo = false) {
    if (fieldStatus(i, 'diagnosis') !== 'confirmed' || i.group === 'R' || i.legacy_readonly) return false;
    const state = issueState(i);
    if (['unknown', 'needs_review', 'readonly', 'blocked', 'in_progress'].includes(state)) return false;
    if (typeof i.default_selectable !== 'boolean' || typeof i.redo_selectable !== 'boolean') return false;
    return (state === 'pending' && i.default_selectable) || (redo && ['repaired', 'verified', 'adopted'].includes(state) && i.redo_selectable);
  }
  function matches(i, f) {
    if (f.scene && f.scene !== 'all' && i.scene !== f.scene) return false;
    if (f.kind === 'logo' && !isLogo(i)) return false;
    if (f.kind === 'structure' && !isStructure(i)) return false;
    if (f.kind && !['all', 'logo', 'structure'].includes(f.kind) && i.group !== f.kind) return false;
    if (f.state && f.state !== 'all' && issueState(i) !== f.state) return false;
    const q = (f.query || '').trim().toLocaleLowerCase();
    return !q || [i.id, i.scene, i.person, i.filename, i.title, i.position, i.color, i.feature].join(' ').toLocaleLowerCase().includes(q);
  }
  function pendingIds(items, predicate, scene = 'all') {
    return items.filter(i => predicate(i) && eligible(i) && (scene === 'all' || i.scene === scene)).map(i => i.id);
  }
  const logoIds = (items, scene = 'all') => pendingIds(items, isLogo, scene);
  const textureIds = (items, scene = 'all') => pendingIds(items, isTexture, scene);
  function updateSelection(selected, items, ids, mode = 'add', redo = false) {
    const result = new Set(selected), lookup = new Map(items.map(i => [i.id, i]));
    for (const id of ids) {
      const item = lookup.get(id);
      if (!item || !eligible(item, redo)) continue;
      if (mode === 'invert' && result.has(id)) result.delete(id); else result.add(id);
    }
    return result;
  }
  function chosen(items, selected) { return items.filter(i => selected.has(i.id)); }
  function instruction(items) {
    if (!items.length) return '';
    return '请修复：' + items.map(i => i.id).join('、') + (items.every(isLogo) ? '；仅修改所选 Logo 及必要融合边缘；其余保持不动。' : '；其余保持不动。');
  }
  function stats(items) { return {issues: items.length, scenes: new Set(items.map(i => i.scene)).size, people: new Set(items.map(peopleKey)).size}; }
  function coveragePeople(data) {
    const people = new Map();
    for (const p of data.people || []) people.set(peopleKey(p), p);
    return [...people.values()];
  }
  function exportable(data) {
    return data.schema_version === 2 && !data.legacy_readonly && Boolean(data.dataset_id && data.revision && data.source_manifest_sha256);
  }
  const clone = value => value === undefined ? null : JSON.parse(JSON.stringify(value));
  function buildPayload(data, selected, redo = false, exportedAt) {
    if (!exportable(data)) throw new Error('当前预览缺少有效版本绑定，只能查看；请重新生成 schema 2 预览。');
    const rows = chosen(data.issues || [], selected);
    if (!rows.length) throw new Error('请选择至少一个明确的修改项。');
    if (rows.length !== selected.size) throw new Error('已选编号不属于当前预览，请重新选择。');
    if (rows.some(i => ['diagnosis', 'repair', 'review', 'adoption'].some(key => !i[key] || typeof i[key] !== 'object'))) throw new Error('已选项状态记录不完整，请重新生成预览。');
    if (rows.some(i => !eligible(i, redo))) throw new Error('已选项含未确认、需复核或未授权返修项，请重新核对。');
    const payload = {
      schema_version: 2, dataset_id: data.dataset_id, review_revision: data.revision,
      source_manifest_sha256: data.source_manifest_sha256, allow_redo: Boolean(redo),
      summary: stats(rows), selected_issues: rows.map(i => ({
        id: i.id, scene: i.scene, person: i.person, people_key: i.people_key || peopleKey(i),
        group: i.group, feature: i.feature, title: i.title, state: i.state || issueState(i),
        current_output: clone(i.current_output), diagnosis: clone(i.diagnosis), repair: clone(i.repair),
        review: clone(i.review), adoption: clone(i.adoption)
      })), instruction: instruction(rows)
    };
    if (exportedAt) payload.exported_at = exportedAt;
    return payload;
  }
  const serializePayload = payload => JSON.stringify(payload, null, 2);
  function evidenceLines(i) {
    const lines = [];
    function append(label, value) {
      if (value === undefined || value === null || value === '') return;
      lines.push(label + '：' + (typeof value === 'string' ? value : JSON.stringify(value)));
    }
    append('可见性', i.visibility);
    append('面料检查记录', i.material_checks);
    append('检查证据', i.evidence);
    return lines;
  }
  function actionabilityLines(i) {
    const lines = [];
    if (Array.isArray(i.dependencies) && i.dependencies.length) lines.push('依赖项：' + i.dependencies.join('、'));
    if (Array.isArray(i.dependency_blockers) && i.dependency_blockers.length) lines.push('未满足依赖：' + i.dependency_blockers.join('、'));
    if (i.actionability_reason) lines.push('当前执行限制：' + i.actionability_reason);
    return lines;
  }
  function referenceLabel(i) {
    const ids = Array.isArray(i.reference_ids) ? i.reference_ids.filter(Boolean).join('、') : '';
    return ids || i.reference_id || '未记录';
  }
  const engine = {isLogo, isTexture, isStructure, peopleKey, issueState, eligible, matches, logoIds, textureIds, updateSelection, chosen, instruction, stats, coveragePeople, exportable, buildPayload, serializePayload, evidenceLines, actionabilityLines, referenceLabel};
  if (typeof module !== 'undefined' && module.exports) module.exports = engine;
  if (typeof document === 'undefined') return;

  const data = JSON.parse(document.getElementById('review-data').textContent), items = data.issues || [];
  const $ = id => document.getElementById(id), readOnly = !exportable(data);
  const stateNames = {pending: '待修复', repaired: '已修待复核', verified: '技术复核通过', adopted: '用户已采用', blocked: '证据不足／不执行', needs_review: '需重新复核', unknown: '状态未知', in_progress: '修复进行中', readonly: '旧记录／仅供查看'};
  const storageKey = 'product-diff-selection:' + data.dataset_id + ':' + data.revision;
  let selected = new Set(), visible = [], currentPayload = null;
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || '[]');
    if (!readOnly) selected = new Set(items.filter(i => saved.includes(i.id) && eligible(i)).map(i => i.id));
  } catch (_) { /* Selection still works when file viewers block localStorage. */ }
  function el(tag, text, cls) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; }
  function button(text, fn, cls) { const b = el('button', text, cls); b.type = 'button'; b.addEventListener('click', fn); return b; }
  function link(text, href) { const a = el('a', text); a.href = href; a.target = '_blank'; a.rel = 'noopener'; return a; }
  function filters() { return {scene: $('scene-filter').value, kind: $('kind-filter').value, state: $('state-filter').value, query: $('search').value}; }
  function remember() { try { localStorage.setItem(storageKey, JSON.stringify([...selected])); } catch (_) {} }
  function syncChecks() {
    document.querySelectorAll('input[data-issue-id]').forEach(c => {
      c.checked = selected.has(c.value); c.closest('.issue').classList.toggle('is-selected', c.checked);
    });
  }
  function setBatchButton(id, ids, label, scene) {
    const unavailable = readOnly || scene === 'all';
    $(id).textContent = unavailable && scene === 'all' ? label + '（先选图片）' : `${label}（${ids.length}）`;
    $(id).disabled = readOnly || unavailable || !ids.length;
  }
  function summarize() {
    const current = chosen(items, selected), s = stats(current), shown = new Set(visible.map(i => i.id));
    const hidden = current.filter(i => !shown.has(i.id)).length;
    $('selected-count').textContent = `已选 ${s.issues} 处 · ${s.scenes} 张图 · ${s.people} 位模特`;
    const visibleIds = readOnly ? [] : visible.filter(i => eligible(i, $('redo').checked)).map(i => i.id);
    $('visible-summary').textContent = `当前筛选 ${visible.length} 项，可选 ${visibleIds.length} 项；筛选外仍已选 ${hidden} 项。`;
    $('select-visible').textContent = `全选当前筛选结果（${visibleIds.length}）`;
    $('select-visible').disabled = !visibleIds.length; $('invert-visible').disabled = !visibleIds.length;
    const scene = $('scene-filter').value;
    for (const [kind, getIds, label] of [['texture', textureIds, '质感'], ['logo', logoIds, 'Logo']]) {
      const ids = getIds(items);
      $('batch-' + kind).textContent = `本批次待修${kind === 'texture' ? '质感' : ' Logo '}全选（${ids.length}）`;
      $('batch-' + kind).disabled = readOnly || !ids.length;
      setBatchButton('scene-' + kind, scene === 'all' ? [] : getIds(items, scene), `本图待修${kind === 'texture' ? '质感' : ' Logo '}全选`, scene);
    }
    const chips = $('selected-chips'); chips.replaceChildren();
    for (const i of current) {
      const b = button(`${i.id} · ${i.scene} ${i.position || i.person} ×`, () => { selected.delete(i.id); update(); }, 'chip');
      b.setAttribute('aria-label', '移除 ' + i.id); chips.append(b);
    }
    currentPayload = null;
    if (current.length && !readOnly) {
      try { currentPayload = buildPayload(data, selected, $('redo').checked); }
      catch (error) { $('copy-message').textContent = error.message; }
    }
    $('instruction').value = currentPayload ? serializePayload(currentPayload) : '';
    $('copy').disabled = !currentPayload; $('download').disabled = !currentPayload; $('clear').disabled = !current.length;
  }
  function update() { $('copy-message').textContent = ''; remember(); syncChecks(); summarize(); }
  function addKind(getIds, scene = 'all') { if (readOnly) return; selected = updateSelection(selected, items, getIds(items, scene)); update(); }
  function render() {
    visible = items.filter(i => matches(i, filters())); const cards = $('cards'); cards.replaceChildren();
    if (!visible.length) cards.append(el('div', '当前没有匹配项，可调整图片、问题或状态筛选。', 'empty'));
    const groups = new Map();
    for (const i of visible) { if (!groups.has(i.scene)) groups.set(i.scene, []); groups.get(i.scene).push(i); }
    for (const [scene, rows] of groups) {
      const head = el('div', undefined, 'scene-head'); head.append(el('h2', `${scene} · ${rows[0].filename || scene}`));
      const actions = el('div', undefined, 'actions');
      for (const [getIds, label] of [[textureIds, '质感'], [logoIds, 'Logo']]) {
        const count = getIds(items, scene).length, pick = button(`本图待修${label === '质感' ? '质感' : ' Logo '}全选（${count}）`, () => addKind(getIds, scene));
        pick.disabled = readOnly || !count; actions.append(pick);
      }
      head.append(actions); cards.append(head);
      for (const i of rows) {
        const state = issueState(i), card = el('article', undefined, 'issue'); card.id = i.id;
        const title = el('label', undefined, 'issue-title'), c = document.createElement('input'); c.type = 'checkbox'; c.value = i.id; c.dataset.issueId = i.id;
        c.disabled = readOnly || !eligible(i, $('redo').checked); c.checked = selected.has(i.id);
        c.addEventListener('change', () => { if (c.checked && eligible(i, $('redo').checked)) selected.add(i.id); else selected.delete(i.id); update(); });
        title.append(c, el('span', `${i.id} · ${i.title}`)); card.append(title);
        const tags = el('div'); tags.append(el('span', stateNames[state], 'tag ' + state), el('span', i.category || i.group, 'tag')); card.append(tags);
        card.append(el('p', [i.person, i.position, i.color].filter(Boolean).join(' · '), 'small'));
        card.append(el('p', `问题判断：${fieldStatus(i, 'diagnosis') || '未知'} · 修复：${fieldStatus(i, 'repair') || '未知'} · 复核：${fieldStatus(i, 'review') || '未知'} · 采用：${fieldStatus(i, 'adoption') || '未记录'}`, 'small'));
        for (const line of actionabilityLines(i)) card.append(el('p', line, 'evidence-warning'));
        if ((readOnly || state === 'readonly') && i.state_text) card.append(el('p', '历史处理文字（未作为当前通过或采用依据）：' + i.state_text, 'small'));
        if (i.image) {
          const a = link('', i.image), img = document.createElement('img'); a.className = 'preview'; img.src = i.image; img.loading = 'lazy'; img.alt = i.id + '：AI与实拍的编号放大对比'; a.append(img); card.append(a);
        } else card.append(el('p', '缺少该项对比图片：需补充可追溯证据，当前页面不能据此确认差异或复核通过。', 'evidence-warning'));
        if (i.description) card.append(el('p', i.description));
        card.append(el('p', `确定性：${i.certainty || '未记录'}。${i.limitation || ''}`, 'small'));
        const evidence = evidenceLines(i);
        if (evidence.length) for (const line of evidence) card.append(el('p', line, 'small evidence'));
        else if (isTexture(i)) card.append(el('p', '尚未附可见性或面料检查证据；请结合清晰原裁片判断纹理、褶皱和受光，不据缺失记录推断已通过。', 'evidence-warning'));
        if (['repaired', 'verified', 'adopted'].includes(state)) card.append(el('p', '此项已有处理记录；需要返修时打开“允许选择已处理项”。技术通过与用户采用分别记录。', 'small'));
        if (['unknown', 'needs_review'].includes(state)) card.append(el('p', '状态待确认，未自动加入待修范围。请补齐或更新复核记录后重新生成预览。', 'evidence-warning'));
        if (i.current_output) card.append(el('p', `当前输出：${i.current_output.version || '未命名版本'} · ${i.current_output.path || ''}`, 'small filename'));
        const details = el('details'), sum = el('summary', '参考、原裁片与建议修法'); details.append(sum);
        if (i.suggested_method) details.append(el('p', i.suggested_method));
        details.append(el('p', '参考：' + referenceLabel(i), 'small'));
        const links = el('p'); if (i.native_ai) links.append(link('AI原裁片', i.native_ai), document.createTextNode('　')); if (i.native_ref) links.append(link('实拍原裁片', i.native_ref)); details.append(links); card.append(details); cards.append(card);
      }
    }
    syncChecks(); summarize();
  }
  $('title').textContent = data.title || 'AI商品质感与差异检查'; document.title = $('title').textContent + ' · 批量选择'; $('scope').textContent = data.scope || '';
  const coverage = coveragePeople(data), s = stats(items);
  $('batch-summary').textContent = `本批次 ${s.scenes} 张涉及问题的图片 · ${coverage.length || s.people} 位模特。已确认待修质感／画质 ${textureIds(items).length} 处；已确认待修 Logo ${logoIds(items).length} 处。技术复核通过和用户采用分别显示。`;
  const diagnostics = $('diagnostics');
  if (readOnly) {
    $('kind-filter').value = 'all'; $('state-filter').value = 'all'; $('redo').disabled = true;
    diagnostics.append(el('p', '此预览缺少有效的当前版本绑定，仅供查看；请使用当前素材和状态记录重新生成，不能导出修复选择。', 'evidence-warning'));
  }
  for (const diagnostic of data.diagnostics || []) diagnostics.append(el('p', typeof diagnostic === 'string' ? diagnostic : JSON.stringify(diagnostic), 'evidence-warning'));
  const scenes = [...new Set(items.map(i => i.scene))].sort();
  for (const scene of scenes) { const opt = el('option', scene + ' · ' + (items.find(i => i.scene === scene).filename || scene)); opt.value = scene; $('scene-filter').append(opt); }
  for (const name of ['scene-filter', 'state-filter', 'search']) $(name).addEventListener(name === 'search' ? 'input' : 'change', render);
  $('kind-filter').addEventListener('change', () => { if ($('kind-filter').value === 'R') $('state-filter').value = 'all'; render(); });
  $('redo').addEventListener('change', () => { if (!$('redo').checked) { selected = new Set(items.filter(i => selected.has(i.id) && eligible(i)).map(i => i.id)); remember(); } render(); });
  for (const [kind, getIds] of [['texture', textureIds], ['logo', logoIds]]) {
    $('batch-' + kind).addEventListener('click', () => addKind(getIds));
    $('scene-' + kind).addEventListener('click', () => addKind(getIds, $('scene-filter').value));
  }
  $('select-visible').addEventListener('click', () => { if (readOnly) return; selected = updateSelection(selected, items, visible.map(i => i.id), 'add', $('redo').checked); update(); });
  $('invert-visible').addEventListener('click', () => { if (readOnly) return; selected = updateSelection(selected, items, visible.map(i => i.id), 'invert', $('redo').checked); update(); });
  $('clear').addEventListener('click', () => { selected.clear(); update(); });
  $('copy').addEventListener('click', async () => {
    if (!currentPayload) return;
    const text = serializePayload(currentPayload);
    try { await navigator.clipboard.writeText(text); $('copy-message').textContent = '已复制绑定完整范围与当前版本的选择清单；粘贴回聊天后核对执行。'; }
    catch (_) { $('instruction').focus(); $('instruction').select(); $('copy-message').textContent = '已选中完整选择清单，请手动复制后粘贴回聊天。'; }
  });
  $('download').addEventListener('click', () => {
    if (!currentPayload) return;
    const url = URL.createObjectURL(new Blob([serializePayload(currentPayload)], {type: 'application/json;charset=utf-8'})), a = document.createElement('a');
    a.href = url; a.download = '差异修复选择_' + data.dataset_id + '.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    $('copy-message').textContent = '已下载与复制内容相同的选择清单。页面只记录选择，不执行图像修复。';
  });
  $('coverage-title').textContent = `逐人覆盖记录（${coverage.length}人）与素材索引`;
  for (const p of coverage) {
    const tr = el('tr'); tr.append(el('td', `${p.scene} / ${p.id} · ${p.position || ''} · ${p.color || ''}`));
    for (const key of ['cloth', 'structure', 'logo', 'face']) tr.append(el('td', (p.conclusions || {})[key] || '未记录／未确认'));
    $('coverage-body').append(tr);
  }
  for (const f of data.files || []) {
    const card = el('div', undefined, 'scene-card'); card.append(el('b', f.id), el('p', f.name, 'small filename'));
    if (f.image) { const a = link('', f.image), img = document.createElement('img'); img.loading = 'lazy'; img.src = f.image; img.alt = f.id + '预览'; a.append(img); card.append(a); }
    if (scenes.includes(f.id)) card.append(button('筛选本图问题', () => { $('scene-filter').value = f.id; $('state-filter').value = 'all'; render(); $('scene-filter').scrollIntoView({block: 'center'}); }));
    $('scene-grid').append(card);
  }
  $('disclaimer').textContent = data.disclaimer || '模型目视判断，建议人工复核。'; render();
})();
