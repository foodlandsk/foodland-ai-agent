// tests/js/widget.test.mjs  -  V2.15d.1 test tooling foundation
// (docs/frontend-widget-test-foundation-v2.15d.1.md), extended by
// V2.15d.2 (docs/frontend-recommendation-correlation-v2.15d.2.md) to
// cover the new interaction_id/decision_id correlation and the
// PRODUCT_CLICK / ADD_TO_CART_ATTEMPT / ADD_TO_CART_CONFIRMED semantic
// split. All checks here are STATIC source inspection - no Node.js is
// available on the local dev machine that authored this file, so every
// assertion is regex/string-based against the real app/widget.js
// source rather than a runtime DOM execution. CI (Node 20) is the
// authoritative oracle; every pattern below was cross-validated with
// Python's `re` against the actual file before being committed.
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

// ---------------------------------------------------------------------
// V2.15d.2 - decision id resolution (Section 13/14 of the closure spec)
// ---------------------------------------------------------------------

test("decisionId resolution picks whichever capability-specific field the backend returned, never fabricates one", () => {
  const source = readWidgetSource();
  assert.ok(
    source.includes(
      "data.comparison_decision_id || data.basket_decision_id || data.use_case_advice_decision_id || null"
    ),
    "decisionId must fall back to null for ordinary product search (Section 41) - never invent an id"
  );
});

test("product_id contract unchanged: fireEvent still keys product identity off product.id (Section 17)", () => {
  const source = readWidgetSource();
  assert.ok(source.includes("product_sku: product.id"));
});

// ---------------------------------------------------------------------
// PRODUCT_CLICK / ADD_TO_CART_ATTEMPT / ADD_TO_CART_CONFIRMED
// (Section 18-23 - these must remain three distinct, non-conflated events)
// ---------------------------------------------------------------------

test("the three cart-lifecycle event types are all distinct string literals in source", () => {
  const source = readWidgetSource();
  assert.ok(source.includes('"click"'));
  assert.ok(source.includes('"add_to_cart_attempt"'));
  assert.ok(source.includes('"add_to_cart_confirmed"'));
});

test("legacy \"add_to_cart\" event type is preserved unchanged (backward compat with app.fbt/app.behavioral/app.learning_signals)", () => {
  const source = readWidgetSource();
  assert.ok(source.includes('event_type: "add_to_cart"'));
});

test("ADD_TO_CART_ATTEMPT fires before the cart-mutation attempt begins (Section 20 - initiation, not outcome)", () => {
  const source = readWidgetSource();
  const attemptIdx = source.indexOf('event_type: "add_to_cart_attempt"');
  const tryIdx = source.indexOf("try {", attemptIdx);
  assert.ok(attemptIdx > -1 && tryIdx > attemptIdx, "add_to_cart_attempt must fire before the try{} that calls addToCart()");
});

