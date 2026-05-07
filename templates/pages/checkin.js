/* ─── H5 Check-in Page — Interactive Logic (2-step flow) ─── */
/* Injected by Jinja2 into checkin.html via {{ js }} */
/* EVENT_ID is set in a separate <script> tag before this runs.

   Flow:
     1. User types name, clicks the search button (#search-btn → doSearch)
     2. /checkin/lookup runs (no side effects). UI:
        - found  → fill #name-display / #seat-display / #zone-display,
                   stash attendee_id on #confirm-btn, show #confirm-btn
        - already → fill the same display fields and show #confirm-btn
                   disabled with "已签到" text (still informative)
        - ambiguous → render #candidates-list, user picks one
        - not_found → toast
     3. User clicks #confirm-btn → /checkin/confirm/{attendee_id} actually
        checks in. UI flips to success state.

   The internal check-in business logic (CheckinService.checkin, DB state
   machine) is unchanged — /confirm/{aid} still performs it. We only added
   the read-only /lookup step in front. Old /search endpoint remains for
   any callers; the page no longer hits it.

   Element contract — gen prompt enforces these IDs but custom layouts
   may freely add wrappers, decoration, classes:
     #name-input        text input
     #search-btn        triggers doSearch()
     #confirm-btn       triggers doConfirm() (initially hidden)
     #result-section    wrapper for the populated info card (initially hidden)
     #name-display      filled with attendee name
     #seat-display      filled with seat label (or "未分配")
     #zone-display      (optional) filled with zone name
     #candidates-section + #candidates-list   for ambiguous matches
     #success-section + #success-name + #success-msg + #seat-info + #seat-label
                         final post-confirm state
     #stat-total / #stat-checked / #stat-rate  (optional) live stats
*/

var API_BASE = window.location.origin + "/p/" + EVENT_ID + "/checkin";

/* ── Resolve elements (defensive — model may omit optional ones) ── */
var nameInput        = document.getElementById("name-input");
var searchBtn        = document.getElementById("search-btn");
var confirmBtn       = document.getElementById("confirm-btn");
var resultSection    = document.getElementById("result-section");
var candidatesSection = document.getElementById("candidates-section");
var successSection   = document.getElementById("success-section");

/* ── Force initial state (defensive against gen LLM mistakes) ──────
   The gen LLM was caught rendering ALL states simultaneously — info
   card visible with placeholder text "尊敬的XXX先生/女士 / 胸牌編號:001",
   confirm button visible, success block visible — instead of starting
   in the search-only state. JS owns state transitions, so JS owns the
   initial state too. Any inline style="display:..." or placeholder
   text the model put on these elements gets wiped here. */
[resultSection, candidatesSection, successSection, confirmBtn].forEach(function (el) {
  if (el) el.style.display = "none";
});
[
  "name-display", "seat-display", "zone-display",
  "title-display", "organization-display",
  "success-name", "success-msg", "seat-label",
].forEach(function (id) {
  var el = document.getElementById(id);
  if (el) el.textContent = "";
});

/* ── Tiny helpers ──────────────────────────────────────────────── */
function $(id) { return document.getElementById(id); }
function show(el) { if (el) el.style.display = ""; }
function hide(el) { if (el) el.style.display = "none"; }
function setText(id, text) {
  var el = $(id);
  if (el) el.textContent = text == null ? "" : String(text);
}

function showToast(msg) {
  var t = document.createElement("div");
  t.className = "toast";
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(function () { t.remove(); }, 2600);
}

function setLoading(btn, loading) {
  if (!btn) return;
  if (loading) {
    btn.disabled = true;
    btn.classList.add("loading");
    if (!btn.dataset.origText) btn.dataset.origText = btn.textContent;
    btn.textContent = "请稍候...";
  } else {
    btn.disabled = false;
    btn.classList.remove("loading");
    if (btn.dataset.origText) {
      btn.textContent = btn.dataset.origText;
      delete btn.dataset.origText;
    }
  }
}

function escHtml(s) {
  var d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

/* ── Step 1: lookup (no check-in side effect) ─────────────────── */
function doSearch() {
  if (!nameInput) return;
  var name = nameInput.value.trim();
  if (!name) {
    showToast("请输入姓名");
    nameInput.focus();
    return;
  }

  hideSuggestions();
  setLoading(searchBtn, true);
  hide(resultSection);
  hide(candidatesSection);
  hide(successSection);
  hide(confirmBtn);

  fetch(API_BASE + "/lookup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: name }),
  })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      setLoading(searchBtn, false);
      handleLookupResult(data);
    })
    .catch(function () {
      setLoading(searchBtn, false);
      showToast("网络错误，请重试");
    });
}

