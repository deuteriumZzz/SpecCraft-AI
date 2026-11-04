// Фронтенд без фреймворка. Весь вывод идёт через textContent: ответ модели считается
// недоверенным, innerHTML не используется нигде (защита от stored XSS). Позиции на шкалах
// задаются через CSSOM (element.style), это не inline-стили в разметке и CSP не нарушает.
"use strict";

const $ = (id) => document.getElementById(id);
const NO_DATA = "данных нет";
const TABS = ["card", "markdown", "json"];
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

let result = null;
let tab = "card";
let copyTimer = null;

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function label(text) {
  return el("h3", "mb-2.5 text-[11px] font-semibold uppercase tracking-widest text-ink-2", text);
}

function section(title, ...children) {
  const box = el("section", "mt-8");
  box.append(label(title), ...children);
  return box;
}

function list(items, cls) {
  const ul = el("ul", "list-disc space-y-1 pl-5 " + cls);
  items.forEach((t) => ul.append(el("li", "", t)));
  return ul;
}

// Шкала-измеритель: стрелка показывает значение, зелёная полоса — допустимый диапазон.
function meter(title, value, [lo, hi], scaleMax, valueText) {
  const ok = value >= lo && value <= hi;
  const pct = (v) => Math.max(0, Math.min(100, (v / scaleMax) * 100));
  const head = el("div", "flex items-baseline justify-between gap-2");
  head.append(
    el("span", "truncate text-xs text-ink-2", title),
    el("span", "shrink-0 whitespace-nowrap font-mono text-xs tabular-nums " + (ok ? "text-ok" : "text-warn"),
      `${valueText} · ${ok ? "норма" : "вне нормы"}`),
  );
  const track = el("div", "relative mt-2.5 h-1.5 rounded-full bg-rule");
  const band = el("div", "absolute inset-y-0 rounded-full bg-ok/35");
  band.style.left = pct(lo) + "%";
  band.style.width = pct(hi) - pct(lo) + "%";
  const mark = el("div",
    "absolute -top-1 h-3.5 w-[3px] -translate-x-1/2 rounded-sm " + (ok ? "bg-ok" : "bg-warn"));
  mark.style.left = pct(value) + "%";
  track.append(band, mark);
  const box = el("div");
  box.append(head, track);
  return box;
}

// Русское склонение: 1 пробел, 2–4 пробела, 5–20 и 11–14 пробелов.
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

function renderEmpty() {
  const rows = el("dl", "mt-6 max-w-md");
  FIELDS.forEach(([name, hint]) => {
    const row = el("div", "flex items-baseline gap-2 py-1.5 text-sm");
    row.append(
      el("dt", "font-mono text-ink", name),
      el("span", "min-w-4 flex-1 -translate-y-0.5 border-b border-dotted border-rule"),
      el("dd", "text-right text-ink-2", hint),
    );
    rows.append(row);
  });
  $("output").replaceChildren(
    el("p", "text-xl font-semibold tracking-tight", "Карточка появится здесь"),
    el("p", "mt-1 text-sm text-ink-2", "Вставьте JSON слева. Поля запроса:"),
    rows,
  );
}

function renderCard(card) {
  const out = $("output");
  out.replaceChildren();
  out.append(el("h3",
    "max-w-[34ch] text-balance text-2xl font-semibold leading-tight tracking-tight sm:text-[1.75rem]",
    card.seo_title));

  const strip = el("div", "mt-6 grid gap-x-8 gap-y-5 border-y border-rule py-5 sm:grid-cols-3");
  strip.append(
    meter("Заголовок, до 70", card.seo_title.length, [1, 70], 80, String(card.seo_title.length)),
    meter("Описание, 800–1200", card.seo_description.length, [800, 1200], 1400,
      String(card.seo_description.length)),
    meter("Запросы, 3–5", card.search_queries.length, [3, 5], 6, String(card.search_queries.length)),
  );
  out.append(strip);

  const gaps = card.characteristics.filter((c) => c.value === NO_DATA).length;
  const counters = el("p", "mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm text-ink-2");
  const missing = card.missing_fields.length;
  const warnings = card.warnings.length;
  counters.append(
    stat(gaps, plural(gaps, "пробел в данных", "пробела в данных", "пробелов в данных"),
      gaps ? "text-gap" : "text-ok"),
    stat(missing, plural(missing, "недостающее поле", "недостающих поля", "недостающих полей"),
      missing ? "text-gap" : "text-ok"),
    stat(warnings, plural(warnings, "предупреждение", "предупреждения", "предупреждений"),
      warnings ? "text-warn" : "text-ok"),
  );
  out.append(counters);

  if (card.warnings.length || card.missing_fields.length) {
    const box = el("div", "mt-6 border-l-2 border-warn pl-4");
    box.append(el("h3", "text-sm font-semibold", "Требует внимания"));
    if (card.warnings.length) box.append(list(card.warnings, "mt-2 text-sm text-warn"));
    if (card.missing_fields.length) {
      box.append(el("p", "mt-3 text-sm text-ink-2", "Не хватает данных: " + card.missing_fields.join(" · ")));
    }
    out.append(box);
  }

  out.append(section("Описание", el("p", "max-w-[68ch] text-[15px] leading-7", card.seo_description)));

  const dl = el("dl", "max-w-2xl");
  card.characteristics.forEach((c) => {
    const gap = c.value === NO_DATA;
    const row = el("div", "flex items-baseline gap-2 py-1.5 text-sm");
    row.append(
      el("dt", "text-ink-2", c.name),
      el("span", "min-w-4 flex-1 -translate-y-0.5 border-b border-dotted border-rule"),
      el("dd", "ml-auto max-w-[60%] break-words text-right font-mono " +
        (gap ? "rounded-sm bg-gap-bg px-1.5 text-gap" : "text-ink"), c.value),
    );
    dl.append(row);
  });
  out.append(section("Характеристики", dl));

  const queries = el("ul", "flex flex-wrap gap-2");
  card.search_queries.forEach((q) =>
    queries.append(el("li", "rounded-sm border border-rule px-2 py-1 font-mono text-[13px]", q)));
  out.append(section("Поисковые запросы", queries));

  const manager = el("div", "max-w-[68ch] space-y-3 text-[15px] leading-7");
  [["Кому подходит", card.commercial.audience], ["Какие задачи решает", card.commercial.tasks]]
    .forEach(([name, text]) => {
      const p = el("p");
      p.append(el("span", "text-ink-2", name + ": "), text);
      manager.append(p);
    });
  out.append(section("Для менеджера", manager));

  out.append(el("p", "mt-10 border-t border-rule pt-3 font-mono text-[11px] text-ink-2",
    `промпт v${card.meta.prompt_version} · ${card.meta.model}`));
}

