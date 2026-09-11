/* AI 커머스광고 키워드 Agent — 1단계: tvN 편성표 캘린더 */

const PX_PER_MIN = 1.25;   // style.css 의 --px-per-min 과 같아야 합니다.
const DAY_START_MIN = 5 * 60;  // 방송일은 05:00 에 시작하는 것으로 봅니다.
const VIEW_START_MIN = 30;     // 화면은 05:30 부터 보여 줘서 위쪽이 잘린 것처럼 둡니다.

/** 방송일 기준 분(05:00=0)을 화면 y 좌표로 바꿉니다. */
function posY(offsetMin) {
  return (offsetMin - VIEW_START_MIN) * PX_PER_MIN;
}

function gridHeight() {
  return (state.totalMin - VIEW_START_MIN) * PX_PER_MIN;
}
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
  programIds: {},
  programGenres: {},
  genreChoices: [],
  genrePickerFor: null,
  bodyDraft: null,
  summary: null,
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
    // 키워드는 회차가 아니라 프로그램에 붙습니다.
    state.registrationsByProgram = new Map();
    for (const item of json.items || []) {
      const key = item.programName || item.programId;
      if (!state.registrationsByProgram.has(key)) state.registrationsByProgram.set(key, []);
      state.registrationsByProgram.get(key).push(item);
    }
    for (const list of state.registrationsByProgram.values()) {
      list.sort((a, b) => (a.createdAt || 0) - (b.createdAt || 0));
    }
  } catch (err) {
    /* 등록 이력이 없어도 캘린더는 그립니다. */
  }
}

/** 이 프로그램에 등록된 이력 전체 (최근 등록이 앞). */
function programRegistrations(program) {
  const list = (state.registrationsByProgram.get(program.programName || program.title) || []).slice();
  list.sort((a, b) => (b.fromTs || 0) - (a.fromTs || 0) || (b.createdAt || 0) - (a.createdAt || 0));
  return list;
}

/** 이 회차 방송 시각에 유효했던 키워드 하나.
 *  매뉴얼 키워드는 한 시점에 한 개뿐이라, 바꾸기 전 편성에는 예전 키워드가 남습니다. */
function activeRegistration(program) {
  const ts = program.startTs || 0;
  let best = null;
  for (const r of state.registrationsByProgram.get(program.programName || program.title) || []) {
    const from = r.fromTs || 0;
    if (from > ts) continue;
    const bf = best ? best.fromTs || 0 : -1;
    if (!best || from > bf || (from === bf && (r.createdAt || 0) > (best.createdAt || 0))) {
      best = r;
    }
  }
  return best;
}

function registrationsFor(program) {
  const active = activeRegistration(program);
  return active ? [active] : [];
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

    const cell = document.createElement("div");
    cell.className = "day-head";
    if (i === 5) cell.classList.add("is-sat");
    if (i === 6) cell.classList.add("is-sun");
    if (key === todayKey) cell.classList.add("is-today");

    cell.innerHTML =
      `<div class="wk">${WKDAY[date.getDay()]}</div>` +
      `<div class="dd">${date.getDate()}</div>`;
    wrap.appendChild(cell);
  }
}

function renderTimeGutter() {
  const gutter = document.getElementById("timeGutter");
  gutter.innerHTML = "";
  gutter.style.height = gridHeight() + "px";
  for (let m = 60; m <= state.totalMin; m += 60) {
    const label = document.createElement("div");
    label.className = "hour";
    label.style.top = posY(m) + "px";
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
    col.style.height = gridHeight() + "px";
    if (key === todayKey) col.classList.add("is-today");
    if (!list.length) col.classList.add("is-empty");

    for (const p of list) col.appendChild(programBlock(p));
    const line = nowLine(key);
    if (line) col.appendChild(line);
    grid.appendChild(col);
  }
}

function programBlock(p) {
  const height = Math.max(16, p.durationMin * PX_PER_MIN - 3);
  const regs = registrationsFor(p);

  const el = document.createElement("button");
  el.type = "button";
  el.className = "pgm";
  el.dataset.airing = p.id;
  if (p.liveFlag === "본") el.classList.add("is-live");
  if (regs.length) el.classList.add("is-registered");
  if (height < 46) el.classList.add("is-short");
  el.style.top = posY(p.offsetMin) + "px";
  el.style.height = height + "px";
  el.title = `${p.start}~${p.end} ${p.title}` + (p.episode ? ` ${p.episode}` : "") +
    (regs.length ? `\n등록 키워드: ${regs.map((r) => r.keyword).join(", ")}` : "");

  const flag = p.liveFlag === "본" ? '<span class="pgm-flag">본</span>' : "";
  el.innerHTML =
    `<div class="t">${p.start}</div>` +
    `<div class="n">${flag}${escapeHtml(p.title)}</div>` +
    (p.episode ? `<div class="e">${escapeHtml(p.episode)}</div>` : "") +
    (regs.length ? keywordChipsHtml(regs, height) : "");

  el.addEventListener("click", () => openProgram(p));
  return el;
}

