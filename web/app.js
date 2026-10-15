import { callVerifier, identifyRecord, toHex, fromHex, normalizePath, validateFiles, LIMITS } from './client.js';
const $ = id => document.getElementById(id);
const decode = hex => new TextDecoder('utf-8', { fatal: true }).decode(fromHex(hex));
let files = {}, pristine = null, sources = {}, revision = '', trust, lastReport, busy = false;
const el = (tag, text, className) => { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (className) e.className = className; return e; };
function inputMode(own) {
  $('example-tab').classList.toggle('active', !own); $('own-tab').classList.toggle('active', own);
  $('example-tab').setAttribute('aria-pressed', String(!own)); $('own-tab').setAttribute('aria-pressed', String(own));
  $('upload-panel').hidden = !own; $('example-description').hidden = own;
}
function clearResult() {
  lastReport = null; $('report-details').hidden = true; $('result-counts').hidden = true;
  $('findings').replaceChildren(); $('check-results').replaceChildren(); $('state-label').textContent = 'READY';
  $('result-title').textContent = 'Ready to check these bytes.'; $('result-description').textContent = 'Press Verify to run a fresh local check.';
  $('result-symbol').textContent = '↗'; delete $('output-pane').dataset.result;
}
function renderInput() {
  const paths = Object.keys(files), records = paths.filter(p => p.startsWith('records/'));
  $('file-count').textContent = `${records.length} record${records.length === 1 ? '' : 's'} · ${paths.length - records.length} other files`;
  const summary = $('record-summary'); summary.replaceChildren();
  if (records.length) {
    const first = records[0];
    try {
      const raw = decode(files[first]); $('record-json').value = raw;
      const env = JSON.parse(raw), body = env.body || {};
      for (const [label, value] of [['decision', body.decision], ['actor', body.actor?.id], ['reason', (body.because || []).map(r => r.runtime || r.kind).join(', ')], ['file ID', first.slice(8, -5)]]) {
        const row = el('div', undefined, 'summary-row'); row.append(el('span', label), el('strong', String(value ?? '—'), label === 'file ID' ? 'hash' : '')); summary.append(row);
      }
      if (sources[first] && /^[0-9a-f]{40}$/.test(revision)) {
        const a = el('a', 'View the original source record ↗', 'source-link'); a.href = `https://github.com/s0fractal/warrant/blob/${revision}/${sources[first]}`; summary.append(a);
      }
    } catch { $('record-json').value = 'Could not display this record as UTF-8 JSON. Its original bytes will still be checked.'; summary.append(el('p', 'This record could not be displayed. The verifier will inspect its original bytes.')); }
  }
  $('verify-button').disabled = busy || !records.length; $('change-button').disabled = busy || !records.length; clearResult();
}
function displayError(message) {
  clearResult(); $('state-label').textContent = 'INCOMPLETE'; $('result-title').textContent = 'No completed report.';
  $('result-description').textContent = message; $('result-symbol').textContent = '!'; $('output-pane').dataset.result = 'failed';
}
async function verify() {
  if (busy) return;
  busy = true; $('verify-button').disabled = true; $('change-button').disabled = true;
  $('output-pane').setAttribute('aria-busy', 'true'); $('state-label').textContent = 'RUNNING LOCALLY';
  $('result-title').textContent = 'Checking the bytes…'; $('result-description').textContent = 'Rust → WebAssembly → your browser. No files are sent to a verifier server.';
  $('report-details').hidden = true; $('result-counts').hidden = true; $('findings').replaceChildren(); $('check-results').replaceChildren();
  try {
    const { report, checks } = await callVerifier('verify', files, { trust }); lastReport = report;
    $('output-pane').dataset.result = !report.ok ? 'failed' : report.warnings ? 'warned' : 'passed';
    $('state-label').textContent = report.grade.toUpperCase() + ' GRADE';
    $('result-symbol').textContent = !report.ok ? '×' : report.warnings ? '!' : '✓';
    $('result-title').textContent = !report.ok ? 'The record does not verify.' : report.warnings ? 'No errors. Read the warnings.' : 'No verification errors.';
    $('result-description').textContent = !report.ok ? 'The completed report found a mismatch or another verification error. Read the findings below.' : report.warnings ? 'The core verifier completed with zero errors, and reported limits you should inspect.' : 'The requested checks completed with zero errors and zero warnings. This does not establish factual truth or permission.';
    const counts = $('result-counts'); counts.replaceChildren(); counts.hidden = false;
    for (const [label, value] of [['records', report.records], ['errors', report.errors], ['warnings', report.warnings]]) { const div = el('div'); div.append(el('strong', String(value)), document.createTextNode(label)); counts.append(div); }
    for (const c of checks) {
      const box = el('div', undefined, 'rerun'); box.append(el('strong', c.error ? 'ski@v1 · NOT RE-EXECUTED' : 'ski@v1 · RE-EXECUTED'));
      if (c.error) box.append(el('p', c.error));
      else { box.append(el('p', `Filed: ${c.filedVerdict} · Fresh: ${c.verdict} · ${c.atp_spent} ATP`), el('code', `Result: ${c.result}`)); }
      $('check-results').append(box);
    }
    for (const f of report.findings) { const box = el('div', undefined, `finding ${f.level.toLowerCase()}`); box.append(el('strong', `${f.level} · ${f.subject === 'store' || f.subject === 'settlement' ? f.subject : f.subject.slice(0, 12) + '…'}`), el('p', f.message)); $('findings').append(box); }
    $('report-json').textContent = JSON.stringify(report, null, 2); $('report-details').hidden = false;
  } catch (error) { displayError(error.message); }
  finally { busy = false; $('verify-button').disabled = !Object.keys(files).some(p => p.startsWith('records/')); $('change-button').disabled = false; $('output-pane').setAttribute('aria-busy', 'false'); }
}
async function loadExample(run = false) {
  try {
    if (!pristine) { const response = await fetch('./example.json'); if (!response.ok) throw new Error('Could not load the repository example.'); pristine = await response.json(); }
    files = { ...pristine.files }; sources = pristine.sources; revision = pristine.sourceRevision; trust = undefined;
    $('trust-status').textContent = 'No trust configuration supplied.'; $('clear-trust').hidden = true;
    inputMode(false); renderInput(); if (run) await verify();
  } catch (e) { displayError(e.message); }
}
async function loadSelection(selection, single = false) {
  if (busy || !selection?.length) return;
  busy = true; $('verify-button').disabled = true;
  try {
    if (selection.length > LIMITS.files || [...selection].reduce((n, f) => n + f.size, 0) > LIMITS.bytes) throw new Error('Browser limit: 8 MiB and 2,048 selected files. Use the CLI for larger stores.');
    const next = {};
    for (const file of selection) {
      const hex = toHex(new Uint8Array(await file.arrayBuffer()));
      const namedId = /^([0-9a-f]{64})\.json$/.exec(file.name)?.[1];
      let path = single ? `records/${namedId || await identifyRecord(hex)}.json` : normalizePath(file.webkitRelativePath || file.name);
      if (!path) continue;
      if (Object.hasOwn(next, path)) throw new Error(`Two selected files resolve to ${path}. Select one store at a time.`);
      next[path] = hex;
    }
    validateFiles(next); files = next; sources = {}; trust = undefined;
    $('trust-status').textContent = 'No trust configuration supplied.'; $('clear-trust').hidden = true;
    inputMode(true); busy = false; renderInput();
  } catch (e) { displayError(e.message); }
  finally { busy = false; $('verify-button').disabled = !Object.keys(files).some(p => p.startsWith('records/')); }
}
$('fetch-source').addEventListener('click', async () => {
  if (busy || !pristine || !/^[0-9a-f]{40}$/.test(pristine.sourceRevision)) return;
  busy = true; $('verify-button').disabled = true; $('fetch-source').disabled = true;
  const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), LIMITS.timeout);
  try {
    const next = {};
    for (const [path, source] of Object.entries(pristine.sources)) {
      if (!/^examples\/ski\/[a-zA-Z0-9_.-]+$/.test(source)) throw new Error('Unsupported example source path.');
      const response = await fetch(`https://raw.githubusercontent.com/s0fractal/warrant/${pristine.sourceRevision}/${source}`, { signal: controller.signal, credentials: 'omit', referrerPolicy: 'no-referrer' });
      if (!response.ok) throw new Error('GitHub source could not be loaded. The bundled example is still available.');
      next[path] = toHex(new Uint8Array(await response.arrayBuffer()));
    }
    validateFiles(next); files = next; sources = pristine.sources; revision = pristine.sourceRevision; renderInput();
    busy = false; await verify();
  } catch (e) { displayError(e.name === 'AbortError' ? 'GitHub source did not respond within the time limit.' : e.message); }
  finally { clearTimeout(timer); busy = false; $('fetch-source').disabled = false; $('verify-button').disabled = false; }
});
$('verify-button').addEventListener('click', verify);
$('hero-run').addEventListener('click', () => { if (!busy) loadExample(true); });
$('reset-button').addEventListener('click', () => { if (!busy) loadExample(); });
$('example-tab').addEventListener('click', () => { if (!busy) loadExample(); });
$('own-tab').addEventListener('click', () => { if (!busy) inputMode(true); });
$('folder-input').addEventListener('change', e => loadSelection(e.target.files));
$('record-input').addEventListener('change', e => loadSelection(e.target.files, true));
$('change-button').addEventListener('click', () => {
  if (busy) return;
  try {
    const path = Object.keys(files).find(p => p.startsWith('records/')); const env = JSON.parse(decode(files[path]));
    env.body.subject.note = (env.body.subject.note || '') + ' — edited'; files[path] = toHex(new TextEncoder().encode(JSON.stringify(env, null, 2))); renderInput(); verify();
  } catch (e) { displayError(`Cannot edit this record: ${e.message}`); }
});
$('apply-json').addEventListener('click', () => {
  if (busy) return;
  const path = Object.keys(files).find(p => p.startsWith('records/'));
  if (!path) return;
  files[path] = toHex(new TextEncoder().encode($('record-json').value)); renderInput();
});
$('trust-input').addEventListener('change', async e => {
  if (busy) return;
  const f = e.target.files[0]; if (!f) return;
  if (f.size > 256 * 1024) { displayError('Trust configuration exceeds 256 KiB.'); return; }
  trust = await f.text(); $('trust-status').textContent = `${f.name} · settlement grade requested. No validation result yet.`; $('clear-trust').hidden = false; clearResult();
});
$('clear-trust').addEventListener('click', () => { if (busy) return; trust = undefined; $('trust-status').textContent = 'No trust configuration supplied.'; $('clear-trust').hidden = true; clearResult(); });
$('download-report').addEventListener('click', () => {
  if (!lastReport) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(lastReport, null, 2) + '\n'], { type: 'application/json' }));
  const a = el('a'); a.href = url; a.download = 'warrant-verify-report.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
fetch('./build.json').then(r => { if (!r.ok) throw new Error(); return r.json(); }).then(b => {
  $('build-identity').textContent = `Rust ${b.coreVersion} · source ${b.sourceRevision.slice(0, 12)} · ${b.workingTree} build · WASM ${(b.wasmSha256 || '').slice(0, 12)}…`;
}).catch(() => { $('build-identity').textContent = 'Build identity unavailable. Inspect source before relying on this deployment.'; });
loadExample();
