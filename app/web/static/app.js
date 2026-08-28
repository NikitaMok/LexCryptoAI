const form = document.getElementById("check-form");
const pdfBtn = document.getElementById("pdf-btn");
const errorBox = document.getElementById("error");
const resultBox = document.getElementById("result");
const searchForm = document.getElementById("search-form");
const searchResult = document.getElementById("search-result");

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
  if (data.get("aml")) query.set("aml", "true");
  return query;
}

function findingsHtml(title, items) {
  if (!items || !items.length) return "";
  const blocks = items.map((item) => {
    const clauses = item.clauses && item.clauses.length
      ? `<p>пункты договора: ${item.clauses.join(", ")}</p>`
      : "";
    const norms = item.norms && item.norms.length
      ? `<p>норма: ${item.norms.join("; ")}</p>`
      : "";
    const evidence = item.evidence ? `<p>${item.evidence}</p>` : "";
    const rec = item.recommendation ? `<p>как исправить: ${item.recommendation}</p>` : "";
    return `<article class="finding"><p><strong>[${item.code}]</strong> ${item.title}</p>${evidence}${clauses}${norms}${rec}</article>`;
  });
  return `<h2>${title}</h2>${blocks.join("")}`;
}

function renderReport(payload) {
  const scores = (payload.address_scores || []).map((item) => {
    const factors = (item.factors || []).map((factor) => `<p>${factor}</p>`).join("");
    const err = item.error ? `<p>${item.error}</p>` : "";
    const score = item.score != null ? `, оценка ${item.score}` : "";
    return `<article class="finding"><p>${item.address} (${item.network}): ${item.band}${score}</p>${factors}${err}<p>${item.disclaimer || ""}</p></article>`;
  }).join("");

  resultBox.hidden = false;
  resultBox.innerHTML = `
    <p class="status ${payload.status}">${payload.status_label}</p>
    <p>Документ: ${payload.source}. Проверено на дату: ${payload.checked_on}.</p>
    <p>Итого правил: ${payload.counts.total}. Выполнено: ${payload.counts.passed}.
       Нарушено: ${payload.counts.failed}. На ручной оценке: ${payload.counts.manual}.</p>
    ${findingsHtml("Нарушены обязательные требования", payload.blocking)}
    ${findingsHtml("Замечания", payload.advisory)}
    ${findingsHtml("Нормы, вступающие в силу позднее", payload.deferred)}
    ${findingsHtml("Требует оценки юриста", payload.manual)}
    ${scores ? `<h2>Адреса по открытым данным</h2>${scores}` : ""}
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
  }
});

pdfBtn.addEventListener("click", async () => {
  if (!lastFile) return;
  clearError();
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
      (hit) => `<article class="search-hit"><p>${hit.ref}</p><p>${hit.text}</p></article>`
    ).join("");
  } catch (error) {
    searchResult.textContent = "нет связи с сервером";
  }
});