test("ADD_TO_CART_CONFIRMED is gated on the authoritative flag, never fired unconditionally (Section 21-23)", () => {
  const source = readWidgetSource();
  const confirmedBlockMatch = source.match(/if \(cartResult && cartResult\.attempted && cartResult\.authoritative\) \{\s*fireEvent\(\{ event_type: "add_to_cart_confirmed"/);
  assert.ok(confirmedBlockMatch, "add_to_cart_confirmed must be inside an `if (... .authoritative)` guard");
});

test("the fallback timeout path resolves with authoritative=false, the real XHR-confirmed path resolves with authoritative=true", () => {
  // Section 22/23 - the highest-risk semantic point of this sprint.
  // finish(null, false) is the fallback-timeout guess; finish(null, true)
  // is reached ONLY inside the intercepted XHR's `data.success` branch.
  const source = readWidgetSource();
  assert.ok(source.includes("finish(null, false)"), "fallback timeout must resolve non-authoritative");
  assert.ok(source.includes("finish(null, true)"), "real host confirmation must resolve authoritative");
  const successBranch = source.match(/if \(data && data\.success\) finish\(null, true\);/);
  assert.ok(successBranch, "authoritative=true must be directly gated on the host's own data.success flag");
});

test("addToCart() returns {attempted:false} when the cart mechanism was never even initiated (off-site/no product link)", () => {
  const source = readWidgetSource();
  assert.ok(source.includes("return { attempted: false, authoritative: false };"));
});

test("confirmed fireEvent call textually follows the awaited addToCart() call (causal ordering, Section 61)", () => {
  const source = readWidgetSource();
  const awaitIdx = source.indexOf("await addToCart(product)");
  const confirmedIdx = source.indexOf('event_type: "add_to_cart_confirmed"');
  assert.ok(awaitIdx > -1 && confirmedIdx > awaitIdx);
});

// ---------------------------------------------------------------------
// Honesty / non-fabrication (Section 1/2/24/39)
// ---------------------------------------------------------------------

test("no PURCHASE/order-confirmation event is fabricated anywhere in source", () => {
  const source = readWidgetSource();
  assert.equal(/purchase|order_confirmed|order_complete/i.test(source), false);
});

test("no learning/ranking/promotion call was introduced (Sections 3/32/38 hard freeze)", () => {
  const source = readWidgetSource();
  assert.equal(/AUTO_PROMOTION|learning_lifecycle|ranking_optimizer|ranking_config/.test(source), false);
});

// ---------------------------------------------------------------------
// Telemetry failure isolation (Section 29 - unchanged from V2.15d.1 baseline)
// ---------------------------------------------------------------------

test("fireEvent() still swallows every failure mode (sync throw + fetch rejection) - commerce must never depend on telemetry", () => {
  const source = readWidgetSource();
  assert.match(source, /function fireEvent\(payload\) \{\s*if \(demoMode\) return;\s*try \{/);
  assert.ok(source.includes("}).catch(function () {});"), "fetch rejection must still be silently swallowed");
});

// ---------------------------------------------------------------------
// V2.15e.1 - resultset continuation attribution
// (docs/resultset-continuation-attribution-v2.15e.1.md)
//
// GATE B: result_set_id is the backend's already-existing, STABLE
// per-search identifier (app.result_sets.ResultSet.result_set_id) that
// survives a "Show More"/"Show All" continuation unchanged - unlike
// interaction_id, which is legitimately fresh on every single /chat
// call. The gap closed here is purely that app/widget.js never read or
// forwarded it; the identity model itself required no new backend
// concept.
// ---------------------------------------------------------------------

test("initial-response stash writes result_set_id onto every product object, alongside interaction_id/decision_id", () => {
  const source = readWidgetSource();
  assert.ok(
    source.includes(
      "p.interaction_id = data.interaction_id || null;\n            p.decision_id = decisionId;\n            p.result_set_id = data.result_set_id || null;"
    ),
    "the primary data.products stash block must set result_set_id from data.result_set_id, never fabricate it"
  );
});

test("cart-candidate fallback stash also carries result_set_id (Section 32 - both product-bearing branches, not just the primary one)", () => {
  const source = readWidgetSource();
  const candidateBlock = source.match(
    /candidateProducts\.forEach\(function \(p\) \{\s*p\.interaction_id = data\.interaction_id \|\| null;\s*p\.decision_id = decisionId;\s*p\.result_set_id = data\.result_set_id \|\| null;\s*\}\);/
  );
  assert.ok(candidateBlock, "cartCandidatesToProducts() branch must stash result_set_id identically to the primary branch");
});

test("continuation responses reuse the SAME stash code path as an initial search (no separate/bypassable branch for Show More)", () => {
  // Characterization finding: a "zobraz viac"/"zobraz vsetky" response
  // has intent product_search (never "recipe", the only branch this
  // block excludes), so it is provably NOT possible for continuation to
  // skip this stash logic - there is only one such block in the file.
  const source = readWidgetSource();
  const occurrences = source.match(/p\.result_set_id = data\.result_set_id \|\| null;/g) || [];
  assert.equal(occurrences.length, 2, "exactly two stash sites (primary products + cart-candidate fallback), no third/duplicate continuation-only branch");
});

test("all 5 renderCard() fireEvent() calls (view click, cart click, attempt, legacy add_to_cart, confirmed) include result_set_id", () => {
  const source = readWidgetSource();
  const eventTypes = ["click", "click", "add_to_cart_attempt", "add_to_cart", "add_to_cart_confirmed"];
  const fireEventCalls = [...source.matchAll(/fireEvent\(\{ event_type: "(click|add_to_cart_attempt|add_to_cart|add_to_cart_confirmed)"[^}]*\}\);/g)];
  assert.equal(fireEventCalls.length, 5, `expected exactly 5 renderCard fireEvent() calls, found ${fireEventCalls.length}`);
  fireEventCalls.forEach((m) => {
    assert.ok(
      m[0].includes("result_set_id: product.result_set_id || null"),
      `fireEvent for event_type "${m[1]}" must forward product.result_set_id, never fabricate it: ${m[0]}`
    );
  });
});

test("the impression event includes result_set_id sourced from data.result_set_id, never from a product-level field", () => {
  const source = readWidgetSource();
  const impressionBlock = source.match(
    /fireEvent\(\{\s*event_type: "impression",\s*query: text,\s*product_skus: data\.products\.map\(function \(p\) \{ return p\.id; \}\)\.filter\(Boolean\),\s*interaction_id: data\.interaction_id \|\| null,\s*decision_id: decisionId,\s*result_set_id: data\.result_set_id \|\| null,\s*\}\);/
  );
  assert.ok(impressionBlock, "impression event must include result_set_id: data.result_set_id || null");
});

test("result_set_id is never hardcoded/fabricated as a string literal anywhere near the stash or fireEvent sites", () => {
  const source = readWidgetSource();
  // Every result_set_id assignment in the file must be a `|| null`
  // fallback read off data/product, never a bare string literal - this
  // rules out a stray hardcoded id sneaking into a fireEvent payload.
  const assignments = [...source.matchAll(/result_set_id:\s*([^,}\n]+)/g)].map((m) => m[1].trim());
  assert.ok(assignments.length >= 6, "expected at least 6 result_set_id: ... sites (5 fireEvent + 1 impression)");
  assignments.forEach((expr) => {
    assert.match(expr, /^(data|product)\.result_set_id \|\| null$/, `unexpected result_set_id expression: ${expr}`);
  });
});
