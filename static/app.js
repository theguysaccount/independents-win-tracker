// Progressive enhancement only: every page works without this file.
(function () {
  "use strict";

  // Count an event if the site owner turned on GoatCounter (cookieless); otherwise do nothing.
  function track(name) {
    try {
      if (window.goatcounter && window.goatcounter.count) {
        window.goatcounter.count({ path: name, title: name, event: true });
      }
    } catch (e) { /* analytics must never break the page */ }
  }

  // Sortable tables: <table data-sort> with <th data-type="num|text"><button>...</button></th>.
  document.querySelectorAll("table[data-sort]").forEach(function (table) {
    var heads = table.querySelectorAll("thead th");
    heads.forEach(function (th, col) {
      var btn = th.querySelector("button");
      if (!btn) return;
      btn.addEventListener("click", function () {
        var asc = th.getAttribute("aria-sort") !== "ascending";
        heads.forEach(function (h) { h.removeAttribute("aria-sort"); });
        th.setAttribute("aria-sort", asc ? "ascending" : "descending");
        var num = th.dataset.type === "num";
        var body = table.tBodies[0];
        var rows = Array.prototype.slice.call(body.rows);
        rows.sort(function (a, b) {
          var x = a.cells[col].dataset.v !== undefined ? a.cells[col].dataset.v : a.cells[col].textContent.trim();
          var y = b.cells[col].dataset.v !== undefined ? b.cells[col].dataset.v : b.cells[col].textContent.trim();
          if (num) {
            x = x === "" ? -Infinity : parseFloat(x);
            y = y === "" ? -Infinity : parseFloat(y);
            return asc ? x - y : y - x;
          }
          return asc ? x.localeCompare(y) : y.localeCompare(x);
        });
        rows.forEach(function (r) { body.appendChild(r); });
      });
    });
  });

  // Filters: <input data-filter="#tableId"> and <select data-filter-col="n" data-filter="#tableId">.
  function applyFilters(tableSel) {
    var table = document.querySelector(tableSel);
    if (!table) return;
    var q = "";
    var selects = [];
    document.querySelectorAll('[data-filter="' + tableSel + '"]').forEach(function (el) {
      if (el.tagName === "SELECT") selects.push(el);
      else q = el.value.trim().toLowerCase();
    });
    var shown = 0;
    Array.prototype.forEach.call(table.tBodies[0].rows, function (row) {
      var ok = !q || row.textContent.toLowerCase().indexOf(q) >= 0;
      selects.forEach(function (s) {
        if (s.value && row.dataset[s.dataset.key] !== s.value) ok = false;
      });
      row.hidden = !ok;
      if (ok) shown++;
    });
    var counter = document.querySelector('[data-count="' + tableSel + '"]');
    if (counter) counter.textContent = shown;
  }
  document.querySelectorAll("[data-filter]").forEach(function (el) {
    el.addEventListener("input", function () { applyFilters(el.dataset.filter); });
    el.addEventListener("change", function () { applyFilters(el.dataset.filter); });
  });

  // Share: the native sheet where there is one, otherwise copy the link.
  document.querySelectorAll("[data-share]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var data = { title: document.title, text: btn.dataset.text || "", url: btn.dataset.share };
      track("share");
      if (navigator.share) {
        navigator.share(data).catch(function () {});
      } else {
        copy(data.url, btn, "Link copied");
      }
    });
  });

  function copy(text, btn, done) {
    var old = btn.textContent;
    function ok() { btn.textContent = done; setTimeout(function () { btn.textContent = old; }, 1600); }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(ok, function () { fallback(); });
    } else { fallback(); }
    function fallback() {
      var ta = document.createElement("textarea");
      ta.value = text; document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); ok(); } catch (e) { /* ignore */ }
      document.body.removeChild(ta);
    }
  }
  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var src = document.querySelector(btn.dataset.copy);
      if (!src) return;
      track("embed-copy");
      copy(src.value || src.textContent, btn, "Copied");
    });
  });

  // Outbound source links count toward the activation metric.
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[data-out]");
    if (a) track("source-" + a.dataset.out);
  });

  // Times: keep the UTC text, add the reader's local time on hover.
  document.querySelectorAll("time[datetime]").forEach(function (t) {
    var d = new Date(t.getAttribute("datetime"));
    if (!isNaN(d) && t.getAttribute("datetime").length > 10) t.title = d.toLocaleString();
  });

  // Countdown to Election Day, in whole calendar days in the reader's time zone.
  var cd = document.querySelector("[data-countdown]");
  if (cd) {
    var p = cd.dataset.countdown.split("-");
    var target = new Date(+p[0], +p[1] - 1, +p[2]);
    var today = new Date(); today.setHours(0, 0, 0, 0);
    var days = Math.round((target - today) / 86400000);
    if (days > 1) cd.textContent = days + " days";
    else if (days === 1) cd.textContent = "tomorrow";
    else if (days === 0) cd.textContent = "today";
  }
})();
