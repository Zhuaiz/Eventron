/* ─── H5 Check-in Page — Interactive Logic ─── */
/* Injected by Jinja2 into checkin.html via {{ js }} */
/* EVENT_ID is set in a separate <script> tag before this runs. */

var API_BASE = window.location.origin + "/p/" + EVENT_ID + "/checkin";

/* ── Sections ── */
var searchSection = document.getElementById("search-section");
var resultSection = document.getElementById("result-section");
var candidatesSection = document.getElementById("candidates-section");
var successSection = document.getElementById("success-section");
var nameInput = document.getElementById("name-input");
var searchBtn = document.getElementById("search-btn");

/* ── Helpers ── */
function show(el) { el.style.display = ""; }
function hide(el) { el.style.display = "none"; }

function showToast(msg) {
  var t = document.createElement("div");
  t.className = "toast";
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(function () { t.remove(); }, 2600);
}

function setLoading(btn, loading) {
  if (loading) {
    btn.classList.add("loading");
    btn.dataset.origText = btn.textContent;
    btn.textContent = "请稍候...";
  } else {
    btn.classList.remove("loading");
    btn.textContent = btn.dataset.origText || btn.textContent;
  }
}

/* ── Search ── */
function doSearch() {
  var name = nameInput.value.trim();
  if (!name) {
    showToast("请输入姓名");
    nameInput.focus();
    return;
  }

  setLoading(searchBtn, true);
  hide(resultSection);
  hide(candidatesSection);
  hide(successSection);

  fetch(API_BASE + "/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: name }),
  })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      setLoading(searchBtn, false);
      handleSearchResult(data);
    })
    .catch(function (err) {
      setLoading(searchBtn, false);
      showToast("网络错误，请重试");
    });
}

function handleSearchResult(data) {
  if (data.status === "success" || data.status === "already") {
    showSuccess(data);
    refreshStats();
    return;
  }

  if (data.status === "ambiguous" && data.candidates) {
    showCandidates(data.candidates);
    return;
  }

  if (data.status === "not_found") {
    showToast(data.message || "未找到该人员");
    nameInput.select();
    return;
  }

  showToast(data.message || "操作失败");
}

/* ── Disambiguation: show candidate list ── */
function showCandidates(candidates) {
  var list = document.getElementById("candidates-list");
  list.innerHTML = "";

  candidates.forEach(function (c) {
    var div = document.createElement("div");
    div.className = "cand-item";
    div.onclick = function () { confirmCheckin(c.attendee_id); };

    var initial = (c.name || "?").charAt(0);
    var detail = [];
    if (c.title) detail.push(c.title);
    if (c.organization) detail.push(c.organization);

    div.innerHTML =
      '<div class="cand-avatar">' + initial + "</div>" +
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
  show(candidatesSection);
}

/* ── Confirm check-in (by attendee_id) ── */
function confirmCheckin(attendeeId) {
  // Disable candidate list while loading
  var items = document.querySelectorAll(".cand-item");
  items.forEach(function (el) { el.style.pointerEvents = "none"; el.style.opacity = "0.6"; });

  fetch(API_BASE + "/confirm/" + attendeeId, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.status === "success" || data.status === "already") {
        showSuccess(data);
        refreshStats();
      } else {
        showToast(data.message || "签到失败");
        items.forEach(function (el) { el.style.pointerEvents = ""; el.style.opacity = ""; });
      }
    })
    .catch(function () {
      showToast("网络错误，请重试");
      items.forEach(function (el) { el.style.pointerEvents = ""; el.style.opacity = ""; });
    });
}

/* ── Show success ── */
function showSuccess(data) {
  document.getElementById("success-name").textContent = data.attendee_name || "";
  document.getElementById("success-msg").textContent =
    data.status === "already" ? "您已签到过" : "签到成功！";

  var seatInfo = document.getElementById("seat-info");
  if (data.seat_label) {
    document.getElementById("seat-label").textContent =
      "您的座位：" + data.seat_label;
    show(seatInfo);
  } else {
    hide(seatInfo);
  }

  hide(searchSection);
  hide(resultSection);
  hide(candidatesSection);
  show(successSection);
}

/* ── Reset ── */
function resetPage() {
  nameInput.value = "";
  hide(resultSection);
  hide(candidatesSection);
  hide(successSection);
  show(searchSection);
  nameInput.focus();
}

/* ── Refresh stats ── */
function refreshStats() {
  fetch(API_BASE + "/stats")
    .then(function (r) { return r.json(); })
    .then(function (s) {
      document.getElementById("stat-total").textContent = s.total;
      document.getElementById("stat-checked").textContent = s.checked_in;
      document.getElementById("stat-rate").textContent = s.rate + "%";
    })
    .catch(function () {});
}

/* ── Poll stats every 15s ── */
setInterval(refreshStats, 15000);

/* ── Enter key to search ── */
nameInput.addEventListener("keydown", function (e) {
  if (e.key === "Enter") {
    e.preventDefault();
    doSearch();
  }
});

/* ── Escape HTML ── */
function escHtml(s) {
  var d = document.createElement("div");
  d.textContent = s || "";
  return d.innerHTML;
}
