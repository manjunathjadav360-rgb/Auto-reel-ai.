/* Pure helpers (no DOM). Loaded by the dashboard and unit-tested with Node. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.AR = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const STYLES = {
    educational: "Educational",
    tech_explainer: "Tech / AI explainer",
    cinematic_story: "Cinematic story",
    motivational: "Motivational",
    comedy: "Comedy",
    product_ad_fictional: "Fictional product ad",
    typography_quote: "Typography / quote",
    festival: "Festival / seasonal",
  };
  const DURATIONS = [15, 30, 45, 60, 90];
  const STATUS_LABELS = {
    running: "Running", needs_review: "Needs review", approved: "Approved",
    rejected: "Rejected", failed: "Failed", qa_failed: "Quality check failed",
  };
  const SAFE_HOSTS = ["github.com", "githubusercontent.com", "pixabay.com"];
  const NAME_RE = /^[A-Za-z0-9_.-]{1,100}$/;
  const ID_RE = /^[0-9]{8}-[0-9]{6}-[a-z0-9-]{1,40}$/;

  function statusLabel(s) { return STATUS_LABELS[s] || String(s || "unknown"); }

  function isSafeUrl(u) {
    try {
      const x = new URL(u);
      return x.protocol === "https:" &&
        SAFE_HOSTS.some((h) => x.hostname === h || x.hostname.endsWith("." + h));
    } catch (e) { return false; }
  }

  function canDecide(p) {
    return !!p && ["needs_review", "approved", "rejected"].indexOf(p.status) >= 0 &&
      !(p.qa && p.qa.status === "fail");
  }

  function validateGenerate(v) {
    const errors = [];
    const topic = String((v && v.topic) || "").replace(/\s+/g, " ").trim();
    if (topic.length < 3 || topic.length > 200) errors.push("Topic must be 3-200 characters.");
    if (DURATIONS.indexOf(Number(v && v.duration)) < 0) errors.push("Choose a listed duration.");
    if (!Object.prototype.hasOwnProperty.call(STYLES, v && v.style)) errors.push("Choose a style.");
    return errors;
  }

  function workflowPage(cfg) {
    return "https://github.com/" + cfg.owner + "/" + cfg.repo + "/actions/workflows/studio.yml";
  }

  function dispatchRequest(cfg, inputs) {
    if (!cfg || !NAME_RE.test(cfg.owner || "") || !NAME_RE.test(cfg.repo || "") ||
        !NAME_RE.test(cfg.branch || "main")) throw new Error("Check owner, repository and branch in Settings.");
    if (!cfg.token) throw new Error("Add a GitHub token in Settings first.");
    const clean = {};
    Object.keys(inputs).forEach((k) => { clean[k] = String(inputs[k]); });
    if (clean.project_id !== undefined && !ID_RE.test(clean.project_id)) throw new Error("Invalid project id.");
    return {
      url: "https://api.github.com/repos/" + cfg.owner + "/" + cfg.repo + "/actions/workflows/studio.yml/dispatches",
      init: {
        method: "POST",
        headers: {
          Accept: "application/vnd.github+json",
          Authorization: "Bearer " + cfg.token,
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ref: cfg.branch || "main", inputs: clean }),
      },
    };
  }

  function sortProjects(rows) {
    return (rows || []).slice().sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
  }

  function formatDate(iso) {
    const d = new Date(iso);
    return isNaN(d) ? String(iso || "") : d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  }

  return { STYLES, DURATIONS, statusLabel, isSafeUrl, canDecide, validateGenerate,
           workflowPage, dispatchRequest, sortProjects, formatDate, ID_RE };
});
