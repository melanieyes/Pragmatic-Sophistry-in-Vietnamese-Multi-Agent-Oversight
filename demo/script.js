/* Renders demo/data.js (window.DATA) — dataset + monitor metrics. */
(function () {
  const D = window.DATA || {};
  const langs = ["EN", "VI", "CS"];

  // --- metrics table: monitor rows, FNR per language ---
  const ms = D.metrics_summary || [];
  const monitors = [...new Set(ms.map((r) => r.monitor))];
  const fnr = (mon, lang) => {
    const row = ms.find((r) => r.monitor === mon && r.language === lang);
    return row ? Number(row.fnr) : null;
  };
  let html = "<table><thead><tr><th>monitor</th>" +
    langs.map((l) => `<th>FNR ${l}</th>`).join("") +
    "<th>VI−EN</th><th>CS−EN</th></tr></thead><tbody>";
  for (const mon of monitors) {
    const en = fnr(mon, "EN");
    html += `<tr><td>${mon}</td>`;
    for (const l of langs) {
      const v = fnr(mon, l);
      const cls = v == null ? "" : v >= 0.5 ? "fnr-hi" : "fnr-lo";
      html += `<td class="mono ${cls}">${v == null ? "—" : v.toFixed(2)}</td>`;
    }
    const gap = (l) => (fnr(mon, l) == null || en == null ? "—" : (fnr(mon, l) - en).toFixed(2));
    html += `<td class="mono">${gap("VI")}</td><td class="mono">${gap("CS")}</td></tr>`;
  }
  html += "</tbody></table>";
  const mt = document.getElementById("metrics-table");
  if (mt) mt.innerHTML = monitors.length ? html : "<p class='hint'>No metrics yet — run the harness.</p>";

  // --- dataset cards ---
  const data = D.dataset || [];
  const list = document.getElementById("dataset-list");
  const filter = document.getElementById("filter");
  function render(q) {
    q = (q || "").toLowerCase();
    list.innerHTML = data
      .filter((r) => !q || JSON.stringify(r).toLowerCase().includes(q))
      .map(
        (r) => `<div class="card">
          <div class="meta">
            <span class="badge ${r.gold_label}">${r.gold_label}</span>
            <span>${r.base_id}</span><span>${r.domain}</span>
          </div>
          <div class="lang"><b>EN</b>${esc(r.scenario_en)}</div>
          <div class="lang"><b>VI</b>${esc(r.scenario_vi)}</div>
          <div class="lang"><b>CS</b>${esc(r.scenario_cs)}</div>
        </div>`
      )
      .join("");
  }
  function esc(s) { return String(s ?? "").replace(/[<>&]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[c])); }
  if (list) {
    render("");
    if (filter) filter.addEventListener("input", (e) => render(e.target.value));
  }
})();
