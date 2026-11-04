// Фронтенд без фреймворка. Весь вывод идёт через textContent: ответ модели считается
// недоверенным, innerHTML не используется нигде (защита от stored XSS).
"use strict";

const $ = (id) => document.getElementById(id);
const EXAMPLE = {
  name: "Манометр технический МТ-100",
  manufacturer: "Приборзавод Тест",
  specs: { "диапазон измерений": "0–1,6 МПа", "класс точности": "1,5", "присоединение": "G1/2" },
  description: "Прибор предназначен для измерения избыточного давления жидкостей и газов.",
};

let result = null;
let tab = "card";

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function section(title, ...children) {
  const box = el("section", "mt-4 first:mt-0");
  box.append(el("h3", "mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500", title), ...children);
  return box;
}

function list(items, cls = "") {
  const ul = el("ul", "list-disc space-y-0.5 pl-5 " + cls);
  items.forEach((t) => ul.append(el("li", "", t)));
  return ul;
}

function renderCard(card) {
  const out = $("output");
  out.replaceChildren();
  out.append(el("h3", "text-lg font-semibold", card.seo_title));
  out.append(el("p", "mt-1 text-xs text-slate-500", `${card.seo_title.length}/70 символов в заголовке`));
  out.append(section("SEO-описание", el("p", "leading-relaxed", card.seo_description),
    el("p", "mt-1 text-xs text-slate-500", `${card.seo_description.length} символов (норма 800–1200)`)));

  const table = el("table", "w-full text-left");
  card.characteristics.forEach((c) => {
    const row = el("tr", "border-t border-slate-200 dark:border-slate-800");
    const missing = c.value === "данных нет";
    row.append(el("th", "w-1/2 py-1.5 pr-3 font-normal text-slate-600 dark:text-slate-400", c.name),
      el("td", missing ? "py-1.5 text-amber-700 dark:text-amber-400" : "py-1.5", c.value));
    table.append(row);
  });
  out.append(section("Характеристики", table));
  out.append(section("Поисковые запросы", list(card.search_queries)));
  out.append(section("Для менеджера",
    el("p", "", "Кому подходит: " + card.commercial.audience),
    el("p", "mt-1", "Задачи: " + card.commercial.tasks)));
  if (card.missing_fields.length) {
    out.append(section("Не хватает данных", list(card.missing_fields, "text-amber-800 dark:text-amber-300")));
  }
  if (card.warnings.length) {
    out.append(section("Предупреждения", list(card.warnings, "text-red-700 dark:text-red-300")));
  }
}

function renderPre(text) {
  const out = $("output");
  out.replaceChildren(el("pre", "whitespace-pre-wrap break-words font-mono text-xs", text));
}

function render() {
  document.querySelectorAll(".tab").forEach((b) =>
    b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
  $("copy").disabled = !result;
  if (!result) {
    $("output").replaceChildren(el("p", "text-slate-500", "Здесь появится карточка товара."));
    return;
  }
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

async function generate() {
  $("error").hidden = true;
  // Старая карточка не должна оставаться на экране (и доступной для копирования), если
  // новый запрос не удался: иначе её легко скопировать в карточку другого товара.
  result = null;
  render();
  let payload;
  try {
    payload = JSON.parse($("input").value);
  } catch (e) {
    showError("Введённый текст не является корректным JSON.", [String(e.message).slice(0, 200)]);
    return;
  }
  $("run").disabled = true;
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
    showError("Нет связи с сервисом. Проверьте, что он запущен.");
    $("status").textContent = "";
    $("run").disabled = false;
    return;
  }
  $("run").disabled = false;
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

$("example").addEventListener("click", () => {
  $("input").value = JSON.stringify(EXAMPLE, null, 2);
});
$("run").addEventListener("click", generate);
document.querySelectorAll(".tab").forEach((b) =>
  b.addEventListener("click", () => { tab = b.dataset.tab; render(); }));
$("copy").addEventListener("click", async () => {
  if (!result) return;
  const text = tab === "markdown" ? result.markdown
    : tab === "json" ? JSON.stringify(result, null, 2) : result.text;
  try {
    await navigator.clipboard.writeText(text);
    $("status").textContent = "Скопировано.";
  } catch {
    $("status").textContent = "Не удалось скопировать: выделите текст вручную.";
  }
});
