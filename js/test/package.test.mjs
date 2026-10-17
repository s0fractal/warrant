import { test } from "node:test";
import assert from "node:assert/strict";
import {
  readFileSync,
  mkdtempSync,
  mkdirSync,
  writeFileSync,
  rmSync,
} from "node:fs";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { Worker } from "node:worker_threads";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { verifyStore, recordId, runCheck, toHex, LIMITS } from "../dist/mod.js";
const example = JSON.parse(
  readFileSync(new URL("../../web/dist/example.json", import.meta.url)),
);
const hash = (b) => createHash("sha256").update(b).digest("hex");
const record = Object.keys(example.files).find((p) => p.startsWith("records/"));
const env = JSON.parse(Buffer.from(example.files[record], "hex"));
const check = env.body.because[0].check;
const doc = JSON.parse(Buffer.from(example.files[`blobs/${check}`], "hex"));
function withDoc(descriptor, extra = {}) {
  const raw = Buffer.from(
    JSON.stringify(descriptor, Object.keys(descriptor).sort()),
  );
  const h = hash(raw);
  return {
    files: { ...example.files, ...extra, [`blobs/${h}`]: raw.toString("hex") },
    check: h,
  };
}
function nativeCheck(files, check) {
  const root = mkdtempSync(join(tmpdir(), "warrant-js-native-"));
  try {
    mkdirSync(join(root, "blobs"));
    mkdirSync(join(root, "records"));
    for (const [p, bytes] of Object.entries(files))
      writeFileSync(join(root, p), Buffer.from(bytes, "hex"));
    return spawnSync(
      resolve("../impl-rs/target/release/warrant-rs"),
      ["--store", root, "check", check],
      { encoding: "utf8" },
    );
  } finally {
    rmSync(root, { recursive: true });
  }
}
function workerCheck(payload) {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL("./deep-worker.mjs", import.meta.url), {
      workerData: payload,
    });
    const timer = setTimeout(() => {
      void worker.terminate();
      reject(new Error("worker time limit; no report"));
    }, 12000);
    worker.once("message", (value) => {
      clearTimeout(timer);
      void worker.terminate();
      resolve(value);
    });
    worker.once("error", (error) => {
      clearTimeout(timer);
      void worker.terminate();
      reject(error);
    });
  });
}
test("offline package preserves raw bytes, the closed report and explicit trust", () => {
  const fetch = globalThis.fetch;
  globalThis.fetch = () => {
    throw new Error("package must work offline");
  };
  try {
    const files = Object.fromEntries(
      Object.entries(example.files).map(([p, h]) => [
        p,
        new Uint8Array(Buffer.from(h, "hex")),
      ]),
    );
    assert.deepEqual(verifyStore(files), verifyStore(example.files));
    assert.equal(recordId(files[record]), record.slice(8, -5));
    assert.equal(verifyStore(files).warnings, 1);
    const trust = JSON.stringify({
      genesis_roots: [record.slice(8, -5)],
      actors: { [env.body.actor.id]: [env.sigs[0].key] },
    });
    assert.equal(verifyStore(files, { trust }).warnings, 0);
    assert.equal(verifyStore(files, { trust: "{bad" }).ok, false);
    // WRT-018: requireBound makes the actor's own unbound key an ERR, and only that.
    assert.equal(verifyStore(files, { trust, requireBound: true }).errors, 0);
    const otherKey = JSON.stringify({
      genesis_roots: [record.slice(8, -5)],
      actors: { [env.body.actor.id]: ["11".repeat(32)] },
    });
    assert.equal(verifyStore(files, { trust: otherKey }).errors, 0);
    const strict = verifyStore(files, { trust: otherKey, requireBound: true });
    assert.equal(strict.errors, 1);
    assert.ok(strict.findings.some((f) => f.message === "no bound signature by body.actor.id"));
    assert.throws(() => verifyStore(files, { requireBound: true }), /requireBound needs a trust/);
    const edited = structuredClone(env);
    edited.body.subject.note += " changed";
    assert.equal(
      verifyStore({
        ...files,
        [record]: new TextEncoder().encode(JSON.stringify(edited)),
      }).ok,
      false,
    );
    assert.equal(runCheck(files, check).atp_spent, 20);
  } finally {
    globalThis.fetch = fetch;
  }
});
test("declared ATP cap is inclusive; native and WASM intentionally differ above it", () => {
  for (const atp of [999999, 1000000, 1000001]) {
    const payload = withDoc({ ...doc, atp });
    const native = nativeCheck(payload.files, payload.check);
    assert.equal(native.status, 0, native.stderr);
    assert.match(native.stdout, /^pass/);
    if (atp <= LIMITS.atpPerCheck)
      assert.equal(runCheck(payload.files, payload.check).verdict, "pass");
    else assert.throws(() => runCheck(payload.files, payload.check), /budget/);
  }
});
test("LIMITS states the limits the embedded WASM build was made with", async () => {
  const built = JSON.parse(
    readFileSync(new URL("../dist/generated/build.json", import.meta.url)),
  );
  assert.equal(LIMITS.bytes, built.limits.bytes);
  assert.equal(LIMITS.files, built.limits.files);
  assert.equal(LIMITS.atpPerCheck, built.limits.atpPerCheck);
  const wasm = Buffer.from(
    (await import("../dist/generated/bytes.js")).binary,
    "base64",
  );
  assert.equal(hash(wasm), built.wasmSha256, "the embedded bytes are the ones build.json names");
});
test("runCheck needs blobs only, as the native `warrant check` does", () => {
  const blobsOnly = Object.fromEntries(
    Object.entries(example.files).filter(([p]) => p.startsWith("blobs/")),
  );
  assert.equal(runCheck(blobsOnly, check).verdict, "pass");
  assert.throws(() => verifyStore(blobsOnly), /records/);
});
test("deep evaluation either completes or raises a worker error, never a fabricated result", async () => {
  const atom = Buffer.concat([
    Buffer.from([0, 1]),
    createHash("sha256").update("I").digest(),
  ]);
  const i = hash(atom);
  let term = i;
  const blobs = { [`blobs/${i}`]: atom.toString("hex") };
  // The deepest stored spine the 2,048-file limit admits (atom + nodes + the
  // check blob), so the WASM stack is exercised at the input boundary itself.
  const depth = LIMITS.files - 2;
  for (let n = 0; n < depth; n++) {
    const raw = Buffer.concat([
      Buffer.from([2, 6]),
      Buffer.from(term, "hex"),
      Buffer.from(i, "hex"),
    ]);
    term = hash(raw);
    blobs[`blobs/${term}`] = raw.toString("hex");
  }
  const descriptor = { ski: 1, term, atp: 1000000, expect: i };
  const raw = Buffer.from(JSON.stringify(descriptor, Object.keys(descriptor).sort()));
  const payload = { files: { ...blobs, [`blobs/${hash(raw)}`]: raw.toString("hex") }, check: hash(raw) };
  assert.equal(Object.keys(payload.files).length, LIMITS.files);
  const native = nativeCheck(payload.files, payload.check);
  assert.equal(native.status, 0, native.stderr);
  assert.match(native.stdout, /^pass/);
  const actual = await workerCheck(payload);
  if (actual.error)
    assert.match(actual.error, /stack|unreachable|resource|memory/i);
  else assert.equal(actual.result.verdict, "pass");
  console.log(
    `depth ${depth}: native passes; WASM:`,
    actual.error || actual.result,
  );
  const fresh = await workerCheck({ files: example.files, check });
  assert.equal(fresh.result.verdict, "pass");
});

