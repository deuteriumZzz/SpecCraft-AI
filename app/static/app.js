// Фронтенд без фреймворка. Весь вывод идёт через textContent / value: ответ модели и ввод
// считаются недоверенными, innerHTML не используется нигде (защита от stored XSS). Позиции на
// шкалах задаются через CSSOM (element.style): это не inline-стили в разметке, CSP не нарушен.
"use strict";

const $ = (id) => document.getElementById(id);
const NO_DATA = "данных нет";
const TABS = ["card", "markdown", "json"];
const MODES = ["json", "form"];
const STORAGE_KEY = "speccraft.draft.v1";
const MAX_FILE_BYTES = 64 * 1024; // как лимит тела запроса на сервере
const EXAMPLE = {
  name: "Манометр технический МТ-100",
  manufacturer: "Приборзавод Тест",
  specs: { "диапазон измерений": "0–1,6 МПа", "класс точности": "1,5", "присоединение": "G1/2" },
  description: "Прибор предназначен для измерения избыточного давления жидкостей и газов.",
};
const FIELDS = [
  ["name", "обязательно"],
  ["manufacturer", "необязательно"],
  ["specs", "объект «название»: «значение»"],
  ["description", "паспорт или описание текстом"],
];
const INPUT_CLS = "w-full rounded-md border border-rule bg-sheet px-3 py-2 text-sm font-mono " +
  "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent";
const LEADER = "after:min-w-4 after:flex-1 after:-translate-y-0.5 after:border-b after:border-dotted after:border-rule after:content-['']";
const GHOST_BTN = "rounded-sm text-xs text-ink-2 underline decoration-rule underline-offset-4 " +
  "hover:text-accent hover:decoration-accent focus:outline-none focus-visible:ring-2 " +
  "focus-visible:ring-accent";

let result = null; // текущий черновик (его правит менеджер)
let original = null; // ответ сервиса без правок: для «Сбросить правки»
let edited = false; // менеджер правил черновик
let tab = "card";
let mode = "json";
let gauges = {};
let renderTimer = null;
let renderSeq = 0;
let pendingRender = Promise.resolve();
let saveTimer = null;

// ---------------------------------------------------------------- DOM-помощники
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function list(items, cls) {
  const ul = el("ul", "list-disc space-y-1 pl-5 " + cls);
  items.forEach((t) => ul.append(el("li", "", t)));
  return ul;
}

function setStatus(text) {
  $("status").textContent = text;
}

// ---------------------------------------------------------------- движение
// Только transform и opacity; токены длительности и кривой: frontend/tailwind.config.js.
const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const STAGGER_MS = 50;
const MAX_STAGGER_ITEMS = 12;

// Секции проявляются по очереди сверху вниз. При «уменьшить движение» остаётся только
// короткое затухание без смещения и без задержек.
function reveal(container) {
  const still = reducedMotion();
  [...container.children].slice(0, MAX_STAGGER_ITEMS).forEach((node, i) => {
    node.classList.add("motion-safe:animate-rise", "motion-reduce:animate-fade");
    if (!still) node.style.animationDelay = `${i * STAGGER_MS}ms`;
  });
}

// Перезапуск короткого затухания у существующего элемента (ошибка, кнопка «Скопировано»).
function flash(node) {
  node.classList.remove("animate-fade");
  void node.offsetWidth; // сброс анимации: без этого повторное добавление класса ничего не даст
  node.classList.add("animate-fade");
}

const HIGHLIGHT = ["ring-2", "ring-warn", "ring-offset-4", "ring-offset-sheet", "rounded-sm"];
function highlight(node) {
  node.classList.add(...HIGHLIGHT);
  setTimeout(() => node.classList.remove(...HIGHLIGHT), 1800);
}

function scrollToNode(node, block = "center") {
  node.scrollIntoView({ block, behavior: reducedMotion() ? "auto" : "smooth" });
}

