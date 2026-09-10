/* AI 커머스광고 키워드 Agent — 1단계: tvN 편성표 캘린더 */

const PX_PER_MIN = 1.25;   // style.css 의 --px-per-min 과 같아야 합니다.
const DAY_START_MIN = 5 * 60;  // 방송일은 05:00 에 시작하는 것으로 봅니다.
const WKDAY = ["일", "월", "화", "수", "목", "금", "토"];

const state = {
  weekStart: mondayOf(new Date()),
  programsByDate: new Map(),
  days: {},
  fetchedAt: 0,
  registrationsByProgram: new Map(),
  totalMin: 1500,
  config: null,
  currentProgram: null,
  analysis: null,
  selectedKeyword: null,
};

/* ------------------------------------------------------------- 날짜 유틸 */

function mondayOf(d) {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diff = (x.getDay() + 6) % 7; // 월요일 = 0
  x.setDate(x.getDate() - diff);
  return x;
}

function addDays(d, n) {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  x.setDate(x.getDate() + n);
  return x;
}

function ymd(d) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}`;
}

function prettyDate(s) {
  return `${s.slice(0, 4)}.${s.slice(4, 6)}.${s.slice(6, 8)}`;
}

function hhmmLabel(min) {
  const h = Math.floor(min / 60) % 24;
  return String(h).padStart(2, "0") + ":00";
}

/* --------------------------------------------------------------- 데이터 */

async function loadSchedule({ refresh = false } = {}) {
  const info = document.getElementById("fetchInfo");
  info.textContent = refresh ? "tvN 편성표 새로 읽는 중…" : "편성표 불러오는 중…";
  try {
    const res = await fetch("/api/schedule" + (refresh ? "?refresh=1" : ""));
    const json = await res.json();
    if (!json.ok) throw new Error(json.error || "편성표를 불러오지 못했습니다.");

    state.days = json.days || {};
    state.fetchedAt = json.fetchedAt || 0;
    state.programsByDate = new Map();
    let maxEnd = 1440;
    for (const p of json.programs || []) {
      if (!state.programsByDate.has(p.date)) state.programsByDate.set(p.date, []);
      state.programsByDate.get(p.date).push(p);
      maxEnd = Math.max(maxEnd, p.offsetMin + p.durationMin);
    }
    state.totalMin = Math.ceil((maxEnd + 15) / 60) * 60;
    for (const list of state.programsByDate.values()) {
      list.sort((a, b) => a.offsetMin - b.offsetMin);
    }

    const when = state.fetchedAt ? new Date(state.fetchedAt * 1000) : null;
    info.textContent = when
      ? `편성표 기준 ${when.getMonth() + 1}/${when.getDate()} ${String(when.getHours()).padStart(2, "0")}:${String(when.getMinutes()).padStart(2, "0")}`
      : "편성표 불러옴";
    showNotice(json.warning || "");
  } catch (err) {
    info.textContent = "편성표 오류";
    showNotice("편성표를 불러오지 못했습니다: " + err.message);
  }
}

async function loadRegistrations() {
  try {
    const res = await fetch("/api/registrations");
    const json = await res.json();
    state.registrationsByProgram = new Map();
    for (const item of json.items || []) {
      const key = item.programId;
      if (!state.registrationsByProgram.has(key)) state.registrationsByProgram.set(key, []);
      state.registrationsByProgram.get(key).push(item);
    }
  } catch (err) {
    /* 등록 이력이 없어도 캘린더는 그립니다. */
  }
}

function showNotice(message) {
  const el = document.getElementById("notice");
  el.textContent = message;
  el.hidden = !message;
}

/* --------------------------------------------------------------- 렌더링 */

function renderWeekLabel() {
  const start = state.weekStart;
  const end = addDays(start, 6);
  document.getElementById("weekRange").textContent =
    `${prettyDate(ymd(start))} (월) ~ ${prettyDate(ymd(end)).slice(5)} (일)`;

  const thisWeek = ymd(mondayOf(new Date()));
  const sub = document.getElementById("weekSub");
  sub.textContent = ymd(start) === thisWeek ? "tvN 편성표 · 이번 주" : "tvN 편성표";
}

function renderDayHead() {
  const wrap = document.getElementById("dayHead");
  wrap.innerHTML = "";
  const todayKey = ymd(new Date());

  for (let i = 0; i < 7; i++) {
    const date = addDays(state.weekStart, i);
    const key = ymd(date);
    const list = state.programsByDate.get(key) || [];

    const cell = document.createElement("div");
    cell.className = "day-head";
    if (i === 5) cell.classList.add("is-sat");
    if (i === 6) cell.classList.add("is-sun");
    if (key === todayKey) cell.classList.add("is-today");

    cell.innerHTML =
      `<div class="wk">${WKDAY[date.getDay()]}</div>` +
      `<div class="dd">${date.getDate()}</div>` +
      `<div class="cnt">${list.length ? list.length + "편" : "-"}</div>`;
    wrap.appendChild(cell);
  }
}

function renderTimeGutter() {
  const gutter = document.getElementById("timeGutter");
  gutter.innerHTML = "";
  gutter.style.height = state.totalMin * PX_PER_MIN + "px";
  for (let m = 0; m <= state.totalMin; m += 60) {
    const label = document.createElement("div");
    label.className = "hour";
    label.style.top = m * PX_PER_MIN + "px";
    label.textContent = hhmmLabel(DAY_START_MIN + m);
    gutter.appendChild(label);
  }
}

function renderGrid() {
  const grid = document.getElementById("dayGrid");
  grid.innerHTML = "";
  const todayKey = ymd(new Date());

  for (let i = 0; i < 7; i++) {
    const date = addDays(state.weekStart, i);
    const key = ymd(date);
    const list = state.programsByDate.get(key) || [];

    const col = document.createElement("div");
    col.className = "day-col";
    col.style.height = state.totalMin * PX_PER_MIN + "px";
    if (key === todayKey) col.classList.add("is-today");
    if (!list.length) col.classList.add("is-empty");

    for (const p of list) col.appendChild(programBlock(p));
    if (key === todayKey) {
      const line = nowLine();
      if (line) col.appendChild(line);
    }
    grid.appendChild(col);
  }
}

function programBlock(p) {
  const height = Math.max(16, p.durationMin * PX_PER_MIN - 3);
  const regs = state.registrationsByProgram.get(p.id) || [];

  const el = document.createElement("button");
  el.type = "button";
  el.className = "pgm";
  if (p.liveFlag === "본") el.classList.add("is-live");
  if (regs.length) el.classList.add("is-registered");
  if (height < 46) el.classList.add("is-short");
  el.style.top = p.offsetMin * PX_PER_MIN + "px";
  el.style.height = height + "px";
  el.title = `${p.start}~${p.end} ${p.title}` + (p.episode ? ` ${p.episode}` : "");

  const flag = p.liveFlag === "본" ? '<span class="pgm-flag">본</span>' : "";
  el.innerHTML =
    `<div class="t">${p.start}</div>` +
    `<div class="n">${flag}${escapeHtml(p.title)}</div>` +
    (p.episode ? `<div class="e">${escapeHtml(p.episode)}</div>` : "") +
    (regs.length ? `<div class="pgm-keys">키워드 ${regs.length}건 등록</div>` : "");

  el.addEventListener("click", () => openProgram(p));
  return el;
}

function nowLine() {
  const now = new Date();
  const min = now.getHours() * 60 + now.getMinutes() - DAY_START_MIN;
  if (min < 0 || min > state.totalMin) return null;
  const el = document.createElement("div");
  el.className = "now-line";
  el.style.top = min * PX_PER_MIN + "px";
  return el;
}

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function render() {
  renderWeekLabel();
  renderDayHead();
  renderTimeGutter();
  renderGrid();
}

/* ----------------------------------------------------------------- 팝업 */

const SOURCE_LABEL = {
  "duckduckgo": "웹검색",
  "daum": "웹문서",
  "daum-ad": "검색광고",
  "naver-ac": "자동완성",
  "광고키워드": "검색광고 조합",
  "조합": "프로그램 조합",
};

function openProgram(p) {
  state.currentProgram = p;
  state.selectedKeyword = null;

  document.getElementById("modalTitle").textContent = p.title;
  const badge = document.getElementById("modalBadge");
  badge.textContent = p.liveFlag === "본" ? "본방송" : "재방송";
  badge.classList.toggle("is-rerun", p.liveFlag !== "본");

  const dow = WKDAY[new Date(+p.date.slice(0, 4), +p.date.slice(4, 6) - 1, +p.date.slice(6, 8)).getDay()];
  document.getElementById("modalMeta").textContent =
    `${prettyDate(p.date)} (${dow}) ${p.start}~${p.end} · ${p.channel}` +
    (p.episode ? ` · ${p.episode}` : "") + (p.genre && p.genre !== "기타" ? ` · ${p.genre}` : "") +
    (p.subtitle ? ` · ${p.subtitle}` : "");

  document.getElementById("previewPanel").innerHTML =
    '<div class="placeholder">왼쪽에서 키워드를 클릭하면 검색 결과를 미리 봅니다.</div>';
  document.getElementById("modalBackdrop").hidden = false;
  loadKeywords(p, false);
}

async function loadKeywords(program, refresh) {
  const list = document.getElementById("keywordList");
  const meta = document.getElementById("analysisMeta");
  list.innerHTML = '<div class="loading"><span class="spinner"></span>검색해서 키워드를 뽑는 중이에요… (10초쯤 걸려요)</div>';
  meta.textContent = "";

  try {
    const url = `/api/keywords?programId=${encodeURIComponent(program.id)}` + (refresh ? "&refresh=1" : "");
    const res = await fetch(url);
    const json = await res.json();
    if (!json.ok) throw new Error(json.error || "분석에 실패했습니다.");
    state.analysis = json;
    renderKeywords(json);
  } catch (err) {
    list.innerHTML = `<div class="notice">키워드를 뽑지 못했습니다: ${escapeHtml(err.message)}</div>`;
  }
}

function renderKeywords(analysis) {
  const meta = document.getElementById("analysisMeta");
  const when = analysis.analyzedAt ? new Date(analysis.analyzedAt * 1000) : null;
  meta.innerHTML =
    `검색어: ${analysis.queries.map((q) => `<code>${escapeHtml(q)}</code>`).join(" · ")}<br>` +
    `문서 ${analysis.docCount}건 분석` +
    (when ? ` · ${when.getMonth() + 1}/${when.getDate()} ${String(when.getHours()).padStart(2, "0")}:${String(when.getMinutes()).padStart(2, "0")} 기준` : "") +
    (analysis.cached ? " (저장된 결과)" : "") +
    (analysis.errors && analysis.errors.length ? ` · 일부 검색처 실패 ${analysis.errors.length}건` : "");

  const list = document.getElementById("keywordList");
  list.innerHTML = "";
  if (!analysis.keywords.length) {
    list.innerHTML = '<div class="placeholder">이 회차에서는 상품 키워드를 찾지 못했어요. 다시 분석을 눌러보거나 다른 회차를 확인해 주세요.</div>';
    return;
  }

  for (const k of analysis.keywords) {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "kw" + (k.shoppable ? "" : " is-generic");
    el.dataset.keyword = k.keyword;

    const srcText = (k.sources || []).map((s) => SOURCE_LABEL[s] || s).join(" · ");
    el.innerHTML =
      `<div class="kw-main">` +
      `<div class="kw-name">${escapeHtml(k.keyword)}</div>` +
      `<div class="kw-sub">${escapeHtml(srcText)}${k.demand && k.demand.length ? " · 검색수요 확인" : ""}</div>` +
      `</div>` +
      `<div class="kw-side">` +
      (k.demand && k.demand.length ? '<span class="demand-tag">수요✓</span>' : "") +
      `<span class="cat cat-${k.category}">${k.category}</span>` +
      `<span class="score-bar" title="추천도 ${k.confidence}%"><i style="width:${k.confidence}%"></i></span>` +
      `</div>`;

    el.addEventListener("click", () => selectKeyword(k, el));
    list.appendChild(el);
  }
}

function selectKeyword(k, el) {
  state.selectedKeyword = k;
  document.querySelectorAll(".kw").forEach((n) => n.classList.remove("is-active"));
  el.classList.add("is-active");
  renderPreview(k);
}

async function renderPreview(k) {
  const panel = document.getElementById("previewPanel");
  panel.innerHTML = '<div class="loading"><span class="spinner"></span>키워드를 확인하는 중…</div>';

  let data;
  try {
    const res = await fetch("/api/store-preview?keyword=" + encodeURIComponent(k.keyword));
    data = await res.json();
    if (!data.ok) throw new Error(data.error || "확인에 실패했습니다.");
  } catch (err) {
    panel.innerHTML = `<div class="notice">${escapeHtml(err.message)}</div>`;
    return;
  }
  if (state.selectedKeyword !== k) return;   // 그 사이 다른 키워드를 눌렀으면 무시합니다.

  const relatedHtml = data.related.length
    ? data.related.map((r) => `<span class="chip">${escapeHtml(r)}</span>`).join("")
    : '<span class="muted" style="font-size:12px">네이버 자동완성에 걸리는 문구가 없어요. 검색량이 적은 키워드일 수 있습니다.</span>';

  const evidence = k.evidence || [];
  const evidenceHtml = evidence.length
    ? evidence
        .map((e) =>
          e.url
            ? `<li><a href="${escapeHtml(e.url)}" target="_blank" rel="noopener">${escapeHtml(e.text)}</a></li>`
            : `<li>${escapeHtml(e.text)}</li>`
        )
        .join("")
    : "<li class='muted'>근거 문서가 없습니다(조합으로 만든 키워드).</li>";

  panel.innerHTML =
    `<div class="preview-head">` +
    `<span class="preview-kw">${escapeHtml(k.keyword)}</span>` +
    `<span class="cat cat-${k.category}">${k.category}</span>` +
    `</div>` +
    `<section class="check-block">` +
    `<h4>네이버 연관 검색어 <small>실제로 검색되는 문구인지</small></h4>` +
    `<div class="chips">${relatedHtml}</div>` +
    `</section>` +
    `<section class="check-block">` +
    `<h4>이 키워드가 나온 근거</h4>` +
    `<ul class="evidence">${evidenceHtml}</ul>` +
    `</section>` +
    (data.warning ? `<p class="muted" style="font-size:11.5px">${escapeHtml(data.warning)}</p>` : "") +
    `<div class="preview-actions">` +
    `<a class="btn btn-line" href="${data.searchUrl}" target="_blank" rel="noopener">네이버플러스스토어에서 열기 ↗</a>` +
    `<button id="btnRegister" class="btn" type="button">매뉴얼 키워드 등록</button>` +
    `</div>` +
    `<p class="muted" style="font-size:11.5px;margin-top:10px">` +
    `네이버 쇼핑 검색 API가 2026-07-31 종료되어 상품 카드를 직접 불러올 수 없습니다. ` +
    `링크로 실제 결과를 확인해 주세요.</p>`;

  document.getElementById("btnRegister").addEventListener("click", () => registerKeyword(k));
}

function registerKeyword(k) {
  // 4단계에서 JSON body 생성으로 이어집니다.
  alert("4단계에서 이 키워드로 JSON body 를 만듭니다: " + k.keyword);
}

/* --------------------------------------------------------------- 설정 팝업 */

async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    state.config = await res.json();
  } catch (err) {
    state.config = null;
  }
}

function openSettings() {
  const c = state.config || {};
  document.getElementById("cfgStoreUrl").value = c.storeSearchUrl || "";
  document.getElementById("cfgStatus").textContent = "";
  document.getElementById("cfgStatus").className = "muted cfg-status";
  document.getElementById("settingsBackdrop").hidden = false;
}

async function saveSettings() {
  const status = document.getElementById("cfgStatus");
  status.className = "cfg-status";
  status.textContent = "저장 중…";
  try {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ storeSearchUrl: document.getElementById("cfgStoreUrl").value.trim() }),
    });
    state.config = await res.json();
    status.className = "cfg-status is-ok";
    status.textContent = "저장했어요.";
  } catch (err) {
    status.className = "cfg-status is-bad";
    status.textContent = "저장 실패: " + err.message;
  }
}

/* ------------------------------------------------------------------ 시작 */

function closeModal() {
  document.getElementById("modalBackdrop").hidden = true;
}

/* ------------------------------------------------------------------ 시작 */

function bindEvents() {
  document.getElementById("btnPrev").addEventListener("click", () => {
    state.weekStart = addDays(state.weekStart, -7);
    render();
  });
  document.getElementById("btnNext").addEventListener("click", () => {
    state.weekStart = addDays(state.weekStart, 7);
    render();
  });
  document.getElementById("btnToday").addEventListener("click", () => {
    state.weekStart = mondayOf(new Date());
    render();
  });
  document.getElementById("btnRefresh").addEventListener("click", async (e) => {
    e.target.disabled = true;
    await loadSchedule({ refresh: true });
    render();
    e.target.disabled = false;
  });
  document.getElementById("btnReanalyze").addEventListener("click", () => {
    if (state.currentProgram) loadKeywords(state.currentProgram, true);
  });
  document.getElementById("btnSettings").addEventListener("click", openSettings);
  document.getElementById("settingsClose").addEventListener("click", () => {
    document.getElementById("settingsBackdrop").hidden = true;
  });
  document.getElementById("settingsBackdrop").addEventListener("click", (e) => {
    if (e.target.id === "settingsBackdrop") e.target.hidden = true;
  });
  document.getElementById("cfgSave").addEventListener("click", saveSettings);
  document.getElementById("modalClose").addEventListener("click", closeModal);
  document.getElementById("modalBackdrop").addEventListener("click", (e) => {
    if (e.target.id === "modalBackdrop") closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const settings = document.getElementById("settingsBackdrop");
    if (!settings.hidden) settings.hidden = true;
    else closeModal();
  });
}

(async function main() {
  bindEvents();
  await Promise.all([loadSchedule(), loadRegistrations(), loadConfig()]);
  render();
  // 오늘 시간대가 화면에 보이도록 스크롤합니다.
  const nowMin = new Date().getHours() * 60 + new Date().getMinutes() - DAY_START_MIN;
  if (nowMin > 0) window.scrollTo({ top: Math.max(0, nowMin * PX_PER_MIN - 200) });
})();