/** 블록 높이에 맞춰 키워드를 몇 개까지 보여 줄지 정합니다. */
function keywordChipsHtml(regs, height) {
  const room = Math.max(1, Math.floor((height - 40) / 17));
  const shown = regs.slice(0, Math.min(room, 3));
  const rest = regs.length - shown.length;
  return (
    '<div class="pgm-keys">' +
    shown.map((r) => `<span class="pgm-key">${escapeHtml(r.keyword)}</span>`).join("") +
    (rest > 0 ? `<span class="pgm-key is-more">+${rest}</span>` : "") +
    "</div>"
  );
}

/** 지금 시각이 어느 방송일의 몇 분째인지.
 *  새벽 0~5시는 아직 전날 방송일이라 하루를 되돌려 계산합니다. */
function nowPosition() {
  const now = new Date();
  let min = now.getHours() * 60 + now.getMinutes() - DAY_START_MIN;
  let dayKey = ymd(now);
  if (min < 0) {
    min += 24 * 60;
    dayKey = ymd(addDays(now, -1));
  }
  return { dayKey: dayKey, min: min };
}

function nowLine(dayKey) {
  const pos = nowPosition();
  if (dayKey !== pos.dayKey) return null;
  if (pos.min < VIEW_START_MIN || pos.min > state.totalMin) return null;
  const el = document.createElement("div");
  el.className = "now-line";
  el.style.top = posY(pos.min) + "px";
  el.title = "지금 방송 중인 시각";
  return el;
}

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

/** 상단 바 높이를 재서 캘린더 헤더가 딱 그 아래에 붙도록 합니다.
 *  창이 좁아지면 상단 바 버튼이 줄바꿈돼 높이가 달라집니다. */
function syncStickyOffset() {
  const bar = document.querySelector(".topbar");
  if (!bar) return;
  // 올림이 아니라 내림을 씁니다. 반올림하면 소수점 높이에서 1px 틈이 생겨
  // 그 사이로 편성 블록이 비쳐 보입니다.
  const h = Math.floor(bar.getBoundingClientRect().height);
  document.documentElement.style.setProperty("--topbar-h", h + "px");
}