// ---------------------------------------------------------------- хранение черновика ввода
function readStore() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
  } catch {
    return null; // приватный режим или повреждённые данные: просто начинаем с чистого листа
  }
}

function saveDraft() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ mode, json: $("input").value, form: readForm().payload }));
  } catch {
    /* хранилище недоступно: работа без запоминания */
  }
}

function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveDraft, 300);
}

// ---------------------------------------------------------------- форма
function specRow(key = "", value = "") {
  const row = el("div", "grid grid-cols-[1fr_1fr_auto] gap-2");
  const k = el("input", INPUT_CLS);
  const v = el("input", INPUT_CLS);
  [k, v].forEach((input) => { input.type = "text"; input.autocomplete = "off"; });
  k.maxLength = 100;
  v.maxLength = 300;
  k.value = key;
  v.value = value;
  k.placeholder = "Название";
  v.placeholder = "Значение";
  k.setAttribute("aria-label", "Название характеристики");
  v.setAttribute("aria-label", "Значение характеристики");
  const remove = el("button", "rounded-md px-2 text-lg leading-none text-ink-2 hover:text-warn " +
    "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent", "×");
  remove.type = "button";
  remove.setAttribute("aria-label", "Удалить характеристику");
  remove.addEventListener("click", () => {
    row.remove();
    if (!$("f-specs").children.length) $("f-specs").append(specRow());
    scheduleSave();
  });
  row.append(k, v, remove);
  return row;
}

function fillForm(payload) {
  $("f-name").value = typeof payload.name === "string" ? payload.name : "";
  $("f-maker").value = typeof payload.manufacturer === "string" ? payload.manufacturer : "";
  $("f-desc").value = typeof payload.description === "string" ? payload.description : "";
  const rows = Object.entries(payload.specs && typeof payload.specs === "object" ? payload.specs : {});
  $("f-specs").replaceChildren(...(rows.length ? rows : [["", ""]]).map(([k, v]) => specRow(k, String(v))));
}

// Возвращает { payload, error }: пустые строки характеристик пропускаются, дубли и
// значения без названия сообщаются по-русски до отправки на сервер.
function readForm() {
  const specs = {};
  let error = null;
  document.querySelectorAll("#f-specs > div").forEach((row) => {
    const [k, v] = row.querySelectorAll("input");
    const key = k.value.trim();
    const value = v.value.trim();
    if (!key && !value) return;
    if (!key) error = "У характеристики есть значение, но нет названия.";
    else if (Object.keys(specs).some((s) => s.toLowerCase() === key.toLowerCase())) {
      error = `Характеристика «${key}» указана дважды.`;
    }
    specs[key] = value;
  });
  return {
    payload: {
      name: $("f-name").value.trim(),
      manufacturer: $("f-maker").value.trim(),
      specs,
      description: $("f-desc").value.trim(),
    },
    error,
  };
}

function applyMode() {
  $("json-panel").hidden = mode !== "json";
  $("form-panel").hidden = mode !== "form";
  document.querySelectorAll(".mode").forEach((b) => {
    const selected = b.dataset.mode === mode;
    b.setAttribute("aria-selected", String(selected));
    b.tabIndex = selected ? 0 : -1;
  });
}

// Переключение переносит данные в другой режим. Если JSON не разобрать, остаёмся на месте
// и говорим об этом: молча потерять введённое нельзя.
function setMode(next) {
  if (next === mode) return;
  hideError();
  if (next === "form") {
    let parsed;
    try {
      parsed = JSON.parse($("input").value.trim() || "{}");
    } catch {
      parsed = null;
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      showError("Не удалось перейти в форму: JSON не разобран или это не один объект.",
        ["Исправьте JSON или останьтесь в режиме JSON."]);
      return;
    }
    fillForm(parsed);
  } else {
    $("input").value = JSON.stringify(readForm().payload, null, 2);
    checkJson();
  }
  mode = next;
  applyMode();
  scheduleSave();
}

