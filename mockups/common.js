// Shared helpers for mockups m1-m3. Scenario comes from ?s=0|1|2.
const SC = window.SCENARIOS[+new URLSearchParams(location.search).get("s") || 0];
const STEPS = SC.steps;
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const GC = ["#8b9dff", "#f472b6", "#34d399", "#fbbf24", "#60a5fa", "#fb7185"];

const KW = new Set(("select from where group by having order limit offset join inner left right outer cross on using as and or not " +
  "in is null like between case when then else end distinct union all with insert into values update set delete create table if " +
  "exists drop alter truncate asc desc over partition int varchar char primary key").split(" "));
function highlight(src) {
  const re = /(--[^\n]*|#[^\n]*)|('(?:[^'\\]|\\.|'')*'?|`[^`]*`?)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_]\w*)(?=\s*\()|([A-Za-z_]\w*)/g;
  let out = "", last = 0, m;
  while ((m = re.exec(src))) {
    out += esc(src.slice(last, m.index));
    const t = esc(m[0]);
    out += m[1] ? `<span class="c">${t}</span>` : m[2] ? `<span class="s">${t}</span>` : m[3] ? `<span class="n">${t}</span>`
      : KW.has(m[0].toLowerCase()) ? `<span class="k">${t}</span>` : m[4] ? `<span class="f">${t}</span>` : t;
    last = re.lastIndex;
  }
  return out + esc(src.slice(last));
}

// Where in the statement text does this step's clause live? Returns [start, end] or null.
function locate(text, title, nested) {
  const toks = (title || "").match(/[A-Za-z0-9_$.]+|'[^']*'|`[^`]*`|[^\sA-Za-z0-9_]/g);
  if (!toks || toks.length > 40) return null;
  const pat = toks.map(t => /^as$/i.test(t) ? "(?:AS\\s+)?" : t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("\\s*");
  let re; try { re = new RegExp(pat, "gi"); } catch { return null; }
  const found = [...text.matchAll(re)].map(m => [m.index, m.index + m[0].length]);
  const depth = i => [...text.slice(0, i)].reduce((d, c) => d + (c === "(") - (c === ")"), 0);
  return found.find(([a]) => (depth(a) > 0) === nested) || found[0] || null;
}
function stepRange(s) {
  if (s.stmt === null) return null;
  const text = SC.statements[s.stmt].text;
  return locate(text, s.title, !!s.scope) || (s.sql ? locate(text, s.sql, false) : null);
}
function codeHtml(text, range) {
  if (!range) return highlight(text);
  return highlight(text.slice(0, range[0])) + `<mark class="hl">${highlight(text.slice(...range))}</mark>` + highlight(text.slice(range[1]));
}

const cellHtml = v => v === null ? `<span class="null">NULL</span>` : esc(v);
const mainTable = s => s.tables.find(t => t.badge) || s.tables[0];
const liveRows = t => t ? t.rows.filter(r => !["dropped", "removed"].includes(r.m)).length + t.more : 0;
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

// Render a table view. opts.rows overrides rows, opts.title/opts.note fill the header.
function tableHtml(t, opts = {}) {
  if (!t) return `<div class="tbl"><div class="empty-t">${opts.empty || "Nothing yet"}</div></div>`;
  const rows = opts.rows || t.rows;
  const body = rows.map((r, i) => {
    const cls = [r.m ? "m-" + r.m : ""];
    let style = "";
    if (r.g !== undefined) {
      cls.push("g", r.g % 2 ? "" : "alt");
      if (i && rows[i - 1].g !== r.g) cls.push("gstart");
      style = ` style="--gc:${GC[(r.g - 1) % GC.length]}"`;
    }
    const cells = r.v.map((v, c) => r.old && c in r.old
      ? `<td class="ch">${opts.oldOnly ? "" : `<s>${cellHtml(r.old[c])}</s>`}${cellHtml(v)}</td>` : `<td>${cellHtml(v)}</td>`).join("");
    return `<tr class="${cls.join(" ")}"${style}><td class="rn">${i + 1}</td>${cells}</tr>`;
  }).join("");
  const live = rows.filter(r => !["dropped", "removed", "out"].includes(r.m)).length;
  const groups = rows.some(r => r.g !== undefined) ? new Set(rows.map(r => r.g)).size : 0;
  return `<div class="tbl ${opts.cls || ""}">
    <div class="tbl-head"><b>${esc(opts.title || t.name)}</b>${opts.note ? `<span>${opts.note}</span>` : ""}
      <span class="right">${groups ? plural(groups, "group") + " · " : ""}${plural(live, "row")}</span></div>
    <div class="tbl-scroll"><table><thead><tr><th class="rn">#</th>${t.cols.map(c => `<th>${esc(c)}</th>`).join("")}</tr></thead>
    <tbody>${body}</tbody></table>${rows.length ? "" : `<div class="empty-t">No rows</div>`}</div></div>`;
}

// Arrow keys + Home/End drive go(i).
function keys(go, get) {
  document.addEventListener("keydown", e => {
    const d = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    if (d) { e.preventDefault(); go(get() + d); }
    if (e.key === "Home") go(0);
    if (e.key === "End") go(STEPS.length - 1);
  });
}
const clamp = i => Math.max(0, Math.min(i, STEPS.length - 1));
