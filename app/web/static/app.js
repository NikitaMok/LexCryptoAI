function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const form = document.getElementById("check-form");
const pdfBtn = document.getElementById("pdf-btn");
const errorBox = document.getElementById("error");
const resultBox = document.getElementById("result");
const searchForm = document.getElementById("search-form");
const searchResult = document.getElementById("search-result");
const busy = document.getElementById("busy");

let lastFile = null;

function showError(message) {
  errorBox.hidden = false;
  errorBox.textContent = message;
}

function clearError() {
  errorBox.hidden = true;
  errorBox.textContent = "";
}

function paramsFromForm() {
  const data = new FormData(form);
  const query = new URLSearchParams();
  query.set("on", data.get("on"));
  if (data.get("quote_norms")) query.set("quote_norms", "true");
  return query;
}

function findingsHtml(title, items) {
  if (!items || !items.length) return "";
  const blocks = items.map((item) => {
    const clauses = item.clauses && item.clauses.length
      ? `<p>пункты договора: ${esc(item.clauses.join(", "))}</p>`
      : "";
    const norms = item.norms && item.norms.length
      ? `<p>норма: ${esc(item.norms.join("; "))}</p>`
      : "";
    const evidence = item.evidence ? `<p>${esc(item.evidence)}</p>` : "";
    const rec = item.recommendation ? `<p>редакция: ${esc(item.recommendation)}</p>` : "";
    return `<article class="finding"><p><strong>[${esc(item.code)}]</strong> ${esc(item.title)}</p>${evidence}${clauses}${norms}${rec}</article>`;
  });
  return `<h2>${title}</h2>${blocks.join("")}`;
}

function walletHtml(scores) {
  if (!scores || !scores.length) {
    return `<h2>2. Кошелёк</h2><p>В тексте нет адреса. Оценка по открытым данным не выполнялась.</p>`;
  }
  const blocks = scores.map((item) => {
    const factors = (item.factors || []).map((factor) => `<p>${esc(factor)}</p>`).join("");
    const labels = (item.labels || []).map((label) => `<p>метка: ${esc(label)}</p>`).join("");
    const notes = (item.source_notes || []).map((note) => `<p>${esc(note)}</p>`).join("");
    const err = item.error ? `<p>${esc(item.error)}</p>` : "";
    const score = item.score != null ? `, оценка ${esc(item.score)}` : "";
    return `<article class="finding"><p>${esc(item.address)} (${esc(item.network)}): ${esc(item.band)}${score}</p>${factors}${labels}${notes}${err}<p>${esc(item.disclaimer || "")}</p></article>`;
  }).join("");
  return `<h2>2. Кошелёк</h2>${blocks}`;
}

function partyHtml(parties) {
  if (!parties || !parties.length) {
    return `<h2>3. Контрагент</h2><p>сверка не выполнена</p>`;
  }
  const blocks = parties.map((item) => {
    const who = esc(item.name || item.inn || "сторона не названа");
    const inn = item.inn ? `<p>ИНН ${esc(item.inn)}</p>` : "";
    const hits = (item.hits || []).map((hit) => `<p>${esc(hit.detail || hit.source)}</p>`).join("");
    return `<article class="finding"><p>${who}</p>${inn}<p>${esc(item.summary || "")}</p>${hits}</article>`;
  }).join("");
  return `<h2>3. Контрагент</h2>${blocks}`;
}

function llmHtml(llm) {
  if (!llm) return "";
  const notes = (llm.notes || []).map((note) => {
    const mark = note.present === true ? "есть в тексте" : note.present === false ? "в тексте не видно" : "не ясно";
    const quote = note.quote ? `<p>цитата: ${esc(note.quote)}</p>` : "";
    const reading = note.reading ? `<p>${esc(note.reading)}</p>` : "";
    return `<article class="finding"><p>[${esc(note.code)}] ${esc(mark)}</p>${quote}${reading}</article>`;
  }).join("");
  const model = llm.model ? `<p>модель: ${esc(llm.model)}</p>` : "";
  return `<h2>Оговорки, которые формальная проверка не ловит</h2><p>${esc(llm.detail || "")}</p>${model}${notes}`;
}

function renderReport(payload) {
  resultBox.hidden = false;
  resultBox.innerHTML = `
    <p class="status ${esc(payload.status)}">${esc(payload.status_label)}</p>
    <p>Документ: ${esc(payload.source)}. Проверено на дату: ${esc(payload.checked_on)}.</p>
    <p>Итого правил: ${payload.counts.total}. Выполнено: ${payload.counts.passed}.
       Нарушено: ${payload.counts.failed}. На ручной оценке: ${payload.counts.manual}.</p>
    <h2>1. Договор</h2>
    ${findingsHtml("Нарушены обязательные требования", payload.blocking)}
    ${findingsHtml("Замечания", payload.advisory)}
    ${findingsHtml("Нормы, вступающие в силу позднее", payload.deferred)}
    ${findingsHtml("Требует оценки юриста", payload.manual)}
    ${llmHtml(payload.llm)}
    ${walletHtml(payload.address_scores)}
    ${partyHtml(payload.counterparties)}
  `;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearError();
  const data = new FormData(form);
  const file = data.get("file");
  if (!(file instanceof File) || !file.size) {
    showError("выберите файл контракта");
    return;
  }
  lastFile = file;
  pdfBtn.disabled = true;
  resultBox.hidden = true;
  busy.hidden = false;

  const body = new FormData();
  body.append("file", file, file.name);

  try {
    const response = await fetch(`/check?${paramsFromForm().toString()}`, {
      method: "POST",
      body,
    });
    const payload = await response.json();
    if (!response.ok) {
      showError(payload.detail || "проверка не выполнена");
      return;
    }
    renderReport(payload);
    pdfBtn.disabled = false;
  } catch (error) {
    showError("нет связи с сервером");
  } finally {
    busy.hidden = true;
  }
});

pdfBtn.addEventListener("click", async () => {
  if (!lastFile) return;
  clearError();
  busy.hidden = false;
  const body = new FormData();
  body.append("file", lastFile, lastFile.name);
  try {
    const response = await fetch(`/check/pdf?${paramsFromForm().toString()}`, {
      method: "POST",
      body,
    });
    if (!response.ok) {
      showError("PDF не сформирован");
      return;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "zaklyuchenie.pdf";
    link.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    showError("нет связи с сервером");
  } finally {
    busy.hidden = true;
  }
});

searchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = new FormData(searchForm).get("q");
  searchResult.textContent = "";
  try {
    const response = await fetch(`/search?q=${encodeURIComponent(query)}`);
    const payload = await response.json();
    if (!response.ok) {
      searchResult.textContent = payload.detail || "поиск не выполнен";
      return;
    }
    if (!payload.hits.length) {
      searchResult.textContent = "Ничего не найдено.";
      return;
    }
    searchResult.innerHTML = payload.hits.map(
      (hit) => `<article class="search-hit"><p>${esc(hit.ref)}</p><p>${esc(hit.text)}</p></article>`
    ).join("");
  } catch (error) {
    searchResult.textContent = "нет связи с сервером";
  }
});
