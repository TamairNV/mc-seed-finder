// Seeds are always JS strings here. Never convert them to numbers: they can exceed 2^53.
const $ = (id) => document.getElementById(id);
const MAP_BLOCKS = 4096;
const PIXELS_PER_BLOCK = 1024 / MAP_BLOCKS;
const STRUCTURES = {
  Village: "#ffd23f", Trial_Chambers: "#ff7a33", Mansion: "#b05cff", Ancient_City: "#21d4d4", Monument: "#3f8cff",
  Desert_Pyramid: "#e8c88a", Jungle_Temple: "#54d15a", Outpost: "#ff4d6d", Trail_Ruins: "#c49a6c",
};
const COMPONENTS = {
  spawn_biome: ["Spawn biome", 20], variety: ["Variety", 15], rare_biomes: ["Rare biomes", 25],
  structures: ["Structures", 30], terrain: ["Terrain", 10],
};
const hidden = new Set(["Trial_Chambers", "Outpost", "Trail_Ruins"]);  // common enough to crowd the map
let selected = null;
let hoverTimer = null;
let wasRunning = false;

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

function drawMarkers() {
  const ctx = $("markers").getContext("2d");
  ctx.clearRect(0, 0, 1024, 1024);
  if (!selected) return;
  const px = (block) => (block + MAP_BLOCKS / 2) * PIXELS_PER_BLOCK;
  for (const [kind, x, z] of selected.structures) {
    if (hidden.has(kind)) continue;
    ctx.beginPath();
    ctx.arc(px(x), px(z), 8, 0, Math.PI * 2);
    ctx.fillStyle = STRUCTURES[kind];
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = "#000";
    ctx.stroke();
  }
  ctx.lineWidth = 3;
  ctx.strokeStyle = "#fff";
  ctx.beginPath();
  ctx.moveTo(502, 512); ctx.lineTo(522, 512); ctx.moveTo(512, 502); ctx.lineTo(512, 522);
  ctx.stroke();
  const sx = px(selected.spawn_x), sz = px(selected.spawn_z);
  ctx.beginPath();
  ctx.arc(sx, sz, 13, 0, Math.PI * 2);
  ctx.strokeStyle = "#000"; ctx.lineWidth = 6; ctx.stroke();
  ctx.strokeStyle = "#ff2ea6"; ctx.lineWidth = 3; ctx.stroke();
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
  title.append(total, code, copy);
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
    `Mean weirdness ${row.mean_weirdness.toFixed(3)}. ${row.structures.length} structures on this map.`;
  box.append(facts);
}

function selectSeed(row) {
  selected = row;
  $("map-empty").hidden = true;
  for (const layer of ["weirdness", "biomes"]) {
    const img = $(`layer-${layer}`);
    img.hidden = false;
    img.onerror = () => showError(new Error(`Couldn't load the ${layer} map.`));
    img.src = `/api/seeds/${row.seed}/layers/${layer}.png`;
  }
  renderBreakdown(row);
  drawMarkers();
  for (const tr of $("seed-list").children) tr.classList.toggle("selected", tr.dataset.seed === row.seed);
}

const refreshList = guarded(async () => {
  const rows = await api(`/api/seeds?sort=${$("sort").value}`);
  $("seed-list").replaceChildren(...rows.map((row) => {
    const tr = document.createElement("tr");
    tr.dataset.seed = row.seed;
    tr.tabIndex = 0;
    tr.classList.toggle("was-rejected", !!row.rejected_reason);
    tr.classList.toggle("selected", selected?.seed === row.seed);
    const cells = [
      row.rejected_reason ? "Rejected" : row.score.toFixed(1),
      pretty(row.spawn_biome),
      row.mean_weirdness.toFixed(3),
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
  const clamp = (v) => Math.max(-2048, Math.min(2047, Math.floor(v)));
  const x = clamp(((event.clientX - rect.left) / rect.width - 0.5) * MAP_BLOCKS);
  const z = clamp(((event.clientY - rect.top) / rect.height - 0.5) * MAP_BLOCKS);
  $("hover").textContent = `x ${x}, z ${z}`;
  clearTimeout(hoverTimer);
  const seed = selected.seed;
  hoverTimer = setTimeout(async () => {
    try {
      const point = await api(`/api/seeds/${seed}/point?x=${x}&z=${z}`);
      if (selected?.seed === seed) {
        $("hover").textContent = `x ${x}, z ${z} · ${pretty(point.biome)} · weirdness ${point.weirdness.toFixed(3)}`;
      }
    } catch { /* a hover readout isn't worth an error message */ }
  }, 150);
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
  $("layer-biomes").style.opacity = $("biome-opacity").value;
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
$("biome-opacity").oninput = applyOpacity;
$("map").onmousemove = onHover;

buildToggles();
applyOpacity();
refreshList();
pollSearch();