function renderPre(text) {
  $("output").replaceChildren(
    el("pre", "whitespace-pre-wrap break-words rounded-md border border-rule bg-paper p-4 " +
      "font-mono text-[12.5px] leading-6", text));
}

function render() {
  document.querySelectorAll(".tab").forEach((b) => {
    const selected = b.dataset.tab === tab;
    b.setAttribute("aria-selected", String(selected));
    b.tabIndex = selected ? 0 : -1;
  });
  $("output").setAttribute("aria-labelledby", "tab-" + tab);
  $("copy").disabled = !result;
  if (!result) return renderEmpty();
  if (tab === "card") renderCard(result);
  else if (tab === "markdown") renderPre(result.markdown);
  else renderPre(JSON.stringify(result, null, 2));
}

function showError(message, details = []) {
  const box = $("error");
  box.replaceChildren(el("p", "font-medium", message));
  if (details.length) box.append(list(details, "mt-1"));
  box.hidden = false;
}

function setBusy(busy) {
  $("run").disabled = busy;
  $("run").textContent = busy ? "Генерируем…" : "Сгенерировать карточку";
  $("progress").hidden = !busy;
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

async function generate() {
  if ($("run").disabled) return;
  $("error").hidden = true;
  // Старая карточка не должна оставаться на экране (и доступной для копирования), если
  // новый запрос не удался: иначе её легко скопировать в карточку другого товара.
  result = null;
  render();
  let payload;
  try {
    payload = JSON.parse($("input").value);
  } catch {
    // Текст ошибки браузера английский и бесполезен менеджеру: даём типовую подсказку.
    showError("Введённый текст не является корректным JSON.",
      ["Проверьте скобки, кавычки вокруг названий и значений и запятые между полями."]);
    return;
  }
  setBusy(true);
  $("status").textContent = "Генерируем карточку…";
  let resp, data;
  try {
    resp = await fetch("/api/cards", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    data = await resp.json().catch(() => null);
  } catch {
    setBusy(false);
    $("status").textContent = "";
    showError("Нет связи с сервисом. Проверьте, что он запущен.");
    return;
  }
  setBusy(false);
  $("status").textContent = "";
  if (!resp.ok) {
    showError((data && data.message) || "Не удалось получить ответ сервиса.", (data && data.details) || []);
    return;
  }
  if (!data || typeof data.seo_title !== "string") {
    showError("Сервис вернул неожиданный ответ. Повторите запрос.");
    return;
  }
  result = data;
  try {
    render();
    $("status").textContent = "Готово. Проверьте предупреждения перед публикацией.";
  } catch {
    result = null;
    render();
    showError("Не удалось отобразить ответ сервиса.");
  }
}

function copyCurrent() {
  if (!result) return;
  const text = tab === "markdown" ? result.markdown
    : tab === "json" ? JSON.stringify(result, null, 2) : result.text;
  navigator.clipboard.writeText(text).then(() => {
    $("copy").textContent = "Скопировано";
    $("status").textContent = "Скопировано в буфер обмена.";
    clearTimeout(copyTimer);
    copyTimer = setTimeout(() => { $("copy").textContent = "Копировать"; }, 1500);
  }, () => {
    $("status").textContent = "Не удалось скопировать: выделите текст вручную.";
  });
}

$("example").addEventListener("click", () => {
  $("input").value = JSON.stringify(EXAMPLE, null, 2);
  checkJson();
});
$("input").addEventListener("input", checkJson);
$("input").addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    generate();
  }
});
$("run").addEventListener("click", generate);
$("copy").addEventListener("click", copyCurrent);
document.querySelectorAll(".tab").forEach((b) =>
  b.addEventListener("click", () => { tab = b.dataset.tab; render(); }));
// Стрелки, Home и End переключают вкладки (шаблон WAI-ARIA tabs).
$("tab-card").parentElement.addEventListener("keydown", (e) => {
  const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
  const target = e.key === "Home" ? 0 : e.key === "End" ? TABS.length - 1
    : step ? (TABS.indexOf(tab) + step + TABS.length) % TABS.length : -1;
  if (target < 0) return;
  e.preventDefault();
  tab = TABS[target];
  render();
  $("tab-" + tab).focus();
});

render();