function handleLookupResult(data) {
  if (data.status === "found" || data.status === "already") {
    populateMatch(data);
    return;
  }

  if (data.status === "ambiguous" && data.candidates) {
    showCandidates(data.candidates);
    return;
  }

  if (data.status === "not_found") {
    showToast(data.message || "未找到该人员");
    if (nameInput) nameInput.select();
    return;
  }

  if (data.status === "cancelled") {
    showToast(data.message || "该人员已取消报名");
    return;
  }

  showToast(data.message || "查询失败");
}

/* Fill the info card with the matched attendee + reveal it.
   Keeps confirm-btn hidden (and disabled with "已签到" label) when the
   attendee is already checked in, so the UI is informative without
   tempting a redundant tap. */
function populateMatch(data) {
  setText("name-display", data.attendee_name || "");
  setText("seat-display", data.seat_label || "未分配");
  setText("zone-display", data.seat_zone || "");
  setText("title-display", data.title || "");
  setText("organization-display", data.organization || "");

  // attrs.* — let templates display arbitrary fields (e.g. badge_number)
  if (data.attrs && typeof data.attrs === "object") {
    Object.keys(data.attrs).forEach(function (k) {
      setText("attr-" + k, data.attrs[k]);
    });
  }

  show(resultSection);
  hide(candidatesSection);
  hide(successSection);

  if (confirmBtn) {
    if (data.status === "already") {
      confirmBtn.disabled = true;
      confirmBtn.dataset.attendeeId = "";
      if (!confirmBtn.dataset.origText) {
        confirmBtn.dataset.origText = confirmBtn.textContent;
      }
      confirmBtn.textContent = "已签到";
      show(confirmBtn);
    } else {
      confirmBtn.disabled = false;
      confirmBtn.dataset.attendeeId = data.attendee_id || "";
      if (confirmBtn.dataset.origText) {
        confirmBtn.textContent = confirmBtn.dataset.origText;
      }
      show(confirmBtn);
    }
  }
}

/* ── Disambiguation: pick a candidate ─────────────────────────── */
function showCandidates(candidates) {
  var list = $("candidates-list");
  if (!list) {
    showToast("找到多位同名人员，请输入更完整的姓名");
    return;
  }
  list.innerHTML = "";

  candidates.forEach(function (c) {
    var div = document.createElement("div");
    div.className = "cand-item";
    div.onclick = function () { selectCandidate(c); };

    var initial = (c.name || "?").charAt(0);
    var detail = [];
    if (c.title) detail.push(c.title);
    if (c.organization) detail.push(c.organization);

    div.innerHTML =
      '<div class="cand-avatar">' + escHtml(initial) + "</div>" +
      '<div class="cand-info">' +
      '<div class="cand-name">' + escHtml(c.name) + "</div>" +
      (detail.length
        ? '<div class="cand-detail">' + escHtml(detail.join(" · ")) + "</div>"
        : "") +
      "</div>" +
      '<div class="cand-arrow">›</div>';

    list.appendChild(div);
  });

  hide(resultSection);
  hide(successSection);
  hide(confirmBtn);
  show(candidatesSection);
}

/* When user picks a candidate, do a follow-up lookup with their full
   name so the same review-then-confirm flow runs (instead of jumping
   straight to check-in). */
function selectCandidate(c) {
  if (nameInput) nameInput.value = c.name;
  hide(candidatesSection);
  // Reuse lookup directly with the attendee_id to skip another fuzzy match
  fetch(API_BASE + "/lookup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: c.name }),
  })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      // If still ambiguous (rare — same name twice in the list), fall back
      // to confirming the picked attendee_id directly.
      if (data.status === "ambiguous") {
        directLookupById(c);
      } else {
        handleLookupResult(data);
      }
    })
    .catch(function () { directLookupById(c); });
}

function directLookupById(c) {
  // No /lookup-by-id endpoint — synthesise a "found" payload with whatever
  // we know, then let confirm hit /confirm/{aid}. Seat info will be empty
  // until the page polls again, but the confirm flow still works.
  populateMatch({
    status: "found",
    attendee_id: c.attendee_id,
    attendee_name: c.name,
    title: c.title,
    organization: c.organization,
  });
}

