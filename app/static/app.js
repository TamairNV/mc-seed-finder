// Seeds are always JS strings here. Never convert them to numbers: they can exceed 2^53.
const $ = (id) => document.getElementById(id);
const MAP_BLOCKS = 6144;
const MAX_ZOOM = 8;
const ZOOM_BUTTON_STEP = 1.5;
const PAST_EDGE = 0.1;  // how far past its edge the map can be dragged, as a share of its width
const STRUCTURES = {
  Village: "#ffd23f", Trial_Chambers: "#ff7a33", Mansion: "#b05cff", Ancient_City: "#21d4d4", Monument: "#3f8cff",
  Desert_Pyramid: "#e8c88a", Jungle_Temple: "#54d15a", Outpost: "#ff4d6d", Trail_Ruins: "#c49a6c",
};
const COMPONENTS = {
  spawn_biome: ["Spawn biome", 20], variety: ["Variety", 15], rare_biomes: ["Rare biomes", 25],
  structures: ["Structures", 30], terrain: ["Terrain", 10],
};
const LAYERS = ["weirdness", "surface", "underground", "height"];
const hidden = new Set(["Trial_Chambers", "Outpost", "Trail_Ruins"]);  // common enough to crowd the map
let selected = null;
let hoverTimer = null;
let wasRunning = false;
const view = { scale: 1, x: 0, y: 0 };
const pointers = new Map();

async function api(path, options = {}) {
  const init = { ...options };
  if (init.json !== undefined) {
    init.method = init.method || "POST";
    init.headers = { "content-type": "application/json" };
    init.body = JSON.stringify(init.json);
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new Error("Couldn't reach the server. If your login expired, reload the page.");
  }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "That request wasn't valid.";
    throw new Error(detail);
  }
  return body;
}

function showError(error) {
  $("error").hidden = !error;
  $("error").textContent = error ? error.message : "";
}

const guarded = (fn) => async (...args) => {
  showError(null);
  try {
    return await fn(...args);
  } catch (error) {
    showError(error);
  }
};

const pretty = (name) => name.replaceAll("_", " ");
const peakPercent = (row) => `${(row.peak_share * 100).toFixed(1)}%`;

const mapWidth = () => $("map").clientWidth;

