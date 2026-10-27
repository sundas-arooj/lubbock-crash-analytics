const SEVERITY_COLOR = {
  K: "#9f1239",
  A: "#c2410c",
  B: "#b45309",
  C: "#3f6212",
};

const state = {
  labels: {},
  requestId: 0,
  map: null,
  cluster: null,
};

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("filters").addEventListener("submit", (event) => {
    event.preventDefault();
    loadProfile();
  });
  document.getElementById("reset").addEventListener("click", () => {
    document.getElementById("filters").reset();
    loadProfile();
  });
  start();
});

async function start() {
  try {
    const choices = await fetchJson("/api/filters");
    state.labels = Object.fromEntries(
      choices.severities.map((item) => [item.code, item.label])
    );
    fillSelect("county", choices.counties);
    fillSelect("year", choices.years);
    fillSelect(
      "severity-filter",
      choices.severities.map((item) => ({ value: item.code, label: item.label }))
    );
    fillSelect("road-class", choices.road_classes);
    renderLegend(choices.severities);
    const source = choices.source || {};
    const asOf = source.as_of ? ` Extract dated ${source.as_of}.` : "";
    document.getElementById("lede").textContent =
      `Injury and fatal crashes, ${choices.years[0] || ""}–${choices.years.at(-1) || ""}.${asOf}`;
    await loadProfile();
  } catch (error) {
    showError(error.message);
  }
}

async function loadProfile() {
  const requestId = ++state.requestId;
  const params = currentParams();
  setBusy(true);
  clearError();
  try {
    const overview = await fetchJson(`/api/overview?${params}`);
    if (requestId !== state.requestId) return;
    renderOverview(overview);
    const locations = await fetchJson(`/api/locations?${params}`);
    if (requestId !== state.requestId) return;
    renderMap(locations);
    document.getElementById("status").textContent = "";
  } catch (error) {
    if (requestId !== state.requestId) return;
    showError(error.message);
  } finally {
    if (requestId === state.requestId) setBusy(false);
  }
}

function renderOverview(overview) {
  const fatal = overview.severity.find((item) => item.severity === "K");
  const serious = overview.severity.find((item) => item.severity === "A");
  document.getElementById("kpis").innerHTML = [
    ["Crashes", overview.crash_count],
    ["Fatal crashes", fatal ? fatal.count : 0],
    ["Serious injury crashes", serious ? serious.count : 0],
    ["Deaths", overview.death_count],
  ]
    .map(
      ([label, value]) =>
        `<article class="kpi"><span>${label}</span><strong>${formatNumber(value)}</strong></article>`
    )
    .join("");

  if (overview.crash_count === 0) {
    document.getElementById("severity").innerHTML = empty("No crashes match these filters.");
    document.getElementById("factors").innerHTML = "";
    document.getElementById("trend").innerHTML = "";
    document.getElementById("hours").innerHTML = "";
    return;
  }

  renderBars(
    "severity",
    overview.severity.map((item) => ({
      label: item.label,
      count: item.count,
      share: item.share,
      severity: item.severity,
    }))
  );
  renderBars(
    "factors",
    overview.factors.map((item) => ({
      label: labelize(item.factor),
      count: item.count,
      share: item.share,
      severity: "factor",
    }))
  );
  if (overview.factors.length === 0) {
    document.getElementById("factors").innerHTML = empty(
      "No coded contributing factor in this slice."
    );
  }
  renderTrend(overview.trends);
  renderHours(overview.hours, overview.crash_count);
}

function renderBars(containerId, rows) {
  const max = Math.max(...rows.map((row) => row.count), 1);
  document.getElementById(containerId).innerHTML = rows
    .map((row) => {
      const width = (row.count / max) * 100;
      return `<div class="bar-row">
        <div class="bar-label">${escapeHtml(row.label)}</div>
        <div class="bar-track"><div class="bar-fill" data-severity="${row.severity}" style="width:${width}%"></div></div>
        <div class="bar-value">${formatNumber(row.count)} · ${percent(row.share)}</div>
      </div>`;
    })
    .join("");
}