/* ── Step 2: confirm (actually check in) ──────────────────────── */
function doConfirm() {
  if (!confirmBtn) return;
  var aid = confirmBtn.dataset.attendeeId;
  if (!aid) {
    showToast("请先搜索姓名");
    return;
  }

  setLoading(confirmBtn, true);

  fetch(API_BASE + "/confirm/" + aid, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      setLoading(confirmBtn, false);
      if (data.status === "success" || data.status === "already") {
        showSuccess(data);
        refreshStats();
      } else {
        showToast(data.message || "签到失败");
      }
    })
    .catch(function () {
      setLoading(confirmBtn, false);
      showToast("网络错误，请重试");
    });
}

/* ── Final success state ──────────────────────────────────────── */
function showSuccess(data) {
  setText("success-name", data.attendee_name || "");
  setText(
    "success-msg",
    data.status === "already" ? "您已签到过" : "签到成功！",
  );

  var seatInfo = $("seat-info");
  if (seatInfo) {
    if (data.seat_label) {
      setText("seat-label", "您的座位：" + data.seat_label);
      show(seatInfo);
    } else {
      hide(seatInfo);
    }
  }

  hide(resultSection);
  hide(candidatesSection);
  hide(confirmBtn);
  show(successSection);
}

function resetPage() {
  if (nameInput) nameInput.value = "";
  hide(resultSection);
  hide(candidatesSection);
  hide(successSection);
  hide(confirmBtn);
  if (nameInput) nameInput.focus();
}

/* ── Stats polling (optional UI) ──────────────────────────────── */
function refreshStats() {
  fetch(API_BASE + "/stats")
    .then(function (r) { return r.json(); })
    .then(function (s) {
      setText("stat-total", s.total);
      setText("stat-checked", s.checked_in);
      setText("stat-rate", s.rate + "%");
    })
    .catch(function () {});
}
setInterval(refreshStats, 15000);

/* ── Keyboard: Enter triggers search ──────────────────────────── */
if (nameInput) {
  nameInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
      hideSuggestions();
      doSearch();
    } else if (e.key === "Escape") {
      hideSuggestions();
    }
  });
}

/* ── Live autocomplete suggestions ────────────────────────────── */
var suggestBox = document.createElement("div");
suggestBox.id = "suggest-box";
suggestBox.style.cssText =
  "display:none;position:absolute;left:0;right:0;top:100%;" +
  "background:#fff;border:1px solid #d1d5db;border-top:none;" +
  "border-radius:0 0 12px 12px;max-height:200px;overflow-y:auto;" +
  "box-shadow:0 4px 12px rgba(0,0,0,0.1);z-index:50;";
if (nameInput && nameInput.parentElement) {
  nameInput.parentElement.style.position = "relative";
  nameInput.parentElement.appendChild(suggestBox);
}

var suggestTimer = null;
if (nameInput) {
  nameInput.addEventListener("input", function () {
    clearTimeout(suggestTimer);
    var q = nameInput.value.trim();
    if (q.length < 1) { hideSuggestions(); return; }
    suggestTimer = setTimeout(function () { fetchSuggestions(q); }, 250);
  });
}

function fetchSuggestions(q) {
  fetch(API_BASE + "/suggest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: q }),
  })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.candidates && data.candidates.length > 0) {
        showSuggestions(data.candidates);
      } else {
        hideSuggestions();
      }
    })
    .catch(function () { hideSuggestions(); });
}

function showSuggestions(items) {
  suggestBox.innerHTML = "";
  items.forEach(function (c) {
    var div = document.createElement("div");
    div.style.cssText =
      "padding:10px 16px;cursor:pointer;font-size:15px;" +
      "border-bottom:1px solid #f3f4f6;display:flex;align-items:center;gap:10px;";
    div.onmouseenter = function () { div.style.background = "#f0f4ff"; };
    div.onmouseleave = function () { div.style.background = ""; };

    var detail = [];
    if (c.title) detail.push(c.title);
    if (c.organization) detail.push(c.organization);

    div.innerHTML =
      '<span style="font-weight:600;color:#1e293b;">' + escHtml(c.name) + "</span>" +
      (detail.length
        ? '<span style="font-size:12px;color:#94a3b8;">' + escHtml(detail.join(" · ")) + "</span>"
        : "");

    div.onclick = function () {
      if (nameInput) nameInput.value = c.name;
      hideSuggestions();
      doSearch();
    };
    suggestBox.appendChild(div);
  });
  suggestBox.style.display = "";
}

function hideSuggestions() { suggestBox.style.display = "none"; }

document.addEventListener("click", function (e) {
  if (e.target !== nameInput && !suggestBox.contains(e.target)) {
    hideSuggestions();
  }
});