function render() {
  syncStickyOffset();
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
    (p.episode ? ` · ${p.episode}` : "") + (p.genre ? ` · ${p.genre}${p.subGenre ? "(" + p.subGenre + ")" : ""}` : "") +
    (p.subtitle ? ` · ${p.subtitle}` : "");

  document.getElementById("previewPanel").innerHTML =
    '<div class="placeholder">왼쪽에서 키워드를 클릭하면 검색 결과를 미리 봅니다.</div>';
  renderRegistered(p);
  document.getElementById("modalBackdrop").hidden = false;
  loadSummary(p);              // tvN 공식 요약은 따로 빨리 가져옵니다.
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

/** 방송 요약 — tvN 공식 회차 미리보기와 출연진을 씁니다.
 *  공식 자료가 없을 때만 검색 결과로 채웁니다. */
async function loadSummary(program) {
  const box = document.getElementById("summaryBox");
  box.hidden = true;
  state.summary = null;
  try {
    const res = await fetch("/api/summary?programId=" + encodeURIComponent(program.id));
    const json = await res.json();
    if (state.currentProgram !== program) return;   // 그새 다른 회차를 열었으면 무시
    state.summary = json;
    renderSummaryBox(json);
  } catch (err) {
    renderSummaryBox(null);
  }
}

/** 방송 요약 — tvN 공식, 티빙, 직접 적어 둔 설명 순서로만 씁니다.
 *  셋 다 없으면 추측해서 채우지 않고 없다고 알립니다. */
function renderSummaryBox(tvn) {
  const box = document.getElementById("summaryBox");

  if (!tvn || !tvn.ok || !tvn.available) {
    box.innerHTML =
      "<h3>방송 요약</h3>" +
      '<p class="sum-empty">이 프로그램 정보를 찾지 못했어요. ' +
      "tvN·티빙 어디에도 자료가 없습니다.</p>";
    box.hidden = false;
    return;
  }

  const rows = [];
  if ((tvn.cast || []).length) {
    rows.push(
      '<div class="sum-row"><span class="sum-key">출연</span>' +
      '<span class="sum-val">' + tvn.cast.map(escapeHtml).join(" · ") + "</span></div>"
    );
  }

  const SOURCE_NAME = { tvn: "tvN 공식", tving: "티빙", note: "직접 적어 둔 설명" };
  let lines = [];
  let footer = "";

  if (tvn.preview) {
    lines = tvn.preview.lines.slice(0, 3).map(escapeHtml);
    const label = SOURCE_NAME[tvn.source] || "";
    footer = (tvn.url && tvn.preview.title)
      ? label + ' <a href="' + escapeHtml(tvn.url) + '" target="_blank" rel="noopener">' +
        escapeHtml(tvn.preview.title) + " ↗</a>"
      : label;
  } else {
    if (tvn.broadcast) lines.push(escapeHtml(tvn.broadcast));
    if (tvn.source !== "tvn") {
      footer = (SOURCE_NAME[tvn.source] || "") + " 기준 · 회차별 내용은 없어요.";
    } else if (tvn.hasPreviews) {
      footer = "이 회차 미리보기는 tvN 에 없어요. (최근 회차만 제공됩니다)";
    } else {
      footer = "tvN 에 회차 미리보기가 없는 프로그램이에요.";
    }
  }

  if (lines.length) {
    rows.push(
      '<div class="sum-row"><span class="sum-key">내용</span>' +
      '<span class="sum-val">' + lines.slice(0, 3).join("<br>") + "</span></div>"
    );
  }

  box.innerHTML = "<h3>방송 요약</h3>" + rows.join("") +
                  (footer ? '<p class="sum-note">' + footer + "</p>" : "");
  box.hidden = false;
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
    `</div>`;

  document.getElementById("btnRegister").addEventListener("click", () => registerKeyword(k));
}

/* ------------------------------------------------- JSON body 만들기 (4단계) */
//
// 바뀌는 값은 requestId / timestamp / programName / programId / productKeyword 다섯 개뿐입니다.
// 나머지는 아래 FIXED 값 그대로 나갑니다. 키워드는 한 번에 하나만 등록합니다.

const FIXED = {
  productIndex: 0,
  productMethod: ["MANUAL"],
  productScore: 27.0,
  isProductCropImg: false,
  productCropImg: "",
  pplInfo: [],
  productCategory: [],
};

function registerKeyword(k) {
  openBodyModal(k);
}

function newRequestId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

function buildBody({ programName, programId, keyword, requestId, timestamp }) {
  return {
    requestId: requestId,
    timestamp: timestamp,
    programName: programName,
    programId: programId,
    productInfo: [
      {
        productIndex: FIXED.productIndex,
        productKeyword: keyword,
        productMethod: FIXED.productMethod.slice(),
        productScore: FIXED.productScore,
        isProductCropImg: FIXED.isProductCropImg,
        productCropImg: FIXED.productCropImg,
        pplInfo: FIXED.pplInfo.slice(),
      },
    ],
    productCategory: FIXED.productCategory.slice(),
  };
}

// JSON.stringify 는 27.0 을 27 로 적습니다. 받은 예시와 똑같이 27.0 으로 내보냅니다.
function bodyToText(body, pretty) {
  const text = pretty ? JSON.stringify(body, null, 2) : JSON.stringify(body);
  return text.replace(/("productScore":\s*)27(?!\.)/g, "$1" + "27.0");
}

function openBodyModal(k) {
  if (!state.currentProgram) return;
  const p = state.currentProgram;
  const name = p.programName || p.title;
  const mapped = state.programIds[name] || "";

  state.bodyDraft = {
    keyword: k.keyword,          // 목록에서 고른 원래 키워드
    requestId: newRequestId(),
    timestamp: Date.now(),
    editingId: false,
  };
  document.getElementById("fldProductKeyword").value = k.keyword;
  document.getElementById("keywordHint").textContent = "";

  document.getElementById("fldProgramName").value = name;
  document.getElementById("fldProgramId").value = mapped;
  document.getElementById("bodyMeta").textContent =
    prettyDate(p.date) + " " + p.start + "~" + p.end +
    (p.episode ? " · " + p.episode : "") + " · 키워드 " + k.keyword;

  refreshBodyJson();
  document.getElementById("bodyBackdrop").hidden = false;
}

function currentBody() {
  const d = state.bodyDraft;
  if (!d) return null;
  return buildBody({
    programName: document.getElementById("fldProgramName").value.trim(),
    programId: document.getElementById("fldProgramId").value.trim(),
    keyword: document.getElementById("fldProductKeyword").value.trim(),
    requestId: d.requestId,
    timestamp: d.timestamp,
  });
}

/** programId 칸 상태 — 저장된 값이 있으면 잠그고 'ID 수정' 으로 풀 수 있게 합니다. */
function programIdState() {
  const name = document.getElementById("fldProgramName").value.trim();
  return {
    name: name,
    saved: state.programIds[name] || "",
    editing: Boolean(state.bodyDraft && state.bodyDraft.editingId),
  };
}

function updateProgramIdButton() {
  const st = programIdState();
  const input = document.getElementById("fldProgramId");
  const btn = document.getElementById("btnSaveProgramId");
  const hint = document.getElementById("programIdHint");
  const locked = Boolean(st.saved) && !st.editing;

  input.readOnly = locked;
  input.classList.toggle("is-locked", locked);
  btn.textContent = locked ? "ID 수정" : st.saved ? "저장" : "ID 저장";

  if (locked) {
    hint.textContent = "표에 저장된 ID 예요. 바꾸려면 ID 수정을 누르세요.";
  } else if (st.saved) {
    hint.textContent = "저장된 값은 " + st.saved + " 예요. 고친 뒤 저장을 누르세요.";
  } else {
    hint.textContent = input.value.trim()
      ? "표에 없는 ID 예요. ID 저장을 누르면 기억해 둡니다."
      : "등록된 ID가 없어요. 직접 넣고 ID 저장을 누르세요.";
  }
}

async function onProgramIdButton() {
  const st = programIdState();
  if (st.saved && !st.editing) {
    state.bodyDraft.editingId = true;
    updateProgramIdButton();
    const input = document.getElementById("fldProgramId");
    input.focus();
    input.select();
    return;
  }
  await saveProgramIdFromBody();
}

function refreshBodyJson() {
  const body = currentBody();
  if (!body) return;
  document.getElementById("bodyJson").value = bodyToText(body, true);
  updateProgramIdButton();

  const typed = body.productInfo[0].productKeyword;
  const hint = document.getElementById("keywordHint");
  hint.textContent = typed && typed !== state.bodyDraft.keyword
    ? "고른 키워드: " + state.bodyDraft.keyword + " (직접 고친 값으로 나갑니다)"
    : "";

  if (!typed) {
    setBodyStatus("productKeyword 가 비어 있어요.", "bad");
  } else if (!body.programId) {
    setBodyStatus("programId 가 비어 있어요. 프로그램 ID 를 넣어 주세요.", "bad");
  } else {
    setBodyStatus("");
  }
}

/** 페이지 안 확인창. 브라우저 confirm() 이 차단되는 환경이 있어 직접 만들었습니다. */
function askConfirm(message, okLabel) {
  return new Promise((resolve) => {
    const back = document.getElementById("askBackdrop");
    const ok = document.getElementById("askOk");
    const cancel = document.getElementById("askCancel");
    document.getElementById("askMessage").textContent = message;
    ok.textContent = okLabel || "확인";

    const done = (answer) => {
      back.hidden = true;
      ok.removeEventListener("click", onOk);
      cancel.removeEventListener("click", onCancel);
      back.removeEventListener("click", onBack);
      document.removeEventListener("keydown", onKey);
      resolve(answer);
    };
    const onOk = () => done(true);
    const onCancel = () => done(false);
    const onBack = (e) => { if (e.target === back) done(false); };
    const onKey = (e) => {
      if (e.key === "Escape") done(false);
      if (e.key === "Enter") done(true);
    };

    ok.addEventListener("click", onOk);
    cancel.addEventListener("click", onCancel);
    back.addEventListener("click", onBack);
    document.addEventListener("keydown", onKey);
    back.hidden = false;
    ok.focus();
  });
}

let toastTimer = null;

/** 화면 위쪽에 잠깐 뜨는 알림. 팝업이 닫혀도 보입니다. */
function showToast(text, kind) {
  const el = document.getElementById("toast");
  el.textContent = text;
  el.className = "toast" + (kind ? " is-" + kind : "");
  el.hidden = false;
  requestAnimationFrame(() => el.classList.add("is-on"));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    el.classList.remove("is-on");
    setTimeout(() => { el.hidden = true; }, 250);
  }, 5000);
}