test("WRT-019: a P-256 signature made by an independent signer (node:crypto) verifies; high-S does not", async () => {
  const { generateKeyPairSync, sign } = await import("node:crypto");
  const N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551n;
  const { privateKey, publicKey } = generateKeyPairSync("ec", { namedCurve: "prime256v1" });
  const spki = publicKey.export({ format: "der", type: "spki" });
  const point = spki.subarray(spki.length - 65); // 04 || x || y
  const key = ((point[64] & 1) ? "03" : "02") + point.subarray(1, 33).toString("hex");
  const wid = record.slice(8, -5);
  const msg = Buffer.concat([Buffer.from("warrant-sig-v1:"), Buffer.from(wid, "hex")]);
  const raw = sign("sha256", msg, { key: privateKey, dsaEncoding: "ieee-p1363" });
  let s = BigInt("0x" + raw.subarray(32).toString("hex"));
  if (s > N / 2n) s = N - s;
  const r = raw.subarray(0, 32).toString("hex");
  const hex = (x) => x.toString(16).padStart(64, "0");
  const withSig = (sig) => ({
    ...example.files,
    [record]: Buffer.from(JSON.stringify({
      body: env.body,
      sigs: [{ actor: env.body.actor.id, alg: "ecdsa-p256-sha256", key, sig }],
    })).toString("hex"),
  });
  const trust = JSON.stringify({ genesis_roots: [wid], actors: { [env.body.actor.id]: [key] } });
  const low = verifyStore(withSig(r + hex(s)), { trust, requireBound: true });
  assert.equal(low.errors, 0, JSON.stringify(low.findings));
  const high = verifyStore(withSig(r + hex(N - s)), { trust, requireBound: true });
  assert.ok(high.errors >= 1, "high-S must not verify");
});