function renderTrend(points) {
  const host = document.getElementById("trend");
  if (!points.length) {
    host.innerHTML = empty("No dated crashes in this slice.");
    return;
  }
  const width = 800;
  const height = 240;
  const pad = { left: 44, right: 12, top: 16, bottom: 32 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const max = Math.max(...points.map((point) => point.count), 1);
  const step = points.length === 1 ? 0 : innerW / (points.length - 1);
  const coords = points.map((point, index) => {
    const x = pad.left + (points.length === 1 ? innerW / 2 : index * step);
    const y = pad.top + innerH - (point.count / max) * innerH;
    return { ...point, x, y };
  });
  const line = coords
    .map((point, index) => `${index === 0 ? "M" : "L"}${point.x.toFixed(1)},${point.y.toFixed(1)}`)
    .join(" ");
  const ticks = coords.filter(
    (point, index) => point.month === 1 || index === 0 || index === coords.length - 1
  );
  host.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Monthly crash counts">
    <line x1="${pad.left}" y1="${pad.top + innerH}" x2="${width - pad.right}" y2="${pad.top + innerH}" stroke="#ddd2c2"/>
    <line x1="${pad.left}" y1="${pad.top}" x2="${pad.left}" y2="${pad.top + innerH}" stroke="#ddd2c2"/>
    <text x="${pad.left - 8}" y="${pad.top + 4}" text-anchor="end" font-size="11" fill="#5e584e">${formatNumber(max)}</text>
    <path d="${line}" fill="none" stroke="#1e3a5f" stroke-width="2"/>
    ${coords
      .map(
        (point) =>
          `<circle cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="2.5" fill="#1e3a5f"><title>${point.period}: ${formatNumber(point.count)}</title></circle>`
      )
      .join("")}
    ${ticks
      .map(
        (point) =>
          `<text x="${point.x.toFixed(1)}" y="${height - 8}" text-anchor="middle" font-size="11" fill="#5e584e">${point.year}</text>`
      )
      .join("")}
  </svg>
  <table class="sr-only">
    <caption>Monthly crash counts</caption>
    <tbody>
      ${points.map((point) => `<tr><th>${point.period}</th><td>${point.count}</td></tr>`).join("")}
    </tbody>
  </table>`;
}

function renderHours(hours, crashCount) {
  const host = document.getElementById("hours");
  const max = Math.max(...hours.map((hour) => hour.count), 1);
  const timed = hours.reduce((sum, hour) => sum + hour.count, 0);
  document.getElementById("hour-hint").textContent =
    timed < crashCount
      ? `Local time from the crash report. ${formatNumber(crashCount - timed)} crashes have no usable time and are left off this chart.`
      : "Local time from the crash report.";
  host.innerHTML = `<div class="hour-plot">
    ${hours
      .map((hour) => {
        const height = Math.max((hour.count / max) * 100, hour.count ? 2 : 0);
        return `<div class="hour-bar" style="height:${height}%" title="${hour.period}: ${formatNumber(hour.count)} crashes"></div>`;
      })
      .join("")}
  </div>
  <div class="hour-labels">
    ${hours
      .map((hour) => `<span>${hour.hour % 6 === 0 ? String(hour.hour).padStart(2, "0") : ""}</span>`)
      .join("")}
  </div>`;
}

function renderMap(payload) {
  const note = document.getElementById("map-note");
  const omitted = payload.crash_count - payload.returned;
  note.textContent = omitted > 0
    ? `Showing ${formatNumber(payload.returned)} mapped crashes out of ${formatNumber(payload.crash_count)}. The rest have no usable coordinate.`
    : `Showing all ${formatNumber(payload.returned)} crashes in this slice.`;

  if (!window.L) {
    note.textContent = "The map library did not load. Charts above still use the same filters.";
    return;
  }
  if (!state.map) {
    state.map = L.map("map", { scrollWheelZoom: false }).setView([33.58, -101.85], 7);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18,
      attribution: "&copy; OpenStreetMap",
    }).addTo(state.map);
  }
  if (state.cluster) {
    state.map.removeLayer(state.cluster);
  }
  state.cluster = L.markerClusterGroup({ chunkedLoading: true, maxClusterRadius: 46 });
  payload.locations.forEach((crash) => {
    const color = SEVERITY_COLOR[crash.severity] || "#1e3a5f";
    const marker = L.circleMarker([crash.latitude, crash.longitude], {
      radius: 6,
      color,
      weight: 1,
      fillColor: color,
      fillOpacity: 0.85,
    });
    const label = state.labels[crash.severity] || crash.severity || "Unknown severity";
    marker.bindPopup(
      `<strong>${escapeHtml(label)}</strong><br>${escapeHtml(crash.crash_date || "Date not reported")}<br>${escapeHtml(crash.county || "County not reported")}<br>Crash ${escapeHtml(crash.crash_id)}`
    );
    state.cluster.addLayer(marker);
  });
  state.map.addLayer(state.cluster);
  state.map.invalidateSize();
  if (payload.locations.length) {
    const bounds = state.cluster.getBounds();
    if (bounds.isValid()) state.map.fitBounds(bounds.pad(0.15));
  }
}

function renderLegend(severities) {
  document.getElementById("legend").innerHTML = severities
    .map(
      (item) =>
        `<span><i class="swatch" style="background:${SEVERITY_COLOR[item.code]}"></i>${escapeHtml(item.label)}</span>`
    )
    .join("");
}

function fillSelect(id, values) {
  const select = document.getElementById(id);
  const first = select.firstElementChild;
  select.innerHTML = "";
  select.appendChild(first);
  values.forEach((value) => {
    const option = document.createElement("option");
    if (typeof value === "object") {
      option.value = value.value;
      option.textContent = value.label;
    } else {
      option.value = value;
      option.textContent = value;
    }
    select.appendChild(option);
  });
}

function currentParams() {
  const form = new FormData(document.getElementById("filters"));
  const params = new URLSearchParams();
  for (const [key, value] of form.entries()) {
    if (String(value).trim()) params.set(key, String(value).trim());
  }
  return params.toString();
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    let detail = `Request failed (${response.status}).`;
    try {
      const body = await response.json();
      if (body.detail) detail = body.detail;
    } catch (_error) {
      /* The body was not JSON. */
    }
    throw new Error(detail);
  }
  return response.json();
}

function formatNumber(value) {
  return Number(value).toLocaleString("en-US");
}

function percent(share) {
  return `${(share * 100).toFixed(1)}%`;
}

function labelize(value) {
  return String(value)
    .toLowerCase()
    .replace(/(^|[\s\-/])([a-z])/g, (_match, boundary, letter) => boundary + letter.toUpperCase());
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[character]));
}

function empty(message) {
  return `<p class="empty">${escapeHtml(message)}</p>`;
}

function setBusy(busy) {
  document.getElementById("apply").disabled = busy;
  document.getElementById("status").textContent = busy ? "Updating figures…" : "";
}

function showError(message) {
  const node = document.getElementById("error");
  node.hidden = false;
  node.textContent = message;
  document.getElementById("status").textContent = "";
}

function clearError() {
  const node = document.getElementById("error");
  node.hidden = true;
  node.textContent = "";
}