function setBodyStatus(text, kind) {
  const status = document.getElementById("bodyStatus");
  status.className = "body-status" + (kind ? " is-" + kind : " muted");
  status.textContent = text;
}

async function copyText(text, okMessage) {
  try {
    await navigator.clipboard.writeText(text);
    setBodyStatus(okMessage, "ok");
  } catch (err) {
    setBodyStatus("복사가 막혀 있어요. 아래 상자에서 직접 선택해 복사해 주세요.", "bad");
  }
}

function downloadFile(filename, text, mime) {
  const blob = new Blob([text], { type: mime || "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function buildCurl(body) {
  const url = (state.config && state.config.registerApiUrl) || "<등록 API 주소를 설정에 넣어 주세요>";
  const json = bodyToText(body, false).split("'").join("'\\''");
  return (
    "curl -X POST '" + url + "' \\\n" +
    "  -H 'Content-Type: application/json' \\\n" +
    "  -d '" + json + "'"
  );
}

function buildPostmanCollection(body, program) {
  const url = (state.config && state.config.registerApiUrl) || "";
  let urlNode;
  if (url) {
    const withoutScheme = url.replace(/^https?:\/\//, "");
    const host = withoutScheme.split("/")[0];
    const path = withoutScheme.split("/").slice(1).filter(Boolean);
    urlNode = { raw: url, protocol: url.split("://")[0], host: [host], path: path };
  } else {
    urlNode = { raw: "{{baseUrl}}/keyword/manual", host: ["{{baseUrl}}"], path: ["keyword", "manual"] };
  }
  return {
    info: {
      name: "커머스광고 키워드 등록 - " + program.title,
      schema: "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    },
    item: [
      {
        name: (program.title + " " + (program.episode || "") + " " + state.bodyDraft.keyword).trim(),
        request: {
          method: "POST",
          header: [{ key: "Content-Type", value: "application/json" }],
          body: {
            mode: "raw",
            raw: bodyToText(body, true),
            options: { raw: { language: "json" } },
          },
          url: urlNode,
        },
      },
    ],
    variable: url ? [] : [{ key: "baseUrl", value: "https://example.com" }],
  };
}

async function confirmRegister() {
  const body = currentBody();
  if (!body) return;
  // 막힌 이유가 화면에서 바로 보이도록 알림을 띄우고 해당 칸으로 이동합니다.
  const block = (message, fieldId) => {
    setBodyStatus(message, "bad");
    showToast(message, "bad");
    const el = document.getElementById(fieldId);
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("is-blocked");
    setTimeout(() => el.classList.remove("is-blocked"), 2000);
    if (!el.readOnly) el.focus();
  };

  if (!body.productInfo[0].productKeyword) {
    block("등록하려면 productKeyword 를 채워 주세요.", "fldProductKeyword");
    return;
  }
  if (!body.programId) {
    block(
      body.programName + " 의 programId 가 없어요. 프로그램 ID 를 넣고 다시 눌러 주세요.",
      "fldProgramId"
    );
    return;
  }
  const p = state.currentProgram;

  if (state.programIds[body.programName] !== body.programId) {
    try {
      const res = await fetch("/api/program-ids", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: body.programName, id: body.programId }),
      });
      state.programIds = (await res.json()).map || state.programIds;
    } catch (err) {
      /* 표 저장에 실패해도 등록은 계속합니다. */
    }
  }

  const item = {
    id: body.requestId,
    programName: body.programName,   // 이 이름의 프로그램 전체에 적용됩니다.
    programCode: body.programId,     // 전송 body 의 programId
    scheduleId: p.id,                // 등록을 누른 회차(참고용)
    fromTs: p.startTs || 0,          // 이 회차부터 다음 등록 전까지 적용됩니다.
    date: p.date,
    startLabel: p.start,
    episode: p.episode,
    keyword: body.productInfo[0].productKeyword,
    bodyText: bodyToText(body, true),
    body: body,
  };

  // 매뉴얼 키워드는 한 시점에 한 개입니다. 바꾸면 이 회차부터 적용되고,
  // 그 전 편성에는 예전 키워드가 기록으로 남습니다.
  const current = activeRegistration(p);
  if (current && current.keyword !== item.keyword) {
    const ok = await askConfirm(
      `${item.programName} 은 지금 '${current.keyword}' 가 적용 중이에요. ` +
      `이 회차(${prettyDate(p.date)} ${p.start})부터 '${item.keyword}' 로 바뀝니다. ` +
      `그 전 편성에는 '${current.keyword}' 가 그대로 남습니다.`,
      "바꾸기"
    );
    if (!ok) {
      showToast("등록을 취소했어요.", "");
      return;
    }
  } else if (current) {
    const ok = await askConfirm(
      `'${item.keyword}' 는 이미 적용 중이에요. 다시 등록할까요?`, "다시 등록"
    );
    if (!ok) {
      showToast("등록을 취소했어요.", "");
      return;
    }
  }

  try {
    const res = await fetch("/api/registrations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(item),
    });
    const json = await res.json();
    if (!json.ok) throw new Error(json.error || "등록에 실패했습니다.");
    await loadRegistrations();          // 개수를 세기 전에 먼저 갱신합니다.
    render();
    renderRegistered(p);

    const hits = countAppliedAirings(item);
    const prev = json.previous && json.previous !== item.keyword ? json.previous : "";
    const message =
      "등록했어요 — " + item.keyword + " · 이번 주 " + hits + "개 편성에 표시됩니다." +
      (prev ? " (이전 편성은 '" + prev + "' 유지)" : "");
    setBodyStatus(message, "ok");
    showToast(message, "ok");

    // 등록이 끝나면 팝업을 모두 닫고 캘린더로 돌아갑니다.
    // 결과 문구는 화면 위 알림으로 남아 있습니다.
    document.getElementById("bodyBackdrop").hidden = true;
    closeModal();
    revealAiring(p.id);
  } catch (err) {
    setBodyStatus("등록 실패: " + err.message, "bad");
    showToast("등록 실패: " + err.message, "bad");
  }
}

