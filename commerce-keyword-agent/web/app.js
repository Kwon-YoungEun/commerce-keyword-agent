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
  programIds: {},
  bodyDraft: null,
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
    (p.episode ? ` · ${p.episode}` : "") + (p.genre ? ` · ${p.genre}${p.subGenre ? "(" + p.subGenre + ")" : ""}` : "") +
    (p.subtitle ? ` · ${p.subtitle}` : "");

  document.getElementById("previewPanel").innerHTML =
    '<div class="placeholder">왼쪽에서 키워드를 클릭하면 검색 결과를 미리 봅니다.</div>';
  renderRegistered(p);
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
  if (!body.productInfo[0].productKeyword) {
    setBodyStatus("productKeyword 가 비어 있어요. 먼저 채워 주세요.", "bad");
    return;
  }
  if (!body.programId) {
    setBodyStatus("programId 가 비어 있어요. 먼저 채워 주세요.", "bad");
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
    programId: p.id,               // tvN 편성 ID (캘린더 표시용)
    programCode: body.programId,   // 전송 body 의 programId
    programName: body.programName,
    date: p.date,
    episode: p.episode,
    keyword: body.productInfo[0].productKeyword,
    bodyText: bodyToText(body, true),
    body: body,
  };

  try {
    const res = await fetch("/api/registrations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(item),
    });
    const json = await res.json();
    if (!json.ok) throw new Error(json.error || "등록에 실패했습니다.");
    setBodyStatus("캘린더에 등록했어요 — " + item.keyword, "ok");
    await loadRegistrations();
    render();
    renderRegistered(p);
    setTimeout(() => { document.getElementById("bodyBackdrop").hidden = true; }, 900);
  } catch (err) {
    setBodyStatus("등록 실패: " + err.message, "bad");
  }
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
      "<td>" + escapeHtml(row.name) +
      (row.genre
        ? ' <span class="cat cat-' + escapeHtml(row.genre) + '"' +
          (row.subGenre ? ' title="' + escapeHtml(row.subGenre) + '"' : "") +
          ">" + escapeHtml(row.genre) + "</span>"
        : ' <span class="cat cat-none" title="tvN 프로그램 목록에서 아직 못 찾은 프로그램이에요">장르 미상</span>') +
      "</td>" +
      '<td class="col-num">' + row.count + "회</td>" +
      '<td><span class="input-row">' +
      '<input type="text" placeholder="예: CS02070316">' +
      '<button type="button" class="btn btn-sm"></button>' +
      "</span></td>";

    const input = tr.querySelector("input");
    const btn = tr.querySelector("button");
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
  const items = state.registrationsByProgram.get(program.id) || [];
  box.hidden = items.length === 0;
  if (!items.length) return;

  box.innerHTML =
    "<h4>이 회차에 등록된 키워드 (" + items.length + "건)</h4><ul>" +
    items
      .map((it) => {
        const when = new Date((it.createdAt || 0) * 1000);
        const stamp =
          when.getMonth() + 1 + "/" + when.getDate() + " " +
          String(when.getHours()).padStart(2, "0") + ":" +
          String(when.getMinutes()).padStart(2, "0");
        const shown = it.keyword || (it.keywords || []).join(", ");
        return "<li>" + escapeHtml(shown) +
          ' <span class="muted">· ' + escapeHtml(it.programCode || "") + " · " + stamp + "</span>" +
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
  await Promise.all([loadSchedule(), loadRegistrations(), loadConfig(), loadProgramIds()]);
  render();
  // 오늘 시간대가 화면에 보이도록 스크롤합니다.
  const nowMin = new Date().getHours() * 60 + new Date().getMinutes() - DAY_START_MIN;
  if (nowMin > 0) window.scrollTo({ top: Math.max(0, nowMin * PX_PER_MIN - 200) });
})();