function setPayload(payload) {
  if (mode === "form") fillForm(payload);
  else $("input").value = JSON.stringify(payload, null, 2);
  checkJson();
  scheduleSave();
}

// Единая точка получения данных для отправки: { payload } или { message, details }.
function buildPayload() {
  if (mode === "form") {
    const { payload, error } = readForm();
    return error ? { message: "Проверьте характеристики.", details: [error] } : { payload };
  }
  try {
    return { payload: JSON.parse($("input").value) };
  } catch {
    // Текст ошибки браузера английский и бесполезен менеджеру: даём типовую подсказку.
    return {
      message: "Введённый текст не является корректным JSON.",
      details: ["Проверьте скобки, кавычки вокруг названий и значений и запятые между полями."],
    };
  }
}

function checkJson() {
  const text = $("input").value.trim();
  const state = $("json-state");
  if (!text) {
    state.textContent = " ";
    return;
  }
  try {
    JSON.parse(text);
    state.textContent = "JSON корректен";
    state.className = "min-h-4 font-mono text-xs text-ok";
  } catch {
    state.textContent = "JSON не разобран";
    state.className = "min-h-4 font-mono text-xs text-warn";
  }
}

function clearAll() {
  $("input").value = "";
  fillForm({});
  result = null;
  original = null;
  edited = false;
  hideError();
  setStatus("");
  checkJson();
  render();
  try { localStorage.removeItem(STORAGE_KEY); } catch { /* нечего чистить */ }
}

// ---------------------------------------------------------------- файлы
async function loadFile(file) {
  if (!file) return;
  hideError();
  if (file.size > MAX_FILE_BYTES) {
    showError("Файл слишком большой.", ["Максимальный размер: 64 КБ."]);
    return;
  }
  let parsed;
  try {
    parsed = JSON.parse(await file.text());
  } catch {
    showError("Файл не содержит корректный JSON.");
    return;
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    showError("В файле должен быть один товар (JSON-объект).",
      ["Если товаров несколько, загружайте их по одному."]);
    return;
  }
  setPayload(parsed);
  setStatus(`Загружен файл ${file.name}.`);
}

function slug(text) {
  const s = text.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-+|-+$/g, "").slice(0, 50);
  return s || "kartochka";
}

function currentExport() {
  if (tab === "markdown") return { text: result.markdown, ext: "md", type: "text/markdown" };
  if (tab === "json") return { text: JSON.stringify(result, null, 2), ext: "json", type: "application/json" };
  return { text: result.text, ext: "txt", type: "text/plain" };
}

async function download() {
  if (!result) return;
  await ensureFresh();
  const { text, ext, type } = currentExport();
  const url = URL.createObjectURL(new Blob([text], { type: `${type};charset=utf-8` }));
  const link = el("a");
  link.href = url;
  link.download = `${slug(result.seo_title)}.${ext}`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  setStatus(`Скачан файл ${link.download}.`);
}

// ---------------------------------------------------------------- копирование
async function copyText(text, button, { fresh = false } = {}) {
  try {
    if (fresh) await ensureFresh();
    await navigator.clipboard.writeText(text);
  } catch {
    setStatus("Не удалось скопировать: выделите текст вручную.");
    return;
  }
  button.dataset.label = button.dataset.label || button.textContent;
  button.textContent = "Скопировано";
  flash(button);
  setStatus("Скопировано в буфер обмена.");
  clearTimeout(Number(button.dataset.timer));
  button.dataset.timer = String(setTimeout(() => { button.textContent = button.dataset.label; }, 1500));
}

function copyButton(getText) {
  const button = el("button", GHOST_BTN, "Копировать");
  button.type = "button";
  button.addEventListener("click", () => copyText(getText(), button));
  return button;
}