/** 방금 등록한 회차를 캘린더 화면에 띄우고 잠깐 표시해 줍니다. */
function revealAiring(airingId) {
  const block = document.querySelector('.pgm[data-airing="' + airingId + '"]');
  if (!block) return;
  block.scrollIntoView({ behavior: "smooth", block: "center" });
  block.classList.add("is-flash");
  setTimeout(() => block.classList.remove("is-flash"), 2400);
}

function countAppliedAirings(item) {
  let n = 0;
  for (const list of state.programsByDate.values()) {
    for (const p of list) {
      if ((p.programName || p.title) !== item.programName) continue;
      const active = activeRegistration(p);
      if (active && active.id === item.id) n++;
    }
  }
  return n;
}

/* --------------------------------------------- 편성 프로그램 ID 표 관리 */

async function putProgramId(name, id) {
  const res = await fetch("/api/program-ids", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: name, id: id }),
  });
  const json = await res.json();
  state.programIds = json.map || state.programIds;
  return json;
}

async function saveProgramIdFromBody() {
  const name = document.getElementById("fldProgramName").value.trim();
  const id = document.getElementById("fldProgramId").value.trim();
  if (!name) {
    setBodyStatus("programName 이 비어 있어요.", "bad");
    return;
  }
  try {
    await putProgramId(name, id);
    if (state.bodyDraft) state.bodyDraft.editingId = false;
    updateProgramIdButton();
    setBodyStatus(
      id ? "프로그램 ID 를 표에 저장했어요 — " + name + " → " + id
         : name + " 의 ID 를 표에서 지웠어요.",
      "ok"
    );
  } catch (err) {
    setBodyStatus("저장 실패: " + err.message, "bad");
  }
}

/** 지금 보고 있는 주에 편성된 프로그램을 이름 기준으로 모읍니다. */
function weekProgramNames() {
  const map = new Map();
  for (let i = 0; i < 7; i++) {
    const key = ymd(addDays(state.weekStart, i));
    for (const p of state.programsByDate.get(key) || []) {
      const name = p.programName || p.title;
      if (!map.has(name)) map.set(name, { name: name, count: 0, genre: "", subGenre: "" });
      const row = map.get(name);
      row.count += 1;
      if (!row.genre && p.genre) {          // 장르를 아는 회차가 하나라도 있으면 씁니다.
        row.genre = p.genre;
        row.subGenre = p.subGenre || "";
      }
    }
  }
  return [...map.values()].sort(
    (a, b) => b.count - a.count || a.name.localeCompare(b.name, "ko")
  );
}

