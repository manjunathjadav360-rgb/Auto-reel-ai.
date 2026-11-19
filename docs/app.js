/* Dashboard. All server/LLM text is rendered with textContent (never innerHTML). */
(function () {
  "use strict";
  var app = document.getElementById("app");
  var nav = document.getElementById("nav");
  var KEY = "autoreel.cfg";
  var DEFAULTS = { owner: "manjunathjadav360-rgb", repo: "Auto-reel-ai.", branch: "main", token: "" };
  var TABS = [["review", "Review"], ["library", "Library"], ["ideas", "Ideas"], ["create", "Create"], ["settings", "Settings"]];

  function loadCfg() {
    try {
      var cfg = Object.assign({}, DEFAULTS, JSON.parse(localStorage.getItem(KEY) || "{}"));
      if (cfg.owner === "manjunathjadav360-rgb" && cfg.repo === "Auto-reel-ai") cfg.repo = "Auto-reel-ai.";
      return cfg;
    } catch (e) { return Object.assign({}, DEFAULTS); }
  }
  function saveCfg(c) { localStorage.setItem(KEY, JSON.stringify(c)); }

  function url(u) {
    if (typeof u !== "string" || !u) return "#";
    if (AR.isSafeUrl(u)) return u;
    if (/^#\/[\w\-/]*$/.test(u)) return u;                 // in-app route
    return /^output\/[\w\-./]+$/.test(u) ? u : "#";
  }
  function h(tag, attrs) {
    var el = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k];
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.indexOf("on") === 0) el.addEventListener(k.slice(2), v);
      else if (k === "href" || k === "src" || k === "poster") el.setAttribute(k, url(v));
      else if (v === true) el.setAttribute(k, "");
      else if (v !== false && v != null) el.setAttribute(k, v);
    });
    (function add(list) {
      list.forEach(function (c) {
        if (c == null || c === false) return;
        if (Array.isArray(c)) return add(c);                    // allow arrays of children
        el.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
      });
    })(Array.prototype.slice.call(arguments, 2));
    return el;
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }
  function msg(kind, text) { return h("div", { class: "msg " + (kind === "err" ? "err" : "okm"), role: "status", text: text }); }

  function getJSON(path) {
    return fetch(path + "?t=" + Date.now(), { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error(path + " returned " + r.status);
      return r.json();
    });
  }

  function dispatch(inputs) {
    var req = AR.dispatchRequest(loadCfg(), inputs);          // throws helpful errors
    return fetch(req.url, req.init).then(function (r) {
      if (r.status === 204) return;
      return r.json().catch(function () { return {}; }).then(function (b) {
        throw new Error("GitHub said " + r.status + (b.message ? ": " + b.message : ""));
      });
    });
  }

  function copy(text, btn) {
    var done = function () { var o = btn.textContent; btn.textContent = "Copied"; setTimeout(function () { btn.textContent = o; }, 1200); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, function () { window.prompt("Copy:", text); });
    else window.prompt("Copy:", text);
  }

  function renderNav(active) {
    clear(nav);
    TABS.forEach(function (t) { nav.appendChild(h("a", { href: "#/" + t[0], class: active === t[0] ? "on" : "", text: t[1] })); });
  }

  function badge(text, cls) { return h("span", { class: "badge " + (cls || ""), text: text }); }

  function projectCard(p) {
    return h("a", { href: "#/p/" + p.id, class: "card row", style: "text-decoration:none;color:inherit" },
      p.thumbnail_url ? h("img", { src: p.thumbnail_url, alt: "", loading: "lazy" }) : h("div", { class: "thumb" }),
      h("div", { class: "grow" },
        h("strong", { text: p.title || p.topic }),
        h("div", {}, badge(AR.statusLabel(p.status), p.status), p.qa_status ? badge("QA: " + p.qa_status, p.qa_status) : null),
        h("div", { class: "mut", text: (AR.STYLES[p.style] || p.style) + " · " + (p.duration_target || "?") + "s · " + AR.formatDate(p.created_at) })));
  }

  function viewList(kind) {
    renderNav(kind);
    clear(app);
    app.appendChild(h("p", { class: "mut", text: "Loading…" }));
    getJSON("data/index.json").then(function (idx) {
      var rows = AR.sortProjects(idx.projects);
      if (kind === "review") rows = rows.filter(function (r) { return r.status === "needs_review"; });
      clear(app);
      app.appendChild(h("h2", { text: kind === "review" ? "Waiting for your review" : "All projects" }));
      if (!rows.length) app.appendChild(h("p", { class: "mut", text: kind === "review" ? "Nothing to review. Use Create to make a video." : "No projects yet." }));
      rows.forEach(function (r) { app.appendChild(projectCard(r)); });
    }).catch(function (e) { clear(app); app.appendChild(msg("err", "Could not load the project list: " + e.message)); });
  }

  function section(title, body) { return h("div", { class: "card" }, h("strong", { text: title }), body); }

  function viewProject(id) {
    renderNav("");
    clear(app);
    if (!AR.ID_RE.test(id)) { app.appendChild(msg("err", "Invalid project id.")); return; }
    getJSON("data/projects/" + id + ".json").then(function (p) {
      clear(app);
      app.appendChild(h("p", {}, h("a", { href: "#/library", text: "← Back" })));
      app.appendChild(h("h2", { text: p.title || p.topic }));
      app.appendChild(h("div", {}, badge(AR.statusLabel(p.status), p.status), p.qa ? badge("QA: " + p.qa.status, p.qa.status) : null));
      if (p.status === "failed") {
        app.appendChild(msg("err", "This run failed: " + (p.error || "unknown error")));
      }
      var a = p.assets || {};
      if (a.video_url) {
        var v = h("video", { controls: true, playsinline: true, preload: "metadata", poster: a.thumbnail_url, src: a.video_url });
        var note = h("p", { class: "mut", text: "" });
        v.addEventListener("error", function () { note.textContent = "The browser could not preview this file. Use Download instead."; });
        app.appendChild(v); app.appendChild(note);
        app.appendChild(h("div", { class: "actions" },
          h("a", { class: "btn primary", href: a.video_url, download: true, text: "Download MP4" }),
          h("a", { class: "btn", href: a.thumbnail_url, download: true, text: "Thumbnail" }),
          h("a", { class: "btn", href: a.captions_url, download: true, text: "Captions (.srt)" })));
        if (a.transitions && a.transitions.length)
          app.appendChild(h("p", { class: "mut", text: "Editorial transitions: " + a.transitions.join(" → ") }));
      }
      decisionBox(p);
      if (p.publish) publishBox(p);
      if (p.qa) app.appendChild(qaBox(p.qa));
      if (p.script && p.script.claims_to_verify && p.script.claims_to_verify.length)
        app.appendChild(section("Claims to verify before posting", h("ul", {}, p.script.claims_to_verify.map(function (c) { return h("li", { text: c }); }))));
      if (p.script) app.appendChild(scriptBox(p));
      var lic = [];
      if (p.narration) lic.push("Voice: " + p.narration.engine + " (" + p.narration.voice + "). " + p.narration.license_note);
      if (p.music) lic.push("Music: " + p.music.source + ". " + p.music.rights);
      if (lic.length) app.appendChild(section("Voice and music rights", h("div", {}, lic.map(function (t) { return h("p", { class: "mut", text: t }); }))));
      if (p.credits) app.appendChild(section("Media credits", h("pre", { text: p.credits })));
      if (p.log) app.appendChild(logBox(p.log));
    }).catch(function (e) { clear(app); app.appendChild(msg("err", "Could not load this project: " + e.message)); });
  }

  function decisionBox(p) {
    var cfg = loadCfg(), box = h("div", { class: "card" }), out = h("div", {});
    box.appendChild(h("strong", { text: "Decision" }));
    if (p.approval && p.approval.decision) box.appendChild(h("p", { class: "mut", text: "Last decision: " + p.approval.decision + " at " + AR.formatDate(p.approval.at) + (p.approval.note ? " — " + p.approval.note : "") }));
    var note = h("input", { type: "text", maxlength: "200", placeholder: "Optional note" });
    function send(decision) {
      out.replaceChildren(msg("ok", "Sending…"));
      dispatch({ action: "decide", project_id: p.id, decision: decision, note: note.value })
        .then(function () { out.replaceChildren(msg("ok", "Sent. The change is committed in about a minute; reload this page then.")); })
        .catch(function (e) { out.replaceChildren(msg("err", e.message)); });
    }
    var can = AR.canDecide(p) && !!cfg.token;
    box.appendChild(note);
    box.appendChild(h("div", { class: "actions" },
      h("button", { class: "primary", disabled: !can, onclick: function () { send("approve"); }, text: "Approve" }),
      h("button", { class: "danger", disabled: !can, onclick: function () { send("reject"); }, text: "Reject" })));
    if (!AR.canDecide(p)) box.appendChild(h("p", { class: "mut", text: "This project cannot be approved in its current state." }));
    else if (!cfg.token) box.appendChild(h("p", { class: "mut" }, "To approve from here add a token in ", h("a", { href: "#/settings", text: "Settings" }), ", or run the Studio workflow on GitHub: ", h("a", { href: AR.workflowPage(cfg), text: "open workflow" }), "."));
    box.appendChild(h("p", { class: "mut", text: "Approval marks the video as ready. It does not post anywhere." }));
    box.appendChild(out);
    app.appendChild(box);
  }

  function publishBox(p) {
    var pub = p.publish, tags = (pub.hashtags || []).join(" ");
    var box = h("div", { class: "card" }, h("strong", { text: "Instagram package (manual posting)" }),
      h("p", { class: "mut", text: "Suggested time: " + (pub.suggested_time || "n/a") }),
      h("textarea", { readonly: true, text: pub.caption || "" }));
    var b1 = h("button", { text: "Copy caption" }), b2 = h("button", { text: "Copy hashtags" });
    b1.addEventListener("click", function () { copy(pub.caption || "", b1); });
    b2.addEventListener("click", function () { copy(tags, b2); });
    box.appendChild(h("p", { class: "mut", text: tags }));
    box.appendChild(h("div", { class: "actions" }, b1, b2));
    app.appendChild(box);
  }

  function qaBox(qa) {
    var rows = (qa.checks || []).map(function (c) { return h("tr", {}, h("td", { class: c.status, text: c.status.toUpperCase() }), h("td", { text: c.name }), h("td", { text: c.detail })); });
    return section("Quality report", h("table", {}, rows));
  }

  function scriptBox(p) {
    var d = h("details", {}, h("summary", { text: "Script and storyboard (" + p.script.scenes.length + " scenes)" }));
    p.script.scenes.forEach(function (s, i) {
      var vis = (p.scene_visuals || [])[i] || {};
      var src = vis.asset ? h("a", { href: vis.asset.page_url, text: vis.type + " by " + (vis.asset.creator || "unknown") }) : h("span", { text: vis.type === "text" ? "typography card" : (vis.type || "") });
      d.appendChild(h("div", { class: "card" }, h("div", { class: "mut", text: "Scene " + (i + 1) }), h("p", { text: s.narration }),
        s.on_screen_text ? h("p", { class: "mut", text: "On-screen: " + s.on_screen_text }) : null,
        h("div", { class: "mut" }, "Visual: ", src, " · search: " + (vis.query || s.search_query))));
    });
    return d;
  }

  function logBox(log) {
    var rows = log.map(function (e) { return h("tr", {}, h("td", { class: e.ok ? "pass" : "fail", text: e.ok ? "OK" : "FAIL" }), h("td", { text: e.stage }), h("td", { text: e.seconds + "s" }), h("td", { text: e.message || "" })); });
    return h("details", {}, h("summary", { text: "Production log" }), h("table", {}, rows));
  }

  function viewIdeas() {
    renderNav("ideas"); clear(app);
    app.appendChild(h("h2", { text: "Ideas" }));
    app.appendChild(h("p", { class: "mut", text: "Ideas come from public signals (Hacker News front page, Wikipedia most-viewed) turned into suggestions by Gemini. They show what people read, not verified Instagram trends." }));
    getJSON("data/ideas.json").then(function (data) {
      app.appendChild(h("p", { class: "mut", text: "Generated " + AR.formatDate(data.generated_at) }));
      (data.ideas || []).forEach(function (i) {
        app.appendChild(h("div", { class: "card" }, h("strong", { text: i.title || i.topic }), h("p", { text: i.topic }),
          i.hook ? h("p", { class: "mut", text: "Hook: " + i.hook }) : null, i.why_now ? h("p", { class: "mut", text: "Why now: " + i.why_now }) : null,
          h("button", { onclick: function () { sessionStorage.setItem("autoreel.prefill", JSON.stringify({ topic: i.topic, style: i.style })); location.hash = "#/create"; }, text: "Use this idea" })));
      });
    }).catch(function () { app.appendChild(h("p", { class: "mut", text: "No ideas yet. The Studio workflow's “research” action creates them." })); });
    var out = h("div", {});
    app.appendChild(h("div", { class: "actions" }, h("button", { onclick: function () {
      dispatch({ action: "research", style: "educational" }).then(function () { out.replaceChildren(msg("ok", "Research started. Reload in about a minute.")); }).catch(function (e) { out.replaceChildren(msg("err", e.message)); });
    }, text: "Run research now" })), out);
  }

  function viewCreate() {
    renderNav("create"); clear(app);
    var pre = {}; try { pre = JSON.parse(sessionStorage.getItem("autoreel.prefill") || "{}"); sessionStorage.removeItem("autoreel.prefill"); } catch (e) { pre = {}; }
    var cfg = loadCfg();
    var topic = h("textarea", { maxlength: "200", placeholder: "e.g. Why tides happen twice a day" }); topic.value = pre.topic || "";
    var dur = h("select", {}, AR.DURATIONS.map(function (d) { return h("option", { value: d, text: d + " seconds" }); })); dur.value = "30";
    var style = h("select", {}, Object.keys(AR.STYLES).map(function (k) { return h("option", { value: k, text: AR.STYLES[k] }); })); if (pre.style) style.value = pre.style;
    var out = h("div", {});
    var go = h("button", { class: "primary", disabled: !cfg.token, text: "Generate video", onclick: function () {
      var errs = AR.validateGenerate({ topic: topic.value, duration: dur.value, style: style.value });
      if (errs.length) { out.replaceChildren(msg("err", errs.join(" "))); return; }
      out.replaceChildren(msg("ok", "Sending…"));
      dispatch({ action: "generate", topic: topic.value.replace(/\s+/g, " ").trim(), duration: dur.value, style: style.value })
        .then(function () { out.replaceChildren(msg("ok", "Your Reel is in production on GitHub's cloud runner. A recent 30-second render finished in under 2 minutes; a fresh or busy runner can take longer."), h("a", { href: AR.workflowPage(cfg), text: "Watch production in GitHub Actions" })); })
        .catch(function (e) { out.replaceChildren(msg("err", e.message)); });
    } });
    app.appendChild(h("h2", { text: "Create a video" }));
    app.appendChild(h("label", { text: "Topic" })); app.appendChild(topic);
    app.appendChild(h("label", { text: "Length" })); app.appendChild(dur);
    app.appendChild(h("label", { text: "Style" })); app.appendChild(style);
    app.appendChild(h("div", { class: "actions" }, go));
    if (!cfg.token) app.appendChild(h("p", { class: "mut" }, "Add a token in ", h("a", { href: "#/settings", text: "Settings" }), " to start from here, or start it on GitHub: ", h("a", { href: AR.workflowPage(cfg), text: "Run workflow" }), " (choose action “generate”)."));
    app.appendChild(h("p", { class: "mut", text: "Free-tier limits apply (Gemini requests per day, GitHub Actions minutes). A failed run appears in the Library with its log." }));
    app.appendChild(out);
  }

  function viewSettings() {
    renderNav("settings"); clear(app);
    var cfg = loadCfg(), out = h("div", {});
    var owner = h("input", { type: "text" }), repo = h("input", { type: "text" }), branch = h("input", { type: "text" }), token = h("input", { type: "password", autocomplete: "off", placeholder: cfg.token ? "(saved on this device)" : "github_pat_…" });
    owner.value = cfg.owner; repo.value = cfg.repo; branch.value = cfg.branch;
    app.appendChild(h("h2", { text: "Settings" }));
    [["GitHub owner", owner], ["Repository", repo], ["Branch", branch], ["Fine-grained token (Actions: read and write, this repo only)", token]].forEach(function (p) { app.appendChild(h("label", { text: p[0] })); app.appendChild(p[1]); });
    app.appendChild(h("div", { class: "actions" },
      h("button", { class: "primary", text: "Save", onclick: function () {
        var next = { owner: owner.value.trim(), repo: repo.value.trim(), branch: branch.value.trim() || "main", token: token.value.trim() || cfg.token };
        saveCfg(next); out.replaceChildren(msg("ok", "Saved on this device only."));
      } }),
      h("button", { class: "danger", text: "Remove token", onclick: function () { var c = loadCfg(); c.token = ""; saveCfg(c); out.replaceChildren(msg("ok", "Token removed from this device.")); } })));
    app.appendChild(h("p", { class: "mut", text: "The token is stored only in this browser (localStorage) and sent only to api.github.com. Anyone with access to this browser profile could use it, so give it only the Actions permission on this one repository and set an expiry date. Without a token the dashboard is read-only and links you to GitHub to start runs." }));
    app.appendChild(out);
  }

  function route() {
    var hash = location.hash.replace(/^#\/?/, "");
    var m = hash.match(/^p\/(.+)$/);
    if (m) return viewProject(m[1]);
    switch (hash) {
      case "library": return viewList("library");
      case "ideas": return viewIdeas();
      case "create": return viewCreate();
      case "settings": return viewSettings();
      default: return viewList("review");
    }
  }
  window.addEventListener("hashchange", route);
  route();
})();
