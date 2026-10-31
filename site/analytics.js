/*
 * Who's Who analytics — OFF in this build.
 *
 * Nothing is sent anywhere unless BOTH are true:
 *   1. the page defines window.WW_ANALYTICS = { endpoint: "https://…", key: "…" } before this script, and
 *   2. the visitor has not opted out (Do Not Track or Global Privacy Control).
 * No build sets WW_ANALYTICS today, so every track() call is a no-op that only records the event
 * in memory (window.WW.events) for local debugging.
 *
 * Privacy rules enforced here, whatever the provider:
 *   - no cookies, no localStorage, no fingerprinting; the session id lives in memory for one page load
 *   - only allow-listed event names and properties are kept; anything else is dropped
 *   - never send free text typed by a visitor (search text, pasted links): only whether it matched
 * Event design: docs/analytics.md.
 */
(function () {
  "use strict";
  var EVENTS = {
    page_viewed: ["page"],
    ownership_lookup: ["input_kind", "result"],            // input_kind: url | name ; result: found | not_found | other_repo
    ownership_report_viewed: ["component", "attention", "unknown"],
    ownership_filter_changed: ["filter"],
    ownership_sources_opened: ["component", "question"],
    ownership_draft_copied: ["component", "question"],
    ownership_feedback: ["component", "question", "verdict"],  // verdict: right | wrong
    ownership_report_link_clicked: ["component", "question"]
  };
  var MAX_LEN = 120;

  function optedOut() {
    var n = window.navigator || {};
    return n.doNotTrack === "1" || window.doNotTrack === "1" || n.globalPrivacyControl === true;
  }

  function clean(name, props) {
    var keys = EVENTS[name];
    if (!keys) return null;
    var out = {};
    keys.forEach(function (k) {
      var v = props && props[k];
      if (typeof v === "number" || typeof v === "boolean") out[k] = v;
      else if (typeof v === "string") out[k] = v.slice(0, MAX_LEN);
    });
    return out;
  }

  var cfg = window.WW_ANALYTICS || null;
  var enabled = !!(cfg && cfg.endpoint && cfg.key) && !optedOut();
  var session = Math.random().toString(36).slice(2) + Date.now().toString(36);  // memory only

  var WW = (window.WW = window.WW || {});
  WW.events = WW.events || [];
  WW.analyticsEnabled = enabled;

  WW.track = function (name, props) {
    var p = clean(name, props);
    if (!p) return;
    var event = { event: name, properties: p, ts: new Date().toISOString() };
    WW.events.push(event);
    if (!enabled) return;
    var body = JSON.stringify({ key: cfg.key, session: session, event: name, properties: p, timestamp: event.ts });
    try {
      if (navigator.sendBeacon) navigator.sendBeacon(cfg.endpoint, new Blob([body], { type: "application/json" }));
      else fetch(cfg.endpoint, { method: "POST", body: body, keepalive: true, credentials: "omit",
                                 headers: { "Content-Type": "application/json" } });
    } catch (e) { /* analytics must never break the page */ }
  };
})();
