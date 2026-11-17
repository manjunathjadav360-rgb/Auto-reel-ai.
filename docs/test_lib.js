const test = require("node:test");
const assert = require("node:assert");
const AR = require("./lib.js");

const cfg = { owner: "me", repo: "Auto-reel-ai", branch: "main", token: "ghp_x" };

test("dispatch request shape and token only in header", () => {
  const r = AR.dispatchRequest(cfg, { action: "generate", topic: "Tides", duration: 30, style: "educational" });
  assert.strictEqual(r.url, "https://api.github.com/repos/me/Auto-reel-ai/actions/workflows/studio.yml/dispatches");
  assert.strictEqual(r.init.headers.Authorization, "Bearer ghp_x");
  assert.ok(!r.url.includes("ghp_x") && !r.init.body.includes("ghp_x"));
  assert.deepStrictEqual(JSON.parse(r.init.body).inputs.duration, "30");   // inputs are strings
});
test("dispatch refuses bad config, missing token, bad project id", () => {
  assert.throws(() => AR.dispatchRequest({ ...cfg, token: "" }, {}), /token/i);
  assert.throws(() => AR.dispatchRequest({ ...cfg, owner: "a/b" }, {}), /Settings/);
  assert.throws(() => AR.dispatchRequest(cfg, { action: "decide", project_id: "../x" }), /project id/);
  assert.doesNotThrow(() => AR.dispatchRequest(cfg, { action: "decide", project_id: "20261116-103000-demo" }));
});
test("url safety", () => {
  assert.ok(AR.isSafeUrl("https://github.com/me/r/releases/download/t/final.mp4"));
  assert.ok(AR.isSafeUrl("https://release-assets.githubusercontent.com/x"));
  for (const u of ["javascript:alert(1)", "http://github.com/x", "https://github.com.evil.com/x", "https://evil.com/github.com", "data:text/html,x"])
    assert.ok(!AR.isSafeUrl(u), u);
});
test("generate validation", () => {
  assert.deepStrictEqual(AR.validateGenerate({ topic: "Why tides happen", duration: 30, style: "educational" }), []);
  assert.strictEqual(AR.validateGenerate({ topic: "x", duration: 7, style: "nope" }).length, 3);
  assert.strictEqual(AR.validateGenerate({ topic: "ok topic", duration: "45", style: "__proto__" }).length, 1);
});
test("decision rules", () => {
  assert.ok(AR.canDecide({ status: "needs_review", qa: { status: "warn" } }));
  assert.ok(!AR.canDecide({ status: "needs_review", qa: { status: "fail" } }));
  assert.ok(!AR.canDecide({ status: "failed" }));
  assert.ok(!AR.canDecide(null));
});
test("sorting newest first", () => {
  const rows = [{ created_at: "2026-11-16T10:00:00Z", id: "a" }, { created_at: "2026-11-17T10:00:00Z", id: "b" }];
  assert.deepStrictEqual(AR.sortProjects(rows).map((r) => r.id), ["b", "a"]);
});