function applyView() {
  const width = mapWidth();
  const margin = width * PAST_EDGE;
  const limit = (value) => Math.max(width - view.scale * width - margin, Math.min(margin, value));
  view.x = limit(view.x);
  view.y = limit(view.y);
  $("map-world").style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.scale})`;
  $("map").classList.toggle("zoomed", view.scale > 1);
  drawMarkers();
}

function zoomAt(cx, cy, factor) {
  const scale = Math.max(1, Math.min(MAX_ZOOM, view.scale * factor));
  view.x = cx - ((cx - view.x) * scale) / view.scale;
  view.y = cy - ((cy - view.y) * scale) / view.scale;
  view.scale = scale;
  applyView();
}

function resetView() {
  Object.assign(view, { scale: 1, x: 0, y: 0 });
  applyView();
}

function drawMarkers() {
  const canvas = $("markers");
  const width = mapWidth();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = canvas.height = Math.round(width * ratio);
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  if (!selected) return;
  const sx = (block) => view.x + view.scale * width * (block / MAP_BLOCKS + 0.5);
  const sz = (block) => view.y + view.scale * width * (block / MAP_BLOCKS + 0.5);
  for (const [kind, x, z] of selected.structures) {
    if (hidden.has(kind)) continue;
    ctx.beginPath();
    ctx.arc(sx(x), sz(z), 5, 0, Math.PI * 2);
    ctx.fillStyle = STRUCTURES[kind];
    ctx.fill();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = "#000";
    ctx.stroke();
  }
  const ox = sx(0), oz = sz(0);
  ctx.lineWidth = 2;
  ctx.strokeStyle = "#fff";
  ctx.beginPath();
  ctx.moveTo(ox - 7, oz); ctx.lineTo(ox + 7, oz); ctx.moveTo(ox, oz - 7); ctx.lineTo(ox, oz + 7);
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(sx(selected.spawn_x), sz(selected.spawn_z), 9, 0, Math.PI * 2);
  ctx.strokeStyle = "#000"; ctx.lineWidth = 4; ctx.stroke();
  ctx.strokeStyle = "#ff2ea6"; ctx.lineWidth = 2; ctx.stroke();
}

function starButton(row) {
  const star = document.createElement("button");
  star.type = "button";
  star.className = "star";
  star.textContent = row.shortlisted ? "★" : "☆";
  star.setAttribute("aria-pressed", String(row.shortlisted));
  star.setAttribute("aria-label", row.shortlisted ? "Remove from shortlist" : "Add to shortlist");
  star.onclick = guarded(async (event) => {
    event.stopPropagation();
    const saved = await api(`/api/seeds/${row.seed}/shortlist`, { method: "PUT", json: { shortlisted: !row.shortlisted } });
    if (selected?.seed === saved.seed) {
      selected = saved;
      renderBreakdown(saved);
    }
    await refreshList();
  });
  return star;
}

function renderBreakdown(row) {
  const box = $("breakdown");
  box.replaceChildren();
  const title = document.createElement("div");
  title.className = "seed-title";
  const total = document.createElement("span");
  total.className = "total";
  total.textContent = row.rejected_reason ? "Rejected" : row.score.toFixed(1);
  const code = document.createElement("code");
  code.textContent = row.seed;
  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "secondary";
  copy.textContent = "Copy";
  copy.onclick = guarded(async () => {
    await navigator.clipboard.writeText(row.seed);
    copy.textContent = "Copied";
  });
  title.append(starButton(row), total, code, copy);
  box.append(title);
  if (row.rejected_reason) {
    const why = document.createElement("p");
    why.className = "rejected";
    why.textContent = row.rejected_reason;
    box.append(why);
  }
  for (const [key, [label, max]] of Object.entries(COMPONENTS)) {
    const value = row.breakdown[key] ?? 0;
    const bar = document.createElement("div");
    bar.className = "bar";
    const name = document.createElement("span");
    name.textContent = label;
    const track = document.createElement("i");
    const fill = document.createElement("b");
    fill.style.width = `${(value / max) * 100}%`;
    track.append(fill);
    const points = document.createElement("span");
    points.textContent = `${value.toFixed(1)}/${max}`;
    bar.append(name, track, points);
    box.append(bar);
  }
  const facts = document.createElement("p");
  facts.className = "status";
  facts.textContent = `Spawn ${row.spawn_x}, ${row.spawn_z} in ${pretty(row.spawn_biome)}. ` +
    `Peak terrain ${peakPercent(row)}. Average weirdness ${row.mean_weirdness.toFixed(3)} (usually near 0). ` +
    `${row.structures.length} structures on this map.`;
  box.append(facts);
}

function selectSeed(row) {
  const changed = selected?.seed !== row.seed;
  selected = row;
  $("map-empty").hidden = true;
  renderBreakdown(row);
  for (const tr of $("seed-list").children) tr.classList.toggle("selected", tr.dataset.seed === row.seed);
  if (!changed) return;
  resetView();
  syncLayers();
}

// Layers that take time to build are only requested once something on the page needs them.
function wantedLayers() {
  const wanted = ["weirdness", $("biome-mode").value];
  if (Number($("height-opacity").value) > 0) wanted.push("height");
  return wanted;
}

function requestLayer(layer, seed) {
  const img = $(`layer-${layer}`);
  img.dataset.seed = seed;
  delete img.dataset.settled;
  img.onload = () => { img.dataset.settled = "loaded"; syncLayers(); };
  img.onerror = () => {
    img.dataset.settled = "failed";
    syncLayers();
    showError(new Error(`Couldn't load the ${layer} map.`));
  };
  img.src = `/api/seeds/${seed}/layers/${layer}.png`;
}

