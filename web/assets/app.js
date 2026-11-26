"use strict";
const $ = (id) => document.getElementById(id);
const ACCENT = "#b62b6e",
  NEUTRAL = "#858087",
  DARK = "#454149";
const SECTIONS = {
  overview: [
    "Анализ данных",
    "Анализ данных",
    "Динамика нагрузки, сезонность и аналитические выводы.",
  ],
  forecast: [
    "Прогноз",
    "Прогноз нагрузки",
    "Ожидаемая динамика, фактические значения и неопределённость.",
  ],
  quality: [
    "Качество данных",
    "Качество данных",
    "Полнота измерений, контроль значений и история загрузок.",
  ],
  backtest: [
    "Проверка моделей",
    "Проверка моделей",
    "Сравнение моделей на последовательных временных окнах.",
  ],
  scenarios: [
    "Сценарии",
    "Температурные сценарии",
    "Как меняется прогноз при изменении погодного индикатора.",
  ],
};
let D = null,
  lastVersion = null,
  activeTab = "overview",
  resizeTimer,
  scenarioRequest = 0;
let lastScenario = null,
  lastScenarioDelta = null;
const esc = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const fmt = (v, n = 0) =>
  v === null || !Number.isFinite(Number(v))
    ? "—"
    : Number(v).toLocaleString("ru-RU", { maximumFractionDigits: n });
