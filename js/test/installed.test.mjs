// The artifact a stranger installs, not this checkout: `npm pack` the package,
// install the tarball into an empty project with no network, and use it there.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL("..", import.meta.url));
const example = new URL("../../web/dist/example.json", import.meta.url);

test("the packed tarball installs offline into an empty project and verifies", () => {
  const dir = mkdtempSync(join(tmpdir(), "warrant-js-installed-"));
  try {
    const packed = JSON.parse(
      execFileSync("npm", ["pack", here, "--json", "--pack-destination", dir], { encoding: "utf8" }),
    )[0];
    const names = packed.files.map((f) => f.path).sort();
    for (const want of ["LICENSE", "README.md", "dist/mod.js", "dist/mod.d.ts",
                        "dist/generated/bytes.js", "dist/generated/build.json",
                        "dist/generated/warrant_browser.js", "package.json"])
      assert.ok(names.includes(want), `tarball carries ${want}`);
    assert.ok(!names.some((n) => n.startsWith("test/") || n.endsWith(".py")),
              "tests and build scripts stay out of the tarball");
    writeFileSync(join(dir, "package.json"), JSON.stringify({ name: "consumer", private: true, type: "module" }));
    execFileSync("npm", ["install", "--offline", "--no-audit", "--no-fund", join(dir, packed.filename)],
                 { cwd: dir, stdio: "pipe" });
    writeFileSync(join(dir, "use.mjs"), `
      import { verifyStore, runCheck, LIMITS } from "@s0fractal/warrant";
      import { readFileSync } from "node:fs";
      const { files } = JSON.parse(readFileSync(${JSON.stringify(fileURLToPath(example))}, "utf8"));
      const r = verifyStore(files);
      const rec = Object.keys(files).find((p) => p.startsWith("records/"));
      const env = JSON.parse(Buffer.from(files[rec], "hex"));
      const c = runCheck(files, env.body.because[0].check);
      console.log(JSON.stringify({ report: r.report, ok: r.ok, verdict: c.verdict, atp: LIMITS.atpPerCheck }));
    `);
    const out = JSON.parse(execFileSync("node", ["use.mjs"], { cwd: dir, encoding: "utf8" }));
    assert.deepEqual(out, { report: "warrant.verify-report@v0", ok: true, verdict: "pass", atp: 1000000 });
    const meta = JSON.parse(readFileSync(join(dir, "node_modules/@s0fractal/warrant/dist/generated/build.json")));
    assert.equal(meta.packageVersion, JSON.parse(readFileSync(join(here, "package.json"))).version);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