function syncLayers() {
  if (!selected) return;
  const seed = selected.seed;
  const wanted = wantedLayers();
  let waiting = false;
  for (const layer of LAYERS) {
    const img = $(`layer-${layer}`);
    const want = wanted.includes(layer);
    if (want && img.dataset.seed !== seed) requestLayer(layer, seed);
    const current = img.dataset.seed === seed;
    if (want && current && !img.dataset.settled) waiting = true;
    // an old seed's map must not sit under the new seed's markers
    img.hidden = !(want && current && img.dataset.settled === "loaded");
  }
  $("map-loading").hidden = !waiting;
}

const refreshList = guarded(async () => {
  const shortlist = $("shortlist-filter").checked ? "&shortlist=true" : "";
  const rows = await api(`/api/seeds?sort=${$("sort").value}${shortlist}`);
  $("seed-list").replaceChildren(...rows.map((row) => {
    const tr = document.createElement("tr");
    tr.dataset.seed = row.seed;
    tr.tabIndex = 0;
    tr.classList.toggle("was-rejected", !!row.rejected_reason);
    tr.classList.toggle("selected", selected?.seed === row.seed);
    const starCell = document.createElement("td");
    starCell.append(starButton(row));
    tr.append(starCell);
    const cells = [
      row.rejected_reason ? "Rejected" : row.score.toFixed(1),
      pretty(row.spawn_biome),
      peakPercent(row),
      row.input_text || row.seed,
    ];
    for (const text of cells) {
      const td = document.createElement("td");
      td.textContent = text;
      tr.append(td);
    }
    tr.onclick = () => selectSeed(row);
    tr.onkeydown = (e) => { if (e.key === "Enter") selectSeed(row); };
    return tr;
  }));
});

async function addSeed(body) {
  const row = await api("/api/seeds", { json: body });
  selectSeed(row);
  await refreshList();
}

function renderSearch(status) {
  $("search-btn").disabled = status.running;
  $("stop-btn").hidden = !status.running;
  $("search-progress").hidden = !status.running;
  $("search-progress").max = status.target || 1;
  $("search-progress").value = status.tried;
  if (status.target) {
    const parts = [`Tried ${status.tried.toLocaleString()} of ${status.target.toLocaleString()} seeds.`];
    if (status.best_score !== null) parts.push(`Best so far ${status.best_score.toFixed(1)}.`);
    if (!status.running && status.stopped_early) parts.push("Stopped early.");
    if (status.error) parts.push(`Some seeds failed: ${status.error}`);
    $("search-status").textContent = parts.join(" ");
  }
}

async function pollSearch() {
  try {
    const status = await api("/api/search");
    renderSearch(status);
    if (status.running || wasRunning) await refreshList();
    wasRunning = status.running;
    if (status.running) setTimeout(pollSearch, 1000);
    else if (status.best_seed && status.target && !selected) {
      selectSeed(await api(`/api/seeds/${status.best_seed}`));
    }
  } catch (error) {
    showError(error);
    setTimeout(pollSearch, 5000);
  }
}

function onHover(event) {
  if (!selected) return;
  const rect = $("map").getBoundingClientRect();
  const toBlock = (offset, shift) => Math.floor(((offset - shift) / (view.scale * rect.width) - 0.5) * MAP_BLOCKS);
  const x = toBlock(event.clientX - rect.left, view.x);
  const z = toBlock(event.clientY - rect.top, view.y);
  clearTimeout(hoverTimer);
  if (Math.abs(x + 0.5) > MAP_BLOCKS / 2 || Math.abs(z + 0.5) > MAP_BLOCKS / 2) {
    $("hover").textContent = "Past the edge of the map";
    return;
  }
  $("hover").textContent = `x ${x}, z ${z}`;
  const seed = selected.seed;
  hoverTimer = setTimeout(async () => {
    try {
      const point = await api(`/api/seeds/${seed}/point?x=${x}&z=${z}`);
      if (selected?.seed === seed) {
        const caves = point.cave_biome ? ` · caves below: ${pretty(point.cave_biome)}` : "";
        $("hover").textContent = `x ${x}, z ${z} · ${pretty(point.biome)}${caves} · height ~${point.height} · weirdness ${point.weirdness.toFixed(3)} · ${point.terrain}`;
      }
    } catch { /* a hover readout isn't worth an error message */ }
  }, 150);
}