// ---------------------------------------------------------------- правки черновика
// Markdown и текст собирает сервер (одно место правды); после правок он пересобирается
// с задержкой, а копирование и скачивание дожидаются свежей версии.
function scheduleRender() {
  clearTimeout(renderTimer);
  renderTimer = setTimeout(() => {
    renderTimer = null;
    pendingRender = refreshRendered();
  }, 350);
}

async function refreshRendered() {
  const seq = ++renderSeq;
  const body = {
    seo_title: result.seo_title,
    seo_description: result.seo_description,
    characteristics: result.characteristics,
    search_queries: result.search_queries,
    commercial: result.commercial,
    missing_fields: result.missing_fields,
    warnings: result.warnings,
  };
  try {
    const resp = await fetch("/api/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error("render");
    const data = await resp.json();
    if (seq === renderSeq && result) {
      result.markdown = data.markdown;
      result.text = data.text;
      if (tab !== "card") render();
    }
  } catch {
    setStatus("Не удалось обновить Markdown и текст: правки видны только на экране.");
  }
}

function cancelPendingRender() {
  clearTimeout(renderTimer);
  renderTimer = null;
  renderSeq++; // ответы с прежним номером будут проигнорированы
}

async function ensureFresh() {
  if (renderTimer) {
    clearTimeout(renderTimer);
    renderTimer = null;
    pendingRender = refreshRendered();
  }
  await pendingRender;
}

function editable(value, cls, label, onInput) {
  const area = el("textarea", "block w-full resize-none overflow-hidden rounded-sm bg-transparent " +
    "decoration-rule hover:bg-paper/70 focus:bg-paper/70 focus:outline-none focus-visible:ring-2 " +
    "focus-visible:ring-accent " + cls);
  area.value = value;
  area.rows = 1;
  area.setAttribute("aria-label", label);
  const fit = () => { area.style.height = "auto"; area.style.height = area.scrollHeight + "px"; };
  area.addEventListener("input", () => { fit(); onInput(area.value); });
  requestAnimationFrame(fit);
  return area;
}

// Подпись «Черновик изменён» рисуется из флага edited, а не хранится в DOM: карточка
// перерисовывается при смене вкладок, и подпись не должна пропадать вместе с узлом.
function showEditNote() {
  const note = $("edit-state");
  if (!note) return;
  note.textContent = "";
  note.append("Черновик изменён. ");
  const reset = el("button", GHOST_BTN, "Сбросить правки");
  reset.type = "button";
  reset.addEventListener("click", () => {
    cancelPendingRender(); // запоздалый ответ /api/render не должен вернуть правленый текст
    result = structuredClone(original);
    edited = false;
    render();
    setStatus("Правки сброшены.");
  });
  note.append(reset);
}

function markEdited() {
  edited = true;
  showEditNote();
  scheduleRender();
}

// ---------------------------------------------------------------- шкалы
// Шкала-измеритель: стрелка показывает значение, зелёная полоса — допустимый диапазон.
function meter(title, value, [lo, hi], scaleMax) {
  const pct = (v) => Math.max(0, Math.min(100, (v / scaleMax) * 100));
  const readout = el("span");
  const track = el("div", "relative mt-2.5 h-1.5 rounded-full bg-rule");
  const band = el("div", "absolute inset-y-0 rounded-full bg-ok/35");
  band.style.left = pct(lo) + "%";
  band.style.width = pct(hi) - pct(lo) + "%";
  // Стрелка «выезжает» через transform: слой во всю ширину шкалы сдвигается в процентах от
  // своей ширины (left не анимируем: он вызывает перерасчёт раскладки).
  const slide = el("div", "absolute inset-0 motion-safe:transition-transform " +
    "motion-safe:duration-slow motion-safe:ease-smooth");
  const tick = el("div");
  slide.append(tick);
  track.append(band, slide);

  function set(v, moveNow = true) {
    const ok = v >= lo && v <= hi;
    readout.textContent = `${v} · ${ok ? "норма" : "вне нормы"}`;
    readout.className = "shrink-0 whitespace-nowrap font-mono text-xs tabular-nums " +
      (ok ? "text-ok" : "text-warn");
    tick.className = "absolute -top-1 right-0 h-3.5 w-[3px] translate-x-1/2 rounded-sm " +
      (ok ? "bg-ok" : "bg-warn");
    if (moveNow) slide.style.transform = `translateX(${pct(v) - 100}%)`;
  }

  const head = el("div", "flex items-baseline justify-between gap-2");
  head.append(el("span", "truncate text-xs text-ink-2", title), readout);
  const node = el("div");
  node.append(head, track);
  slide.style.transform = "translateX(-100%)";
  set(value, false);
  // Два кадра: сначала браузер рисует стартовое положение, потом запускается переход.
  requestAnimationFrame(() => requestAnimationFrame(() => set(value)));
  return { node, set };
}

function plural(n, one, few, many) {
  const last = n % 10;
  if (n % 100 >= 11 && n % 100 <= 14) return many;
  return last === 1 ? one : last >= 2 && last <= 4 ? few : many;
}

function stat(count, text, cls) {
  const item = el("span");
  item.append(el("span", "font-mono font-semibold tabular-nums " + cls, String(count)), " " + text);
  return item;
}

// ---------------------------------------------------------------- переход к предупреждению
function goTo(field) {
  if (field === "input") {
    const target = mode === "json" ? $("input") : $("f-desc");
    scrollToNode(target);
    target.focus({ preventScroll: true });
    highlight(target);
    return;
  }
  if (tab !== "card") {
    tab = "card";
    render();
  }
  const node = document.getElementById("sec-" + field);
  if (!node) return;
  scrollToNode(node);
  highlight(node);
}

function warningItem(text, field) {
  const li = el("li");
  if (!field) {
    li.textContent = text;
    return li;
  }
  const button = el("button", "block text-left underline decoration-warn/40 underline-offset-4 " +
    "hover:decoration-warn focus:outline-none focus-visible:ring-2 focus-visible:ring-accent", text);
  button.type = "button";
  button.title = "Показать место в карточке";
  button.addEventListener("click", () => goTo(field));
  li.append(button);
  return li;
}

// ---------------------------------------------------------------- отрисовка
function labelNode(text) {
  return el("h3", "text-[11px] font-semibold uppercase tracking-widest text-ink-2", text);
}

function section(title, id, body, getText) {
  const box = el("section", "mt-8");
  box.id = "sec-" + id;
  const head = el("div", "mb-2.5 flex items-center justify-between gap-3");
  head.append(labelNode(title));
  if (getText) head.append(copyButton(getText));
  box.append(head, body);
  return box;
}

function renderEmpty() {
  const rows = el("dl", "mt-6 max-w-md");
  FIELDS.forEach(([name, hint]) => {
    const row = el("div", "flex items-baseline gap-2 py-1.5 text-sm");
    row.append(
      el("dt", "flex min-w-0 flex-1 items-baseline gap-2 font-mono text-ink " + LEADER, name),
      el("dd", "text-right text-ink-2", hint),
    );
    rows.append(row);
  });
  $("output").replaceChildren(
    el("p", "text-xl font-semibold tracking-tight", "Карточка появится здесь"),
    el("p", "mt-1 text-sm text-ink-2", "Введите данные слева. Поля запроса:"),
    rows,
  );
}

function renderCard(card) {
  const out = $("output");
  out.replaceChildren();

  const titleRow = el("div", "flex items-start gap-3");
  titleRow.id = "sec-seo_title";
  const titleArea = editable(card.seo_title,
    "max-w-[34ch] text-balance text-2xl font-semibold leading-tight tracking-tight sm:text-[1.75rem]",
    "Заголовок (можно править)",
    (v) => { result.seo_title = v; gauges.title.set(v.length); markEdited(); });
  titleRow.append(titleArea, copyButton(() => result.seo_title));
  out.append(titleRow);
  out.append(el("p", "mt-2 text-xs text-ink-2", "Заголовок и описание можно править прямо здесь."));
  const editState = el("p", "mt-1 min-h-4 text-xs text-ink-2");
  editState.id = "edit-state";
  out.append(editState);
  if (edited) showEditNote();

  gauges = {
    title: meter("Заголовок, до 70", card.seo_title.length, [1, 70], 80),
    desc: meter("Описание, 800–1200", card.seo_description.length, [800, 1200], 1400),
    queries: meter("Запросы, 3–5", card.search_queries.length, [3, 5], 6),
  };
  const strip = el("div", "mt-4 grid gap-x-8 gap-y-5 border-y border-rule py-5 sm:grid-cols-3");
  strip.append(gauges.title.node, gauges.desc.node, gauges.queries.node);
  out.append(strip);

  const gaps = card.characteristics.filter((c) => c.value === NO_DATA).length;
  const missing = card.missing_fields.length;
  const warnings = card.warnings.length;
  const counters = el("p", "mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm text-ink-2");
  counters.append(
    stat(gaps, plural(gaps, "пробел в данных", "пробела в данных", "пробелов в данных"),
      gaps ? "text-gap" : "text-ok"),
    stat(missing, plural(missing, "недостающее поле", "недостающих поля", "недостающих полей"),
      missing ? "text-gap" : "text-ok"),
    stat(warnings, plural(warnings, "предупреждение", "предупреждения", "предупреждений"),
      warnings ? "text-warn" : "text-ok"),
  );
  out.append(counters);

  if (warnings || missing) {
    const box = el("div", "mt-6 border-l-2 border-warn pl-4");
    box.append(el("h3", "text-sm font-semibold", "Требует внимания"));
    if (warnings) {
      const ul = el("ul", "mt-2 list-disc space-y-1.5 pl-5 text-sm text-warn");
      card.warnings.forEach((w, i) => ul.append(warningItem(w, (card.warning_fields || [])[i] || "")));
      box.append(ul);
    }
    if (missing) {
      box.append(el("p", "mt-3 text-sm text-ink-2", "Не хватает данных: " + card.missing_fields.join(" · ")));
    }
    out.append(box);
  }

  const descArea = editable(card.seo_description, "max-w-[68ch] text-[15px] leading-7",
    "SEO-описание (можно править)",
    (v) => { result.seo_description = v; gauges.desc.set(v.length); markEdited(); });
  out.append(section("Описание", "seo_description", descArea, () => result.seo_description));

  const dl = el("dl", "max-w-2xl");
  card.characteristics.forEach((c) => {
    const gap = c.value === NO_DATA;
    const row = el("div", "flex items-baseline gap-2 py-1.5 text-sm");
    row.append(
      el("dt", "flex min-w-0 flex-1 items-baseline gap-2 text-ink-2 " + LEADER, c.name),
      el("dd", "max-w-[60%] break-words text-right font-mono " +
        (gap ? "rounded-sm bg-gap-bg px-1.5 text-gap" : "text-ink"), c.value),
    );
    dl.append(row);
  });
  out.append(section("Характеристики", "characteristics", dl,
    () => result.characteristics.map((c) => `${c.name}: ${c.value}`).join("\n")));

  const queries = el("ul", "flex flex-wrap gap-2");
  card.search_queries.forEach((q) =>
    queries.append(el("li", "rounded-sm border border-rule px-2 py-1 font-mono text-[13px]", q)));
  out.append(section("Поисковые запросы", "search_queries", queries,
    () => result.search_queries.join("\n")));

  const manager = el("div", "max-w-[68ch] space-y-3 text-[15px] leading-7");
  [["Кому подходит", card.commercial.audience], ["Какие задачи решает", card.commercial.tasks]]
    .forEach(([name, text]) => {
      const p = el("p");
      p.append(el("span", "text-ink-2", name + ": "), text);
      manager.append(p);
    });
  out.append(section("Для менеджера", "commercial", manager, () =>
    `Кому подходит: ${result.commercial.audience}\nКакие задачи решает: ${result.commercial.tasks}`));

  out.append(el("p", "mt-10 border-t border-rule pt-3 font-mono text-[11px] text-ink-2",
    `промпт v${card.meta.prompt_version} · ${card.meta.model}`));
  reveal(out);
}

// Скелетон на время генерации: показывает, что идёт работа и какой формы будет результат.
function renderSkeleton() {
  const bar = (cls) => el("div", "rounded-sm bg-rule motion-safe:animate-pulse " + cls);
  const meters = el("div", "mt-6 grid gap-5 border-y border-rule py-5 sm:grid-cols-3");
  meters.append(bar("h-6"), bar("h-6"), bar("h-6"));
  const lines = el("div", "mt-8 space-y-3");
  lines.append(bar("h-4 w-full"), bar("h-4 w-11/12"), bar("h-4 w-4/5"), bar("h-4 w-full"), bar("h-4 w-2/3"));
  const out = $("output");
  out.replaceChildren(bar("h-8 w-3/5"), meters, lines);
  out.setAttribute("aria-busy", "true");
}

function renderPre(text) {
  $("output").replaceChildren(
    el("pre", "animate-fade whitespace-pre-wrap break-words rounded-md border border-rule bg-paper " +
      "p-4 font-mono text-[12.5px] leading-6", text));
}

function render() {
  document.querySelectorAll(".tab").forEach((b) => {
    const selected = b.dataset.tab === tab;
    b.setAttribute("aria-selected", String(selected));
    b.tabIndex = selected ? 0 : -1;
  });
  $("output").setAttribute("aria-labelledby", "tab-" + tab);
  $("output").removeAttribute("aria-busy");
  $("copy").disabled = !result;
  $("download").disabled = !result;
  if (!result) return renderEmpty();
  if (tab === "card") renderCard(result);
  else if (tab === "markdown") renderPre(result.markdown);
  else renderPre(JSON.stringify(result, null, 2));
}

function hideError() {
  $("error").hidden = true;
}

function showError(message, details = []) {
  const box = $("error");
  box.replaceChildren(el("p", "font-medium", message));
  if (details.length) box.append(list(details, "mt-1"));
  box.hidden = false;
  flash(box);
}

function setBusy(busy) {
  $("run").disabled = busy;
  $("run").textContent = busy ? "Генерируем…" : "Сгенерировать карточку";
  $("progress").hidden = !busy;
}

// На телефоне результат ниже поля ввода: после запуска подводим к нему экран.
function bringOutputIntoView() {
  const top = $("output").getBoundingClientRect().top;
  if (top > window.innerHeight * 0.7) scrollToNode($("output"), "start");
}

// ---------------------------------------------------------------- генерация
async function generate() {
  if ($("run").disabled) return;
  hideError();
  // Старая карточка не должна оставаться на экране (и доступной для копирования), если
  // новый запрос не удался: иначе её легко скопировать в карточку другого товара.
  cancelPendingRender();
  result = null;
  original = null;
  edited = false;
  render();
  const built = buildPayload();
  if (!built.payload) {
    showError(built.message, built.details);
    return;
  }
  setBusy(true);
  renderSkeleton();
  bringOutputIntoView();
  setStatus("Генерируем карточку…");
  let resp, data;
  try {
    resp = await fetch("/api/cards", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(built.payload),
    });
    data = await resp.json().catch(() => null);
  } catch {
    setBusy(false);
    render();
    setStatus("");
    showError("Нет связи с сервисом. Проверьте, что он запущен.");
    return;
  }
  setBusy(false);
  setStatus("");
  if (!resp.ok) {
    render();
    showError((data && data.message) || "Не удалось получить ответ сервиса.", (data && data.details) || []);
    return;
  }
  if (!data || typeof data.seo_title !== "string") {
    render();
    showError("Сервис вернул неожиданный ответ. Повторите запрос.");
    return;
  }
  result = data;
  original = structuredClone(data);
  edited = false;
  try {
    render();
    setStatus("Готово. Проверьте предупреждения перед публикацией.");
    $("output").focus({ preventScroll: true }); // экранные читалки начинают с результата
  } catch {
    result = null;
    render();
    showError("Не удалось отобразить ответ сервиса.");
  }
}