/** 장르 칩 — 누르면 직접 고를 수 있습니다. */
function genreChipHtml(row) {
  // 직접 지정한 장르도 따로 표시하지 않고 똑같이 보여 줍니다.
  // 어떤 태그든 누르면 바꿀 수 있습니다.
  const title = row.genre
    ? (row.subGenre ? row.subGenre + " · " : "") + "누르면 장르를 바꿉니다"
    : "tvN 프로그램 목록에 아직 없는 프로그램이에요. 눌러서 골라 주세요";
  const cls = row.genre ? "cat cat-" + row.genre : "cat cat-none";
  const label = row.genre || "장르 미상";
  return ' <button type="button" class="' + cls +
         '" title="' + escapeHtml(title) + '">' + escapeHtml(label) + "</button>";
}

function closeGenrePicker() {
  const old = document.getElementById("genrePicker");
  if (old) old.remove();
  state.genrePickerFor = null;
}

function openGenrePicker(chip, row, rows) {
  // 같은 태그를 다시 누르면 닫습니다.
  if (state.genrePickerFor === row.name && document.getElementById("genrePicker")) {
    closeGenrePicker();
    return;
  }
  closeGenrePicker();
  state.genrePickerFor = row.name;

  const box = document.createElement("div");
  box.id = "genrePicker";
  box.className = "genre-picker";

  const current = state.programGenres[row.name] || row.genre || "";
  const choices = state.genreChoices.length
    ? state.genreChoices
    : ["드라마", "예능", "교양", "브랜디드", "영화", "스포츠", "기타"];

  for (const g of choices) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "genre-opt" + (g === current ? " is-current" : "");
    b.textContent = g;
    b.addEventListener("click", () => setProgramGenre(row.name, g, rows));
    box.appendChild(b);
  }
  if (state.programGenres[row.name]) {
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "genre-opt is-reset";
    reset.textContent = "직접 지정 지우기";
    reset.addEventListener("click", () => setProgramGenre(row.name, "", rows));
    box.appendChild(reset);
  }

  document.body.appendChild(box);
  // 팝업 안에서 눌러도 제자리에 뜨도록 화면 기준(fixed)으로 붙입니다.
  const r = chip.getBoundingClientRect();
  const w = box.offsetWidth, h = box.offsetHeight;
  const below = r.bottom + 6 + h <= window.innerHeight;
  box.style.top = (below ? r.bottom + 6 : Math.max(8, r.top - h - 6)) + "px";
  box.style.left = Math.max(8, Math.min(r.left, window.innerWidth - w - 12)) + "px";
}

async function setProgramGenre(name, genre, rows) {
  closeGenrePicker();
  setPidStatus("저장 중…");
  try {
    const res = await fetch("/api/program-genres", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name, genre: genre }),
    });
    state.programGenres = (await res.json()).map || {};
    await loadSchedule();          // 편성표에도 장르가 반영됩니다.
    render();
    openProgramList();
    setPidStatus(genre ? name + " → " + genre + " 로 지정했어요." : name + " 의 지정을 지웠어요.", "ok");
  } catch (err) {
    setPidStatus("저장 실패: " + err.message, "bad");
  }
}

function updatePidMeta(total) {
  const missing = document.querySelectorAll("#pidBody tr.is-missing").length;
  const noGenre = document.querySelectorAll("#pidBody .cat-none").length;
  document.getElementById("pidMeta").textContent =
    prettyDate(ymd(state.weekStart)) + " ~ " + prettyDate(ymd(addDays(state.weekStart, 6))) +
    " · 프로그램 " + total + "개 · ID 없음 " + missing + "개" +
    (noGenre ? " · 장르 미상 " + noGenre + "개" : "");
}

function openProgramList() {
  const rows = weekProgramNames();
  const body = document.getElementById("pidBody");
  body.innerHTML = "";
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      '<td><span class="name-cell">' + escapeHtml(row.name) +
      genreChipHtml(row) + "</span></td>" +
      '<td class="col-num">' + row.count + "회</td>" +
      '<td><span class="input-row">' +
      '<input type="text" placeholder="예: CS02070316">' +
      '<button type="button" class="btn btn-sm"></button>' +
      "</span></td>";

    const input = tr.querySelector("input");
    const btn = tr.querySelector(".input-row button");   // 장르 칩이 아니라 ID 버튼
    input.dataset.name = row.name;
    input.value = state.programIds[row.name] || "";
    let editing = false;

    // 저장된 ID 가 있으면 잠가 두고, 'ID 수정' 을 눌러야 고칠 수 있게 합니다.
    const paint = () => {
      const saved = state.programIds[row.name] || "";
      const locked = Boolean(saved) && !editing;
      input.readOnly = locked;
      input.classList.toggle("is-locked", locked);
      btn.textContent = locked ? "ID 수정" : saved ? "저장" : "ID 저장";
      tr.classList.toggle("is-missing", !input.value.trim());
      tr.title = saved && input.value.trim() !== saved ? "저장된 값: " + saved : "";
    };

    const saveOne = async () => {
      try {
        await putProgramId(row.name, input.value.trim());
        editing = false;
        paint();
        updatePidMeta(rows.length);
        setPidStatus(
          input.value.trim()
            ? row.name + " → " + input.value.trim() + " 저장했어요."
            : row.name + " 의 ID 를 지웠어요.",
          "ok"
        );
      } catch (err) {
        setPidStatus("저장 실패: " + err.message, "bad");
      }
    };

    btn.addEventListener("click", () => {
      const saved = state.programIds[row.name] || "";
      if (saved && !editing) {
        editing = true;
        paint();
        input.focus();
        input.select();
        return;
      }
      saveOne();
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !input.readOnly) saveOne();
    });
    input.addEventListener("input", paint);

    const chip = tr.querySelector(".cat");
    if (chip) chip.addEventListener("click", (e) => openGenrePicker(e.currentTarget, row, rows));

    paint();
    body.appendChild(tr);
  }

  updatePidMeta(rows.length);
  setPidStatus(rows.length ? "" : "이 주에는 편성 데이터가 없어요.");
  document.getElementById("pidBackdrop").hidden = false;
}

