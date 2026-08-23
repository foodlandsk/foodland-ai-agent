// tests/js/widget.test.mjs  -  V2.15d.1: frontend widget test tooling
// foundation (docs/frontend-widget-test-foundation-v2.15d.1.md).
//
// This is NOT the V2.15d.2 instrumentation sprint. It adds zero
// production telemetry and makes zero edits to app/widget.js. Its only
// job is to make a FUTURE edit to app/widget.js safely reviewable: a
// syntax error, or a new backend endpoint added without deliberate
// review, now fails CI instead of silently reaching production.
//
// Uses only Node's built-in test runner (node:test) and standard
// library modules - no package.json, no external npm dependency, per
// the sprint's "smallest reliable solution" principle (Section 10 of
// the closure spec).
//
// Run locally with: node --test tests/js/
// (requires Node.js 18+; this repository's CI pins Node 20 via
// actions/setup-node in .github/workflows/ci.yml)

import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import vm from "node:vm";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WIDGET_PATH = path.resolve(__dirname, "..", "..", "app", "widget.js");

function readWidgetSource() {
  // app/widget.js begins with a UTF-8 BOM. Node's own module loader
  // strips this automatically (which is why `node --check` handles the
  // file fine); fs.readFileSync does NOT, so vm.Script would otherwise
  // see a stray U+FEFF token and misreport a syntax error that does not
  // actually exist - stripping it here keeps this check honest.
  return fs.readFileSync(WIDGET_PATH, "utf8").replace(/^﻿/, "");
}

test("app/widget.js exists and is a substantial, non-truncated file", () => {
  const stat = fs.statSync(WIDGET_PATH);
  assert.ok(stat.isFile(), "app/widget.js must exist");
  assert.ok(stat.size > 10000, "app/widget.js looks truncated (unexpectedly small)");
});

test("app/widget.js has valid JavaScript syntax (node --check)", () => {
  // This is the mandatory syntax gate (Section 14 of the closure spec).
  // execFileSync throws on a non-zero exit code, i.e. on a syntax error.
  assert.doesNotThrow(() => {
    execFileSync(process.execPath, ["--check", WIDGET_PATH], { stdio: "pipe" });
  });
});

test("node --check actually rejects invalid JavaScript (proves the gate works)", () => {
  // Section 15 - do not merely add a command and assume it detects
  // anything. A deliberately broken fixture, written only to a temp
  // file, must fail the exact same check the previous test just passed.
  const tmpFile = path.join(os.tmpdir(), `v215d1-invalid-widget-fixture-${process.pid}.js`);
  fs.writeFileSync(tmpFile, "function broken( {\n  const x = ;\n");
  try {
    assert.throws(() => {
      execFileSync(process.execPath, ["--check", tmpFile], { stdio: "pipe" });
    });
  } finally {
    fs.unlinkSync(tmpFile);
  }
});

test("app/widget.js parses as a valid Script via an independent mechanism (node:vm)", () => {
  // A second, independent parser (V8's vm.Script, not the CLI's
  // --check flag) parsing the SAME source to the same conclusion rules
  // out a quirk specific to one checking mechanism. This is parse-only
  // - it does NOT execute the top-level IIFE, so no window/document/
  // browser globals need to be mocked (Section 16 - full runtime-load
  // validation is documented as LOAD_VALIDATION_NOT_YET_AVAILABLE in
  // docs/frontend-widget-test-foundation-v2.15d.1.md, not attempted
  // here).
  const source = readWidgetSource();
  assert.doesNotThrow(() => {
    new vm.Script(source, { filename: "widget.js" });
  });
});

test("app/widget.js introduces no new backend API endpoint (Section 47 - no-behavior-change check)", () => {
  // Frozen inventory as of V2.15d.1 (docs/frontend-widget-test-
  // foundation-v2.15d.1.md, Section 9/10/47 of the closure spec). A
  // genuinely new ${apiBaseUrl}/... call must update this list
  // deliberately in the same change, forcing conscious review rather
  // than a silent new production network target.
  const EXPECTED_API_ENDPOINTS = [
    "/chat",
    "/events",
    "/products/suggest",
    "/search/autocomplete",
    "/suggested-questions",
  ];
  const source = readWidgetSource();
  const found = new Set();
  const pattern = /\$\{apiBaseUrl\}(\/[a-zA-Z0-9/_-]*)/g;
  let match = pattern.exec(source);
  while (match !== null) {
    found.add(match[1]);
    match = pattern.exec(source);
  }
  assert.deepEqual(Array.from(found).sort(), [...EXPECTED_API_ENDPOINTS].sort());
});

test("app/widget.js's fetch() calls target exactly the known set of literal URLs (Section 34)", () => {
  // Section 34 characterization: app/widget.js also contains many
  // hardcoded https://www.foodland.sk/... string literals that are NOT
  // network calls at all (a static demo/fallback product catalog used
  // only when demoMode is active, plus a couple of default recipe/
  // article/product link fallbacks) - those are irrelevant here. This
  // narrows specifically to fetch() call targets that are literal
  // strings (not the ${apiBaseUrl}/... template calls, covered by the
  // previous test): today there is exactly one, the real add-to-cart
  // flow's cart-state readback (getCartState()).
  const source = readWidgetSource();
  const fetchLiteralUrls = [...source.matchAll(/fetch\(\s*["'`](https:\/\/[^"'`]*)["'`]/g)].map((m) =>
    m[1].split("?")[0]
  );
  assert.deepEqual(fetchLiteralUrls, ["https://www.foodland.sk/nakupny-kosik/"]);
});

test("app/widget.js does not reference interaction_id/decision_id (V2.15d.1 introduces no frontend correlation yet)", () => {
  // Hard scope boundary (Section 1/22/23 of the closure spec): this
  // sprint is tooling-only. If a future edit starts threading
  // interaction_id/decision_id into widget.js, that is V2.15d.2's job,
  // not this sprint's - this assertion documents the current, honest
  // state and will need deliberate updating when V2.15d.2 begins.
  const source = readWidgetSource();
  assert.equal(source.includes("interaction_id"), false);
  assert.equal(source.includes("decision_id"), false);
});
