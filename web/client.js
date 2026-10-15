/** Browser-only transport. No verification logic lives in this module. */
export const LIMITS = Object.freeze({
  bytes: 8 * 1024 * 1024,
  files: 2048,
  timeout: 12000,
});
export const toHex = (bytes) =>
  Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
export function fromHex(hex) {
  if (typeof hex !== "string" || hex.length % 2 || !/^[0-9a-f]*$/i.test(hex))
    throw new Error("Invalid file bytes");
  return Uint8Array.from(hex.match(/../g) || [], (h) => Number.parseInt(h, 16));
}
export function normalizePath(path) {
  const parts = path.replaceAll("\\", "/").split("/");
  if (parts.some((p) => p === ".." || p === "."))
    throw new Error(
      "Please select a store folder with ordinary relative paths.",
    );
  const at = parts.findIndex((p) => p === "records" || p === "blobs");
  if (at >= 0 && parts.length === at + 2) return parts.slice(at).join("/");
  if (parts.at(-1) === "genesis.json") return "genesis.json";
  return null;
}
export function validateFiles(files) {
  const entries = Object.entries(files);
  if (entries.length > LIMITS.files)
    throw new Error(
      "Browser limit: 2048 files. Use the CLI for larger stores.",
    );
  let bytes = 0;
  for (const [path, hex] of entries) {
    if (
      !/^(records\/[^/\\]+\.json|blobs\/[0-9a-f]{64}|genesis\.json)$/.test(path)
    )
      throw new Error(`Unsupported store path: ${path}`);
    if (typeof hex !== "string" || hex.length % 2 || !/^[0-9a-f]*$/i.test(hex))
      throw new Error(`Invalid bytes for ${path}`);
    bytes += hex.length / 2;
  }
  if (bytes > LIMITS.bytes)
    throw new Error("Browser limit: 8 MiB. Use the CLI for larger stores.");
  if (!entries.some(([p]) => p.startsWith("records/")))
    throw new Error(
      "No records found. Select a .warrants folder or a record JSON file.",
    );
}

export function callVerifier(operation, files, options = {}) {
  validateFiles(files);
  return new Promise((resolve, reject) => {
    const { signal, ...payloadOptions } = options;
    const worker = new Worker(new URL("./worker.js", import.meta.url), {
      type: "module",
    });
    let settled = false;
    const timer = setTimeout(
      () =>
        finish(
          new Error(
            "Local time limit reached. Verification is incomplete; no passing report was produced. Use the CLI for this store.",
          ),
        ),
      LIMITS.timeout,
    );
    const cancel = () =>
      finish(
        new Error(
          "Stopped by you. Verification is incomplete; no passing report was produced.",
        ),
      );
    const finish = (error, result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", cancel);
      worker.terminate();
      if (error) reject(error);
      else resolve(result);
    };
    if (signal?.aborted) {
      cancel();
      return;
    }
    signal?.addEventListener("abort", cancel, { once: true });
    worker.onmessage = (event) =>
      event.data.error
        ? finish(new Error(event.data.error))
        : finish(null, event.data.result);
    worker.onerror = () =>
      finish(
        new Error(
          "The verifier stopped before completion. No passing report was produced. Try the CLI for this input.",
        ),
      );
    worker.postMessage({ operation, files, ...payloadOptions });
  });
}

export function identifyRecord(hex) {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL("./worker.js", import.meta.url), {
      type: "module",
    });
    const finish = (error, result) => {
      clearTimeout(timer);
      worker.terminate();
      error ? reject(error) : resolve(result);
    };
    const timer = setTimeout(
      () =>
        finish(
          new Error("Could not read this record within the local time limit."),
        ),
      LIMITS.timeout,
    );
    worker.onerror = () => finish(new Error("Could not read this record."));
    worker.onmessage = (e) =>
      e.data.error
        ? finish(new Error(e.data.error))
        : finish(null, e.data.result);
    worker.postMessage({ operation: "identify", hex });
  });
}