function setPidStatus(text, kind) {
  const el = document.getElementById("pidStatus");
  el.className = "body-status" + (kind ? " is-" + kind : " muted");
  el.textContent = text;
}

async function saveAllProgramIds() {
  const map = {};
  document.querySelectorAll("#pidBody input").forEach((input) => {
    if (input.readOnly) return;   // 잠긴 줄(이미 저장된 ID)은 건드리지 않습니다.
    map[input.dataset.name] = input.value.trim();
  });
  if (!Object.keys(map).length) {
    setPidStatus("새로 저장할 줄이 없어요. 고치려면 그 줄의 ID 수정을 눌러 주세요.");
    return;
  }
  setPidStatus("저장 중…");
  try {
    const res = await fetch("/api/program-ids", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ map: map }),
    });
    state.programIds = (await res.json()).map || {};
    const saved = Object.values(map).filter(Boolean).length;
    openProgramList();   // 저장된 줄은 다시 잠긴 상태로 그립니다.
    setPidStatus("저장했어요. 이번에 " + saved + "개를 등록했습니다.", "ok");
  } catch (err) {
    setPidStatus("저장 실패: " + err.message, "bad");
  }
}

/* --------------------------------------------- 등록된 키워드 보기 (6단계) */

function renderRegistered(program) {
  const box = document.getElementById("registeredBox");
  const history = programRegistrations(program);
  box.hidden = history.length === 0;
  if (!history.length) return;

  const active = activeRegistration(program);
  const fmt = (ts) => {
    const d = new Date((ts || 0) * 1000);
    return (d.getMonth() + 1) + "/" + d.getDate() + " " +
      String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  };

  box.innerHTML =
    "<h4>" + escapeHtml(program.programName || program.title) + " 의 매뉴얼 키워드</h4>" +
    '<p class="muted" style="margin:0 0 8px;font-size:11.5px">' +
    "한 시점에 한 개만 적용됩니다. 새로 등록하면 그 회차부터 바뀌고, " +
    "그 전 편성에는 예전 키워드가 기록으로 남습니다.</p>" +
    '<p style="margin:0 0 8px;font-size:12.5px">이 회차 적용: ' +
    (active
      ? '<strong style="color:var(--skb-red)">' + escapeHtml(active.keyword) + "</strong>"
      : '<span class="muted">없음</span>') +
    "</p><ul>" +
    history
      .map((it) => {
        const isActive = active && it.id === active.id;
        return "<li>" + (isActive ? "<strong>" : "") + escapeHtml(it.keyword) +
          (isActive ? "</strong>" : "") +
          ' <span class="muted">· ' + escapeHtml(prettyDate(it.date || "")) + " " +
          escapeHtml(it.startLabel || "") + " 회차부터 · " +
          escapeHtml(it.programCode || "") + " · " + fmt(it.createdAt) + " 등록</span>" +
          '<button type="button" data-reg="' + escapeHtml(it.id) + '">삭제</button></li>';
      })
      .join("") +
    "</ul>";

  box.querySelectorAll("button[data-reg]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await fetch("/api/registrations?id=" + encodeURIComponent(btn.dataset.reg), { method: "DELETE" });
      await loadRegistrations();
      render();
      renderRegistered(program);
    });
  });
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
  document.getElementById("cfgRegisterUrl").value = c.registerApiUrl || "";
  document.getElementById("cfgProgramIds").value = Object.entries(state.programIds)
    .map(([name, id]) => name + "," + id)
    .join("\n");
  document.getElementById("cfgStatus").textContent = "";
  document.getElementById("cfgStatus").className = "muted cfg-status";
  document.getElementById("settingsBackdrop").hidden = false;
}

function parseProgramIdText(text) {
  const map = {};
  for (const line of (text || "").split(/\r?\n/)) {
    const row = line.trim();
    if (!row) continue;
    const cut = row.lastIndexOf(",");
    if (cut < 1) continue;
    const name = row.slice(0, cut).trim();
    const id = row.slice(cut + 1).trim();
    if (name) map[name] = id;
  }
  return map;
}