// ---------------------------------------------------------------- навигация вкладками
// Стрелки, Home и End переключают вкладки (шаблон WAI-ARIA tabs).
function bindTabKeys(tablist, ids, current, select) {
  tablist.addEventListener("keydown", (e) => {
    const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
    const target = e.key === "Home" ? 0 : e.key === "End" ? ids.length - 1
      : step ? (ids.indexOf(current()) + step + ids.length) % ids.length : -1;
    if (target < 0) return;
    e.preventDefault();
    select(ids[target]);
  });
}

// ---------------------------------------------------------------- события
$("example").addEventListener("click", () => setPayload(EXAMPLE));
$("clear").addEventListener("click", clearAll);
$("load").addEventListener("click", () => $("file").click());
$("file").addEventListener("change", () => {
  loadFile($("file").files[0]);
  $("file").value = ""; // чтобы тот же файл можно было выбрать повторно
});
$("input").addEventListener("input", () => { checkJson(); scheduleSave(); });
$("form-panel").addEventListener("input", scheduleSave);
$("f-add").addEventListener("click", () => {
  const row = specRow();
  $("f-specs").append(row);
  row.querySelector("input").focus();
});
$("run").addEventListener("click", generate);
$("input-pane").addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    generate();
  }
});
$("copy").addEventListener("click", () => {
  if (result) copyText(currentExport().text, $("copy"), { fresh: true });
});
$("download").addEventListener("click", download);
document.querySelectorAll(".tab").forEach((b) =>
  b.addEventListener("click", () => { tab = b.dataset.tab; render(); }));
