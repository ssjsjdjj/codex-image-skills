'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const review = require('../assets/bulk-review.js');

function item(id, extra = {}) {
  return {
    id, scene: 'S1', person: 'P1', group: 'Q', feature: 'texture', title: '面料细纹', state: 'pending',
    diagnosis: {status: 'confirmed'}, repair: {status: 'pending'}, review: {status: 'not_reviewed'},
    adoption: {status: 'not_adopted'}, current_output: null, default_selectable: true, redo_selectable: false,
    ...extra
  };
}
const output = {path: 'C:/case/final-v2.png', sha256: 'a'.repeat(64), version: 'v2'};
function done(id, extra = {}) {
  return item(id, {state: 'repaired', repair: {status: 'executed'}, current_output: output, default_selectable: false, redo_selectable: true, ...extra});
}
function data(issues, extra = {}) {
  return {schema_version: 2, dataset_id: 'case-a', revision: 'rev-a', source_manifest_sha256: 'b'.repeat(64), issues, people: [], ...extra};
}

test('质感与Logo批选只追加已确认待修项，结构D不进入Logo入口', () => {
  const rows = [
    item('Q1'), item('Q2', {scene: 'S2'}), done('Q3'),
    item('Q4', {diagnosis: {status: 'uncertain'}, default_selectable: false}),
    item('D1', {group: 'D', feature: 'logo'}), item('D2', {group: 'D', feature: 'seam'}),
    item('R1', {group: 'R'}), item('F1', {group: 'F', feature: 'face'}),
    item('Q5', {review: {status: 'needs_review'}, default_selectable: false}),
    item('Q6', {review: {status: 'unrecognized'}, default_selectable: false})
  ];
  assert.deepEqual(review.textureIds(rows), ['Q1', 'Q2']);
  assert.deepEqual(review.textureIds(rows, 'S1'), ['Q1']);
  assert.deepEqual(review.logoIds(rows), ['D1']);
  assert.deepEqual([...review.updateSelection(new Set(['D2']), rows, review.textureIds(rows))], ['D2', 'Q1', 'Q2']);
});

test('筛选区分结构、Logo、质感、证据不足和具体状态', () => {
  const structure = item('D1', {group: 'D', feature: 'seam'});
  const logo = item('D2', {group: 'D', feature: 'logo'});
  assert.equal(review.matches(structure, {kind: 'structure'}), true);
  assert.equal(review.matches(logo, {kind: 'structure'}), false);
  assert.equal(review.matches(structure, {kind: 'logo'}), false);
  assert.equal(review.matches(item('Q1'), {kind: 'Q', state: 'pending'}), true);
  assert.equal(review.matches(done('Q1'), {kind: 'Q', state: 'pending'}), false);
  assert.equal(review.matches(structure, {scene: 'S2'}), false);
  assert.equal(review.matches(structure, {query: 'seam'}), true);
});

test('人数按图片和人物联合身份计数，覆盖记录不吞掉跨图同号人物', () => {
  const rows = [item('Q1'), item('Q2'), item('Q3', {scene: 'S2'})];
  assert.deepEqual(review.stats(rows), {issues: 3, scenes: 2, people: 2});
  const people = [{scene: 'S1', id: 'P1'}, {scene: 'S2', id: 'P1'}, {scene: 'S1', id: 'P1'}];
  assert.equal(review.coveragePeople({people}).length, 2);
  assert.notEqual(review.peopleKey({scene: 'A|B', person: 'C'}), review.peopleKey({scene: 'A', person: 'B|C'}));
});

test('追加与筛选内反选保留筛选外已选项，不自动混入已完成项', () => {
  const rows = [item('Q1'), item('Q2', {scene: 'S2'}), done('Q3')];
  const before = new Set(['Q2']);
  const added = review.updateSelection(before, rows, ['Q1', 'Q3']);
  assert.deepEqual([...added], ['Q2', 'Q1']);
  assert.deepEqual([...review.updateSelection(added, rows, ['Q1'], 'invert')], ['Q2']);
  assert.deepEqual([...before], ['Q2']);
});

test('未知、需复核、撤回、旧文字状态不能默认为待修', () => {
  assert.equal(review.issueState({state: 'pending'}), 'unknown');
  assert.equal(review.eligible({state: 'pending'}), false);
  for (const status of ['needs_review', 'insufficient', 'revoked', 'unrecognized']) {
    const row = item('Q1', {review: {status}, default_selectable: true, redo_selectable: true});
    assert.equal(review.eligible(row), false);
    assert.equal(review.eligible(row, true), false);
    assert.notEqual(review.issueState(row), 'pending');
  }
  assert.equal(review.eligible(item('Q1', {legacy_readonly: true})), false);
  assert.equal(review.issueState(item('Q1', {adoption: {status: 'unknown'}})), 'unknown');
});

test('已修、技术复核通过、采用保持独立；旧采用文字不继承到当前输出', () => {
  assert.equal(review.issueState(done('Q1')), 'repaired');
  assert.equal(review.issueState(done('Q1', {review: {status: 'passed'}})), 'verified');
  assert.equal(review.issueState(done('Q1', {review: {status: 'passed'}, adoption: {status: 'adopted'}})), 'adopted');
  assert.equal(review.issueState(item('Q1', {state: 'adopted', state_text: '旧版已采用'})), 'pending');
  assert.equal(review.issueState(item('Q1', {adoption: {status: 'adopted'}})), 'needs_review');
});