async function saveSettings() {
  const status = document.getElementById("cfgStatus");
  status.className = "cfg-status";
  status.textContent = "저장 중…";
  try {
    const cfgRes = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        storeSearchUrl: document.getElementById("cfgStoreUrl").value.trim(),
        registerApiUrl: document.getElementById("cfgRegisterUrl").value.trim(),
      }),
    });
    state.config = await cfgRes.json();

    const map = parseProgramIdText(document.getElementById("cfgProgramIds").value);
    const idRes = await fetch("/api/program-ids", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ map: map }),
    });
    state.programIds = (await idRes.json()).map || {};

    status.className = "cfg-status is-ok";
    status.textContent = "저장했어요. 프로그램 ID " + Object.keys(state.programIds).length + "개 등록됨.";
  } catch (err) {
    status.className = "cfg-status is-bad";
    status.textContent = "저장 실패: " + err.message;
  }
}

async function loadProgramGenres() {
  try {
    const res = await fetch("/api/program-genres");
    const json = await res.json();
    state.programGenres = json.map || {};
    state.genreChoices = json.choices || [];
  } catch (err) {
    state.programGenres = {};
  }
}

async function loadProgramIds() {
  try {
    const res = await fetch("/api/program-ids");
    state.programIds = (await res.json()).map || {};
  } catch (err) {
    state.programIds = {};
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

  document.getElementById("bodyClose").addEventListener("click", () => {
    document.getElementById("bodyBackdrop").hidden = true;
  });
  document.getElementById("bodyBackdrop").addEventListener("click", (e) => {
    if (e.target.id === "bodyBackdrop") e.target.hidden = true;
  });
  document.getElementById("fldProgramName").addEventListener("input", refreshBodyJson);
  document.getElementById("fldProgramId").addEventListener("input", refreshBodyJson);
  document.getElementById("fldProductKeyword").addEventListener("input", refreshBodyJson);
  document.getElementById("btnRegenIds").addEventListener("click", () => {
    state.bodyDraft.requestId = newRequestId();
    state.bodyDraft.timestamp = Date.now();
    refreshBodyJson();
    setBodyStatus("requestId 와 timestamp 를 새로 만들었어요.", "ok");
  });
  document.getElementById("btnCopyBody").addEventListener("click", () => {
    const body = currentBody();
    if (body) copyText(bodyToText(body, true), "JSON 을 복사했어요. Postman Body(raw)에 붙여 넣으세요.");
  });
  document.getElementById("btnDownloadBody").addEventListener("click", () => {
    const body = currentBody();
    if (!body) return;
    downloadFile("keyword-body-" + body.requestId.slice(0, 8) + ".json", bodyToText(body, true));
    setBodyStatus("JSON 파일을 저장했어요.", "ok");
  });
  document.getElementById("btnCopyCurl").addEventListener("click", () => {
    const body = currentBody();
    if (!body) return;
    if (!(state.config && state.config.registerApiUrl)) {
      setBodyStatus("설정에 등록 API 주소를 넣으면 주소까지 채워집니다.", "bad");
    }
    copyText(buildCurl(body), "curl 명령을 복사했어요.");
  });
  document.getElementById("btnPostman").addEventListener("click", () => {
    const body = currentBody();
    if (!body) return;
    const collection = buildPostmanCollection(body, state.currentProgram);
    downloadFile("postman-" + body.requestId.slice(0, 8) + ".json", JSON.stringify(collection, null, 2));
    setBodyStatus("Postman 컬렉션을 저장했어요. Postman → Import 로 불러오세요.", "ok");
  });
  document.getElementById("btnConfirmRegister").addEventListener("click", confirmRegister);
  document.getElementById("btnSaveProgramId").addEventListener("click", onProgramIdButton);
  document.getElementById("fldProgramId").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.target.readOnly) saveProgramIdFromBody();
  });

  document.getElementById("btnProgramList").addEventListener("click", openProgramList);
  window.addEventListener("resize", syncStickyOffset);
  // 장르 메뉴는 메뉴 바깥·태그 바깥을 눌렀을 때만 닫습니다.
  document.addEventListener("click", (e) => {
    if (e.target.closest("#genrePicker") || e.target.closest("button.cat")) return;
    closeGenrePicker();
  });
  document.getElementById("pidClose").addEventListener("click", () => {
    document.getElementById("pidBackdrop").hidden = true;
  });
  document.getElementById("pidBackdrop").addEventListener("click", (e) => {
    if (e.target.id === "pidBackdrop") e.target.hidden = true;
  });
  document.getElementById("pidSaveAll").addEventListener("click", saveAllProgramIds);
  document.getElementById("modalClose").addEventListener("click", closeModal);
  document.getElementById("modalBackdrop").addEventListener("click", (e) => {
    if (e.target.id === "modalBackdrop") closeModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    for (const id of ["settingsBackdrop", "bodyBackdrop", "pidBackdrop"]) {
      const el = document.getElementById(id);
      if (!el.hidden) {
        el.hidden = true;
        return;
      }
    }
    closeModal();
  });
}

(async function main() {
  bindEvents();
  await Promise.all([loadSchedule(), loadRegistrations(), loadConfig(),
                     loadProgramIds(), loadProgramGenres()]);
  render();
  // 오늘 시간대가 화면에 보이도록 스크롤합니다.
  const here = posY(nowPosition().min);
  if (here > 0) window.scrollTo({ top: Math.max(0, here - 200) });
})();