function bindMap() {
  const map = $("map");
  const local = (event) => {
    const rect = map.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };
  const spread = () => {
    const [a, b] = [...pointers.values()];
    return { distance: Math.hypot(a.x - b.x, a.y - b.y), x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  };
  map.addEventListener("wheel", (event) => {
    event.preventDefault();
    const { x, y } = local(event);
    zoomAt(x, y, event.deltaY < 0 ? 1.25 : 0.8);
  }, { passive: false });
  map.addEventListener("pointerdown", (event) => {
    if (event.target.closest(".zoom")) return;
    map.setPointerCapture(event.pointerId);
    pointers.set(event.pointerId, local(event));
    map.classList.add("dragging");
    onHover(event);
  });
  map.addEventListener("pointermove", (event) => {
    const previous = pointers.get(event.pointerId);
    if (!previous) {
      onHover(event);
      return;
    }
    const now = local(event);
    if (pointers.size === 2) {
      const before = spread();
      pointers.set(event.pointerId, now);
      const after = spread();
      view.x += after.x - before.x;
      view.y += after.y - before.y;
      zoomAt(after.x, after.y, after.distance / before.distance);
      return;
    }
    pointers.set(event.pointerId, now);
    view.x += now.x - previous.x;
    view.y += now.y - previous.y;
    applyView();
  });
  const release = (event) => {
    pointers.delete(event.pointerId);
    if (!pointers.size) map.classList.remove("dragging");
  };
  map.addEventListener("pointerup", release);
  map.addEventListener("pointercancel", release);
  map.addEventListener("pointerleave", () => { clearTimeout(hoverTimer); });
  const centre = (factor) => zoomAt(mapWidth() / 2, mapWidth() / 2, factor);
  $("zoom-in").onclick = () => centre(ZOOM_BUTTON_STEP);
  $("zoom-out").onclick = () => centre(1 / ZOOM_BUTTON_STEP);
  $("zoom-reset").onclick = resetView;
  new ResizeObserver(applyView).observe(map);
}

function buildToggles() {
  for (const [kind, color] of Object.entries(STRUCTURES)) {
    const label = document.createElement("label");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = !hidden.has(kind);
    box.onchange = () => {
      if (box.checked) hidden.delete(kind); else hidden.add(kind);
      drawMarkers();
    };
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background = color;
    label.append(box, swatch, document.createTextNode(pretty(kind)));
    $("structure-toggles").append(label);
  }
}

function applyOpacity() {
  for (const layer of ["surface", "underground"]) $(`layer-${layer}`).style.opacity = $("biome-opacity").value;
  $("layer-height").style.opacity = $("height-opacity").value;
}

$("seed-form").onsubmit = (e) => {
  e.preventDefault();
  guarded(() => addSeed({ seed: $("seed-input").value }))();
};
$("random-btn").onclick = guarded(() => addSeed({ random: true }));
$("search-btn").onclick = guarded(async () => {
  renderSearch(await api("/api/search", { json: { count: Number($("search-count").value) } }));
  wasRunning = true;
  pollSearch();
});
$("stop-btn").onclick = guarded(() => api("/api/search/stop", { method: "POST" }));
$("sort").onchange = refreshList;
$("shortlist-filter").onchange = refreshList;
$("biome-opacity").oninput = applyOpacity;
$("height-opacity").oninput = () => { applyOpacity(); syncLayers(); };
$("biome-mode").onchange = syncLayers;
bindMap();

buildToggles();
applyOpacity();
refreshList();
pollSearch();