test('返修需要显式redo，后端禁选标记不会被前端推断覆盖', () => {
  const row = done('Q1');
  assert.equal(review.eligible(row), false);
  assert.equal(review.eligible(row, true), true);
  assert.equal(review.eligible(done('Q1', {redo_selectable: false}), true), false);
  assert.equal(review.eligible(done('Q1', {default_selectable: true})), false);
  assert.equal(review.eligible(item('Q1', {default_selectable: false})), false);
  assert.equal(review.eligible(item('Q1', {default_selectable: undefined, redo_selectable: undefined})), false);
});

test('已执行但复核失败回到待修，不被误作完成项要求redo', () => {
  const row = item('Q1', {repair: {status: 'executed'}, review: {status: 'failed'}});
  assert.equal(review.issueState(row), 'pending');
  assert.equal(review.eligible(row), true);
  assert.deepEqual(review.textureIds([row]), ['Q1']);
  assert.equal(review.buildPayload(data([row]), new Set(['Q1'])).allow_redo, false);
});

test('未满足依赖阻止默认和redo，缺依赖判定不由前端自行放行', () => {
  const row = item('Q1', {dependencies: ['D1'], dependency_blockers: ['D1'], actionability_reason: '先完成当前结构定位并复核'});
  assert.equal(review.issueState(row), 'blocked');
  assert.equal(review.eligible(row), false);
  assert.equal(review.eligible({...row, redo_selectable: true}, true), false);
  assert.deepEqual(review.textureIds([row]), []);
  assert.throws(() => review.buildPayload(data([row]), new Set(['Q1'])));
  assert.equal(review.eligible(item('Q1', {dependencies: ['D1']})), false);
  assert.deepEqual(review.actionabilityLines(row), ['依赖项：D1', '未满足依赖：D1', '当前执行限制：先完成当前结构定位并复核']);
});

test('一个绑定完整payload供复制和下载使用，包含联合定位、当前输出及四种状态', () => {
  const rows = [item('Q1'), done('D1', {scene: 'S2', group: 'D', feature: 'logo', person: 'P1'})];
  const source = data(rows), payload = review.buildPayload(source, new Set(['Q1', 'D1']), true);
  const copied = review.serializePayload(payload), downloaded = review.serializePayload(payload);
  assert.equal(copied, downloaded);
  assert.equal(payload.schema_version, 2);
  assert.equal(payload.review_revision, source.revision);
  assert.equal(payload.source_manifest_sha256, source.source_manifest_sha256);
  assert.equal(payload.allow_redo, true);
  assert.deepEqual(payload.summary, {issues: 2, scenes: 2, people: 2});
  assert.equal(payload.selected_issues[0].current_output, null);
  assert.deepEqual(payload.selected_issues[1].current_output, output);
  assert.deepEqual(payload.selected_issues[1].review, {status: 'not_reviewed'});
  assert.deepEqual(payload.selected_issues[1].adoption, {status: 'not_adopted'});
  assert.equal(payload.instruction, '请修复：Q1、D1；其余保持不动。');
  assert.deepEqual(Object.keys(payload.selected_issues[0]).filter(k => ['id', 'scene', 'person', 'group', 'feature', 'current_output', 'diagnosis', 'repair', 'review', 'adoption'].includes(k)).sort(), ['adoption', 'current_output', 'diagnosis', 'feature', 'group', 'id', 'person', 'repair', 'review', 'scene']);
  rows[1].current_output = {path: 'changed'};
  rows[1].repair.status = 'failed';
  assert.equal(review.serializePayload(payload), copied);
});

test('Logo专用指令与非Logo指令保持绑定，不把结构说成Logo', () => {
  const logo = item('D1', {group: 'D', feature: 'logo'});
  assert.equal(review.buildPayload(data([logo]), new Set(['D1'])).instruction, '请修复：D1；仅修改所选 Logo 及必要融合边缘；其余保持不动。');
  assert.equal(review.instruction([item('D2', {group: 'D', feature: 'seam'})]), '请修复：D2；其余保持不动。');
});

test('导出拒绝旧预览、失配编号、空选择、状态缺失和未经redo的已修项', () => {
  const row = item('Q1');
  assert.throws(() => review.buildPayload(data([row], {schema_version: 1}), new Set(['Q1'])));
  assert.throws(() => review.buildPayload(data([row], {legacy_readonly: true}), new Set(['Q1'])));
  assert.throws(() => review.buildPayload(data([row]), new Set(['OTHER'])));
  assert.throws(() => review.buildPayload(data([row]), new Set()));
  assert.throws(() => review.buildPayload(data([item('Q1', {adoption: null})]), new Set(['Q1'])));
  assert.throws(() => review.buildPayload(data([done('Q1')]), new Set(['Q1'])));
});

test('可见性和面料证据仅显示已有值，不凭空补出通过结论', () => {
  assert.deepEqual(review.evidenceLines(item('Q1')), []);
  assert.deepEqual(review.evidenceLines(item('Q1', {visibility: '袖口可见', material_checks: {texture_scale: '待核对'}, evidence: ['native/Q1.png']})), ['可见性：袖口可见', '面料检查记录：{"texture_scale":"待核对"}', '检查证据：["native/Q1.png"]']);
});

test('参考显示优先使用v2数组，兼容旧单号且无参考时明确显示未记录', () => {
  assert.equal(review.referenceLabel({reference_ids: ['REF1', 'REF2'], reference_id: 'OLD'}), 'REF1、REF2');
  assert.equal(review.referenceLabel({reference_ids: ['REF1']}), 'REF1');
  assert.equal(review.referenceLabel({reference_id: 'OLD'}), 'OLD');
  assert.equal(review.referenceLabel({reference_ids: [], reference_id: 'OLD'}), 'OLD');
  assert.equal(review.referenceLabel({reference_ids: []}), '未记录');
  assert.equal(review.referenceLabel({}), '未记录');
});