document.querySelectorAll(".mode").forEach((b) =>
  b.addEventListener("click", () => setMode(b.dataset.mode)));
bindTabKeys($("tab-card").parentElement, TABS, () => tab, (id) => {
  tab = id;
  render();
  $("tab-" + id).focus();
});
bindTabKeys($("mode-json").parentElement, MODES, () => mode, (id) => {
  setMode(id);
  $("mode-" + mode).focus();
});

// Перетаскивание .json на левую панель.
const pane = $("input-pane");
const DROP_CLS = ["ring-2", "ring-accent", "ring-inset"];
["dragenter", "dragover"].forEach((type) => pane.addEventListener(type, (e) => {
  if (![...(e.dataTransfer?.types || [])].includes("Files")) return;
  e.preventDefault();
  pane.classList.add(...DROP_CLS);
}));
["dragleave", "drop"].forEach((type) => pane.addEventListener(type, (e) => {
  if (type === "dragleave" && pane.contains(e.relatedTarget)) return;
  pane.classList.remove(...DROP_CLS);
}));
pane.addEventListener("drop", (e) => {
  if (!e.dataTransfer?.files?.length) return;
  e.preventDefault();
  loadFile(e.dataTransfer.files[0]);
});

// ---------------------------------------------------------------- старт
(function init() {
  const saved = readStore();
  fillForm({});
  if (saved && typeof saved === "object") {
    if (typeof saved.json === "string") $("input").value = saved.json;
    if (saved.form && typeof saved.form === "object") fillForm(saved.form);
    if (MODES.includes(saved.mode)) mode = saved.mode;
  }
  applyMode();
  checkJson();
  render();
})();
