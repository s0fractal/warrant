import init, {
  verify_store,
  record_id,
  run_check,
} from "./wasm/warrant_browser.js";

self.onmessage = async ({ data }) => {
  try {
    await init();
    if (data.operation === "identify") {
      self.postMessage({ result: record_id(data.hex) });
      return;
    }
    const input = JSON.stringify(data.files);
    const report = JSON.parse(verify_store(input, data.trust ?? undefined));
    const checks = [];
    // Presentation only: the report above is produced by the core verifier.
    // Additional explicit re-runs explain each portable reason to the reader.
    for (const [path, hex] of Object.entries(data.files)) {
      if (!path.startsWith("records/")) continue;
      try {
        const raw = Uint8Array.from(hex.match(/../g) || [], (h) =>
          Number.parseInt(h, 16),
        );
        const env = JSON.parse(
          new TextDecoder("utf-8", { fatal: true }).decode(raw),
        );
        for (const reason of env.body?.because || []) {
          if (reason.kind !== "check" || reason.runtime !== "ski@v1") continue;
          try {
            checks.push({
              check: reason.check,
              filedVerdict: reason.verdict,
              ...JSON.parse(run_check(input, reason.check)),
            });
          } catch (e) {
            checks.push({
              check: reason.check,
              filedVerdict: reason.verdict,
              error: String(e),
            });
          }
        }
      } catch {
        /* Malformed bytes remain core report errors, never skipped there. */
      }
    }
    self.postMessage({ result: { report, checks } });
  } catch (error) {
    self.postMessage({ error: String(error?.message || error) });
  }
};
