import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { initSync, verify_store, record_id, run_check } from '../dist/wasm/warrant_browser.js';
import { normalizePath, fromHex, toHex, validateFiles, callVerifier } from '../client.js';

initSync({ module: readFileSync(new URL('../dist/wasm/warrant_browser_bg.wasm', import.meta.url)) });
const example = JSON.parse(readFileSync(new URL('../dist/example.json', import.meta.url)));
const recordPath = Object.keys(example.files).find(p => p.startsWith('records/'));
const env = JSON.parse(Buffer.from(example.files[recordPath], 'hex').toString());
const check = env.body.because[0].check;
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const parse = (files, trust) => JSON.parse(verify_store(JSON.stringify(files), trust));

function nativeReport(files, trust) {
  const root = mkdtempSync(join(tmpdir(), 'warrant-wasm-parity-'));
  try {
    mkdirSync(join(root, 'records'));mkdirSync(join(root, 'blobs'));
    for (const [p, hex] of Object.entries(files)) writeFileSync(join(root, p), Buffer.from(hex, 'hex'));
    const args = [resolve('../impl/warrant.py'), '--store', root, 'verify', '--store-mode', '--json'];
    if (trust !== undefined) { const p = join(root, 'trust.json');writeFileSync(p, trust);args.push('--settlement', '--trust-config', p); }
    const result = spawnSync(process.env.WARRANT_PYTHON || 'python3', args, { encoding: 'utf8' });
    assert.ok(result.stdout, result.stderr);return JSON.parse(result.stdout);
  } finally { rmSync(root, { recursive: true }); }
}

test('actual WASM report matches Python for exact raw files, edited and malformed bytes', () => {
  const edited = structuredClone(example.files), body = structuredClone(env);body.body.subject.note += ' edited';edited[recordPath] = Buffer.from(JSON.stringify(body)).toString('hex');
  const malformed = { ...example.files, [recordPath]: Buffer.from('{broken').toString('hex') };
  const wrongBlob = { ...example.files, [`blobs/${check}`]: '00' };
  const duplicate = { ...example.files, [recordPath]: Buffer.from('{"body":{},"body":{},"sigs":[]}').toString('hex') };
  for (const files of [example.files, edited, malformed, wrongBlob, duplicate]) assert.deepEqual(parse(files), nativeReport(files));
  assert.equal(parse(example.files).ok, true);assert.equal(parse(edited).ok, false);
});

test('portable reason is actually re-executed; wrong root and child bytes refuse', () => {
  const result = JSON.parse(run_check(JSON.stringify(example.files), check));
  assert.deepEqual(result, { verdict: 'pass', result: '887045bc22935aec5cba2dc11400d4e4357bc34d06681a6e92f06e7795b1f8a6', atp_spent: 20 });
  assert.throws(() => run_check(JSON.stringify({ ...example.files, [`blobs/${check}`]: '00' }), check), /content does not match/);
  const descriptor = JSON.parse(Buffer.from(example.files[`blobs/${check}`], 'hex').toString());
  assert.throws(() => run_check(JSON.stringify({ ...example.files, [`blobs/${descriptor.term}`]: '00' }), check), /content does not match/);
  const absent = { ...example.files };delete absent[`blobs/${check}`];assert.throws(() => run_check(JSON.stringify(absent), check), /missing/);
});

test('external trust explicitly selects settlement; malformed config fails closed', () => {
  const id = recordPath.slice(8, -5);
  const trust = JSON.stringify({ genesis_roots: [id], actors: { [env.body.actor.id]: [env.sigs[0].key] } });
  assert.deepEqual(parse(example.files, trust), nativeReport(example.files, trust));
  assert.equal(parse(example.files, trust).warnings, 0);
  assert.deepEqual(parse(example.files, '{broken'), nativeReport(example.files, '{broken'));
  assert.equal(parse(example.files, '{broken').ok, false);
  assert.equal(parse(example.files).grade, 'base');
});

test('browser admission and re-execution limits produce refusals', () => {
  assert.throws(() => verify_store('{}'), /at least one/);
  assert.throws(() => verify_store('{"records/a.json":"00","records/a.json":"00"}'));
  assert.throws(() => verify_store('{"records/../a.json":"00"}'), /Unsupported/);
  const doc = JSON.parse(Buffer.from(example.files[`blobs/${check}`], 'hex').toString());doc.atp = 1000001;
  const raw = Buffer.from(JSON.stringify(doc));const h = hash(raw);
  assert.throws(() => run_check(JSON.stringify({ ...example.files, [`blobs/${h}`]: raw.toString('hex') }), h), /budget/);
});

test('raw bytes survive transport; a standalone record obtains its computed ID', () => {
  const bytes = Uint8Array.from([0, 255, 10, 195]);assert.deepEqual(fromHex(toHex(bytes)), bytes);
  assert.equal(record_id(example.files[recordPath]), recordPath.slice(8, -5));
  assert.equal(normalizePath('my-pack/.warrants/records/a.json'), 'records/a.json');
  assert.equal(normalizePath('my-pack/manifest.json'), null);
  assert.throws(() => normalizePath('pack/../records/a.json'));
  assert.throws(() => validateFiles({ 'records/a.json': '0g' }));
});

test('a stopped worker rejects without returning a passing report', async () => {
  const saved = { Worker: globalThis.Worker, setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  let fire, worker, terminated = false;
  globalThis.Worker = class { constructor() { worker = this; } postMessage() {} terminate() { terminated = true; } };
  globalThis.setTimeout = callback => { fire = callback; return 1; };
  globalThis.clearTimeout = () => {};
  try {
    const timed = callVerifier('verify', example.files);
    fire(); await assert.rejects(timed, /incomplete/);assert.equal(terminated, true);
    terminated = false;
    const stopped = callVerifier('verify', example.files);
    worker.onerror();await assert.rejects(stopped, /No passing report/);assert.equal(terminated, true);
  } finally { Object.assign(globalThis, saved); }
});