const date = (s) =>
  new Date(s).toLocaleString("ru-RU", {
    timeZone: "UTC",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
const shortDate = (s) =>
  new Date(s).toLocaleDateString("ru-RU", {
    timeZone: "UTC",
    day: "2-digit",
    month: "short",
    year: "numeric",
  });

function table(
  headers,
  rows,
  { numeric = [], timeColumn = false, rowKeys = null, selected = null } = {},
) {
  return `<table><thead><tr>${headers.map((h, i) => `<th scope="col"${numeric.includes(i) ? ' class="numeric"' : ""}>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((row, r) => `<tr${rowKeys && rowKeys[r] === selected ? ' class="selected-model"' : ""}>${row.map((value, c) => `<td${numeric.includes(c) ? ' class="numeric"' : c === 0 && timeColumn ? ' class="time"' : ""}>${esc(value)}${c === 0 && rowKeys && rowKeys[r] === selected ? '<span class="model-chosen">выбрана</span>' : ""}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

function chart(id, inputSets, { band = null, time = true, unit = "МВт" } = {}) {
  const el = $(id);
  const sets = inputSets
    .map((s) => ({
      ...s,
      data: s.data.filter(
        (p) => Number.isFinite(p[1]) && Number.isFinite(+p[0]),
      ),
    }))
    .filter((s) => s.data.length);
  if (!sets.length) {
    el.innerHTML =
      '<div class="panel-footnote">Нет данных за выбранный период.</div>';
    return;
  }
  const W =
    Math.max(320, el.clientWidth - (window.innerWidth < 760 ? 16 : 36)) || 900;
  const H = Number(el.dataset.height || 270),
    L = unit === "r" ? 43 : 58,
    R = 13,
    T = 16,
    B = 36;
  const points = sets.flatMap((s) => s.data),
    xs = points.map((p) => +p[0]),
    ys = points.map((p) => p[1]);
  if (band) band.forEach((p) => ys.push(p[1], p[2]));
  const xmin = Math.min(...xs),
    xmax = Math.max(...xs),
    spanx = xmax - xmin || 1;
  const rawMin = Math.min(...ys),
    rawMax = Math.max(...ys),
    pad = (rawMax - rawMin) * 0.1 || 1;
  const rough = (rawMax - rawMin + 2 * pad) / 4,
    order = 10 ** Math.floor(Math.log10(rough));
  const step =
    ([1, 2, 2.5, 5, 10].find((n) => n * order >= rough) || 10) * order;
  const ymin = Math.floor((rawMin - pad) / step) * step,
    ymax = Math.ceil((rawMax + pad) / step) * step;
  const X = (x) => L + ((x - xmin) / spanx) * (W - L - R),
    Y = (y) => H - B - ((y - ymin) / (ymax - ymin)) * (H - T - B);
  let svg = "";
  for (let v = ymin; v <= ymax + step / 100; v += step) {
    svg += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="#ebe7ea" stroke-dasharray="3 4"/><text x="${L - 11}" y="${Y(v) + 4}" text-anchor="end" font-size="12">${fmt(v, unit === "r" ? 1 : 0)}</text>`;
  }
  const ticks = W < 460 ? 4 : 5;
  for (let i = 0; i < ticks; i++) {
    const x = xmin + (spanx * i) / (ticks - 1);
    const label = time
      ? new Date(x).toLocaleString("ru-RU", {
          timeZone: "UTC",
          day: "2-digit",
          month: "2-digit",
          ...(spanx < 172800000 ? { hour: "2-digit" } : {}),
        })
      : fmt(x);
    svg += `<text x="${X(x)}" y="${H - 10}" text-anchor="${i === ticks - 1 ? "end" : i === 0 ? "start" : "middle"}" font-size="12">${esc(label)}</text>`;
  }
  if (band && band.length) {
    const top = band.map((p) => `${X(+p[0])},${Y(p[2])}`),
      bottom = [...band].reverse().map((p) => `${X(+p[0])},${Y(p[1])}`);
    svg += `<polygon points="${top.concat(bottom).join(" ")}" fill="#fae5ee"/>`;
  }
  for (const s of sets) {
    const path = s.data
      .map((p, i) => `${i ? "L" : "M"}${X(+p[0])},${Y(p[1])}`)
      .join(" ");
    svg += `<path d="${path}" fill="none" stroke="${s.color}" stroke-width="${s.color === ACCENT ? 2 : 1.6}" stroke-linejoin="round" stroke-linecap="round"${s.dash ? ' stroke-dasharray="4 4"' : ""}/>`;
  }
  svg += `<line class="crosshair" x1="0" x2="0" y1="${T}" y2="${H - B}" stroke="#ad8b9b" stroke-dasharray="3 4" visibility="hidden"/>`;
  el.innerHTML = `<div class="chart-meta"><div class="legend">${sets.map((s) => `<span><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join("")}${band ? '<span><i style="height:8px;background:#fae5ee;border:1px solid #dbafc2;border-radius:2px"></i>90% интервал</span>' : ""}</div><span class="chart-unit">${esc(unit)}</span></div><div class="plot-wrap"><svg style="height:${H}px" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(sets.map((s) => s.name).join(", "))}" preserveAspectRatio="none">${svg}</svg><div class="tip" hidden></div></div>`;
  const plot = el.querySelector(".plot-wrap"),
    tip = el.querySelector(".tip"),
    cross = el.querySelector(".crosshair");
  plot.onpointermove = (e) => {
    const rect = plot.getBoundingClientRect(),
      px = ((e.clientX - rect.left) / rect.width) * W;
    if (px < L || px > W - R) {
      tip.hidden = true;
      cross.setAttribute("visibility", "hidden");
      return;
    }
    const q = xmin + ((px - L) / (W - L - R)) * spanx;
    const values = sets
      .filter(
        (s) =>
          q >= +s.data[0][0] - spanx * 0.02 &&
          q <= +s.data.at(-1)[0] + spanx * 0.02,
      )
      .map((s) => ({
        name: s.name,
        p: s.data.reduce((a, b) =>
          Math.abs(+a[0] - q) < Math.abs(+b[0] - q) ? a : b,
        ),
      }));
    if (!values.length) {
      tip.hidden = true;
      return;
    }
    tip.textContent = values
      .map(
        (v) =>
          (time ? date(v.p[0]) : fmt(v.p[0])) +
          " · " +
          v.name +
          ": " +
          fmt(v.p[1], unit === "r" ? 2 : 1),
      )
      .join("\n");
    tip.hidden = false;
    tip.style.left =
      Math.max(0, Math.min(rect.width - 265, e.clientX - rect.left + 12)) +
      "px";
    tip.style.top = "6px";
    cross.setAttribute("x1", px);
    cross.setAttribute("x2", px);
    cross.setAttribute("visibility", "visible");
  };
  plot.onpointerleave = () => {
    tip.hidden = true;
    cross.setAttribute("visibility", "hidden");
  };
}

function drawHistory() {
  if (!D) return;
  const start = $("from").value,
    end = $("to").value,
    map = new Map();
  if (start > end) {
    $("historyChart").innerHTML =
      '<div class="panel-footnote">Начало периода должно быть раньше его конца.</div>';
    return;
  }
  for (const r of D.series) {
    if (r.y == null) continue;
    const day = r.time.slice(0, 10);
    if (day < start || day > end) continue;
    const a = map.get(day) || [0, 0];
    a[0] += r.y;
    a[1]++;
    map.set(day, a);
  }
  chart("historyChart", [
    {
      name: "Нагрузка",
      color: ACCENT,
      data: [...map].map(([day, a]) => [new Date(day), a[0] / a[1]]),
    },
  ]);
}
function drawProfiles() {
  chart(
    "hourChart",
    [
      {
        name: "Часовой профиль",
        color: ACCENT,
        data: Object.entries(D.stats.hour_profile).map(([k, v]) => [+k, v]),
      },
    ],
    { time: false },
  );
  chart(
    "monthChart",
    [
      {
        name: "Месячный профиль",
        color: ACCENT,
        data: Object.entries(D.stats.month_profile).map(([k, v]) => [+k, v]),
      },
    ],
    { time: false },
  );
}
function setPeriod() {
  if (!D) return;
  const last = new Date(D.last_observation);
  $("to").value = last.toISOString().slice(0, 10);
  $("from").value = new Date(+last - 89 * 86400000).toISOString().slice(0, 10);
  drawHistory();
}
function drawForecast() {
  if (!D) return;
  const model = $("model").value,
    h = +$("horizon").value,
    rows = D.forecast.filter((r) => r.model === model && r.horizon <= h);
  const last = new Date(D.last_observation),
    facts = D.series
      .filter((r) => r.y != null && +new Date(r.time) > +last - 72 * 3600000)
      .map((r) => [new Date(r.time), r.y]);
  chart(
    "forecastChart",
    [
      { name: "Факт", color: NEUTRAL, data: facts },
      {
        name: D.names[model],
        color: ACCENT,
        data: rows.map((r) => [new Date(r.time), r.predicted]),
      },
    ],
    { band: rows.map((r) => [new Date(r.time), r.lower, r.upper]) },
  );
  $("forecastNote").textContent =
    "Начало: " +
    date(D.forecast_origin) +
    " UTC · Последний факт: " +
    date(D.last_observation) +
    " UTC";
  $("forecastTable").innerHTML = table(
    ["Время UTC", "Прогноз, МВт", "Нижняя граница", "Верхняя граница"],
    rows.map((r) => [
      date(r.time),
      fmt(r.predicted),
      fmt(r.lower),
      fmt(r.upper),
    ]),
    { numeric: [1, 2, 3], timeColumn: true },
  );
}
function drawBacktest() {
  if (!D) return;
  const phase = $("phase").value,
    rows = D.metrics.filter((r) => r.phase === phase);
  $("metricsTable").innerHTML = table(
    ["Модель", "MAE, МВт", "RMSE, МВт", "Покрытие 90%", "Часов"],
    rows.map((r) => [
      D.names[r.model],
      fmt(r.MAE, 1),
      fmt(r.RMSE, 1),
      fmt(r.coverage * 100, 1) + "%",
      r.n,
    ]),
    {
      numeric: [1, 2, 3, 4],
      rowKeys: rows.map((r) => r.model),
      selected: D.best_model,
    },
  );
  $("testModelLabel").textContent = D.names[D.best_model];
  const selected = D.backtest.filter(
      (r) => r.phase === "test" && r.model === D.best_model,
    ),
    last = selected
      .map((r) => r.origin)
      .sort()
      .at(-1),
    p = selected.filter((r) => r.origin === last);
  chart(
    "testChart",
    [
      {
        name: "Факт",
        color: NEUTRAL,
        data: p.map((r) => [new Date(r.time), r.actual]),
      },
      {
        name: "Прогноз",
        color: ACCENT,
        data: p.map((r) => [new Date(r.time), r.predicted]),
      },
    ],
    { band: p.map((r) => [new Date(r.time), r.lower, r.upper]) },
  );
  chart(
    "errorChart",
    Object.keys(D.names).map((m, i) => ({
      name: D.names[m],
      color:
        m === D.best_model ? ACCENT : m === "seasonal_naive" ? "#aba6ad" : DARK,
      dash: m === "seasonal_naive",
      data: Array.from({ length: 24 }, (_, j) => {
        const a = D.backtest.filter(
          (r) => r.phase === "test" && r.model === m && r.horizon === j + 1,
        );
        return [
          j + 1,
          Math.sqrt(a.reduce((s, r) => s + r.error * r.error, 0) / a.length),
        ];
      }),
    })),
    { time: false },
  );
  $("residualText").textContent =
    "Среднее остатка: " +
    fmt(D.diagnostics.mean_error_mw, 1) +
    " МВт · σ = " +
    fmt(D.diagnostics.std_error_mw, 1) +
    " МВт. Ошибки сохраняют временную структуру.";
  chart(
    "acfChart",
    [
      {
        name: "Корреляция остатков",
        color: ACCENT,
        data: D.diagnostics.acf_within_window.map((r) => [
          r.lag,
          r.correlation,
        ]),
      },
    ],
    { time: false, unit: "r" },
  );
}
function drawScenario() {
  if (!D || !lastScenario) return;
  const base = D.forecast.filter((r) => r.model === "ridge"),
    rows = lastScenario.rows;
  chart(
    "scenarioChart",
    [
      {
        name: "Базовый Ridge",
        color: NEUTRAL,
        dash: true,
        data: base.map((r) => [new Date(r.time), r.predicted]),
      },
      {
        name:
          "Сценарий " +
          (lastScenarioDelta >= 0 ? "+" : "") +
          lastScenarioDelta +
          " °C",
        color: ACCENT,
        data: rows.map((r) => [new Date(r.time), r.predicted]),
      },
    ],
    { band: rows.map((r) => [new Date(r.time), r.lower, r.upper]) },
  );
}
async function runScenario() {
  if (!D) return;
  const request = ++scenarioRequest,
    value = Number($("delta").value);
  $("scenarioMessage").className = "scenario-result";
  if (
    $("delta").value.trim() === "" ||
    !Number.isFinite(value) ||
    value < -10 ||
    value > 10
  ) {
    $("scenarioRun").disabled = false;
    $("scenarioMessage").className = "scenario-result error";
    $("scenarioMessage").textContent =
      "Введите изменение температуры от −10 до +10 °C.";
    return;
  }
  $("scenarioRun").disabled = true;
  $("scenarioMessage").textContent = "Пересчёт сценария…";
  document
    .querySelectorAll(".preset")
    .forEach((b) =>
      b.classList.toggle("selected", Number(b.dataset.delta) === value),
    );
  try {
    const r = await fetch("/api/scenario", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ delta: value }),
      }),
      s = await r.json();
    if (request !== scenarioRequest) return;
    if (!r.ok) throw Error(s.error);
    lastScenario = s;
    lastScenarioDelta = value;
    drawScenario();
    const base = D.forecast.filter((r) => r.model === "ridge"),
      difference =
        s.rows.reduce((sum, r) => sum + r.predicted, 0) / s.rows.length -
        base.reduce((sum, r) => sum + r.predicted, 0) / base.length;
    $("scenarioMessage").className =
      "scenario-result" + (s.in_range ? "" : " notice");
    $("scenarioMessage").textContent =
      "Изменение средней нагрузки: " +
      (difference > 0 ? "+" : "") +
      fmt(difference, 1) +
      " МВт. " +
      (s.in_range
        ? "Индикатор в диапазоне обучающих данных."
        : "Выход за диапазон обучения — экстраполяция.");
  } catch (e) {
    if (request === scenarioRequest) {
      $("scenarioMessage").className = "scenario-result error";
      $("scenarioMessage").textContent = e.message;
    }
  } finally {
    if (request === scenarioRequest) $("scenarioRun").disabled = false;
  }
}
async function loadLogs() {
  const rows = await (await fetch("/api/logs")).json();
  const names = { elexon: "Elexon Insights", open_meteo: "Open-Meteo" },
    statuses = {
      downloaded: "Загружено",
      offline: "Снимок",
      up_to_date: "Актуально",
      retry: "Повтор",
      error: "Ошибка",
    };
  $("logs").innerHTML = table(
    ["Время UTC", "Источник", "Статус", "Байт"],
    rows
      .slice(-12)
      .reverse()
      .map((r) => [
        date(r.time_utc),
        names[r.source] || r.source,
        statuses[r.status] || r.status,
        r.bytes ? fmt(r.bytes) : "—",
      ]),
    { numeric: [3], timeColumn: true },
  );
}
function drawCurrent() {
  if (!D) return;
  if (activeTab === "overview") {
    drawHistory();
    drawProfiles();
  } else if (activeTab === "forecast") drawForecast();
  else if (activeTab === "backtest") drawBacktest();
  else if (activeTab === "scenarios") drawScenario();
}
function activate(tab, { focus = false } = {}) {
  if (!SECTIONS[tab]) tab = "overview";
  activeTab = tab;
  document
    .querySelectorAll("main>section")
    .forEach((s) => (s.hidden = s.id !== tab));
  document.querySelectorAll("nav button").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === tab);
    if (b.dataset.tab === tab) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
  $("pageTitle").textContent = SECTIONS[tab][1];
  $("pageDescription").textContent = SECTIONS[tab][2];
  document.title = SECTIONS[tab][0] + " · EnergyScope";
  drawCurrent();
  if (focus) {
    $("pageTitle").setAttribute("tabindex", "-1");
    $("pageTitle").focus({ preventScroll: true });
  }
}
async function load() {
  try {
    const response = await fetch("/api/data");
    if (!response.ok) {
      $("empty").hidden = false;
      return false;
    }
    D = await response.json();
    $("empty").hidden = true;
    const test = D.metrics.find(
        (r) => r.phase === "test" && r.model === D.best_model,
      ),
      last = D.series.filter((r) => r.y != null).at(-1);
    const metrics = [
      [
        "Последняя нагрузка",
        fmt(last.y),
        "МВт",
        shortDate(D.last_observation) +
          " · " +
          date(D.last_observation).slice(-5) +
          " UTC",
      ],
      [
        "RMSE на тесте",
        fmt(test.RMSE),
        "МВт",
        D.config.test_folds + " окон по 24 часа",
      ],
      [
        "Полнота нагрузки",
        fmt(D.quality.completeness_percent, 2),
        "%",
        fmt(D.quality.valid_hours) + " из " + fmt(D.quality.hours) + " часов",
      ],
    ];
    $("stats").innerHTML = metrics
      .map(
        (a, i) =>
          `<div class="metric"><span class="metric-label">${esc(a[0])}</span><strong class="metric-value${i === 1 ? " emphasis" : ""}">${esc(a[1])}<span class="metric-unit">${esc(a[2])}</span></strong><span class="metric-meta">${esc(a[3])}</span></div>`,
      )
      .join("");
    $("lastFact").textContent = date(D.last_observation) + " UTC";
    if (!$("from").value) setPeriod();
    const currentModel = $("model").value;
    $("model").innerHTML = Object.entries(D.names)
      .map(([k, v]) => `<option value="${k}">${esc(v)}</option>`)
      .join("");
    $("model").value = D.names[currentModel] ? currentModel : D.best_model;
    $("weatherText").textContent =
      "Корреляция нагрузки с температурой в Лондоне: " +
      fmt(D.stats.correlations.temperature, 2) +
      ".";
    const labels = [
      "Динамика",
      "Погода",
      "Аномалии",
      "Прогноз",
      "Точность",
      "Данные",
      "Сценарий",
    ];
    $("insights").innerHTML = D.insights
      .map(
        (text, i) =>
          `<div class="insight"><span class="insight-label">${esc(labels[i] || "Анализ")}</span><p>${esc(text)}</p></div>`,
      )
      .join("");
    const q = D.quality;
    $("qualityTable").innerHTML = table(
      ["Проверка", "Результат"],
      [
        ["Получасовые записи", fmt(q.raw_energy_rows)],
        ["Период наблюдений", date(q.first_time) + " — " + date(q.last_time)],
        ["Полные / все часы", fmt(q.valid_hours) + " / " + fmt(q.hours)],
        ["Пропущенные часы нагрузки", q.missing_hours],
        ["Дубли временных меток", q.duplicate_energy_rows],
        ["Недопустимые значения", q.invalid_energy_rows],
        ["Пропуски температуры", q.weather_missing_hours.temperature],
        ["Последняя погода, UTC", date(q.weather_last_time)],
        ["Нетипичные часы", D.stats.anomaly_hours],
      ],
      { numeric: [1] },
    );
    $("rangeText").textContent =
      "Диапазон применимости температурного индикатора: " +
      fmt(D.scenario_range[0], 1) +
      "…" +
      fmt(D.scenario_range[1], 1) +
      " °C.";
    drawCurrent();
    drawForecast();
    drawBacktest();
    await loadLogs();
    await runScenario();
    drawCurrent();
    return true;
  } catch (e) {
    $("status").className = "error";
    $("status").textContent = "Не удалось загрузить расчёт: " + e.message;
    return false;
  }
}
async function status() {
  try {
    const response = await fetch("/api/status");
    if (!response.ok) throw Error("Нет связи с программой");
    const s = await response.json();
    $("update").disabled = s.running;
    $("update").classList.toggle("updating", s.running);
    $("status").className = s.error ? "error" : "";
    $("modeLabel").textContent =
      s.offline === false ? "Онлайн-режим" : "Сохранённый расчёт";
    if (s.version !== lastVersion) {
      if (await load()) lastVersion = s.version;
    }
    $("status").textContent = s.error
      ? s.error
      : s.running
        ? s.message
        : D
          ? "Снимок от " + date(D.snapshot_utc) + " UTC."
          : "Загрузка расчёта…";
  } catch (e) {
    $("status").className = "error";
    $("status").textContent =
      "Нет связи с локальной программой. Проверьте, что окно запуска открыто.";
  }
}
for (const b of document.querySelectorAll("nav button"))
  b.onclick = () => {
    activate(b.dataset.tab);
    history.replaceState(null, "", "#" + b.dataset.tab);
  };
$("period").onclick = drawHistory;
$("model").onchange = drawForecast;
$("horizon").onchange = drawForecast;
$("phase").onchange = drawBacktest;
$("scenarioRun").onclick = runScenario;
for (const b of document.querySelectorAll(".preset"))
  b.onclick = () => {
    $("delta").value = b.dataset.delta;
    runScenario();
  };
$("delta").addEventListener("keydown", (e) => {
  if (e.key === "Enter") runScenario();
});
$("update").onclick = async () => {
  try {
    $("update").disabled = true;
    const r = await fetch("/api/update", { method: "POST" });
    if (!r.ok) throw Error("Не удалось запустить обновление");
    await status();
  } catch (e) {
    $("status").className = "error";
    $("status").textContent = e.message;
    $("update").disabled = false;
  }
};
window.addEventListener("hashchange", () => activate(location.hash.slice(1)));
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(drawCurrent, 100);
});
activate(location.hash.slice(1));
status();
setInterval(status, 3000);
