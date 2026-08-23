"""The single-page interface, served inline by :mod:`limelight.server`.

Self-contained by design: no external stylesheet, script, font or image, so the page
works on a phone with no internet access as long as the phone can reach the host.

Two behaviours are worth knowing before editing this file.

*Capability gating.* Controls carry ``data-cap`` attributes and are hidden unless the
device reports the matching capability in ``GET /api/v1/device``. Adding a device with a
different feature set therefore needs no change here.

*Polling.* The page calls ``GET /api/v1/state`` every three seconds, and suspends polling
while a slider is being dragged so the control does not jump under the finger. Sliders
commit on release, so one drag sends one command rather than dozens.
"""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#111417">
<title>Limelight</title>
<style>
  :root{
    --bg:#f6f7f9; --card:#fff; --ink:#14181d; --muted:#697280; --line:#e3e6ea;
    --accent:#c8811f; --ok:#1f8a4c; --bad:#c0392b; --radius:14px;
  }
  @media (prefers-color-scheme:dark){
    :root{ --bg:#0e1114; --card:#171b20; --ink:#e8ecf1; --muted:#98a2b0; --line:#262c34;
           --accent:#e0a44a; --ok:#43c37a; --bad:#e5695b; }
  }
  *{box-sizing:border-box}
  body{margin:0;padding:16px 14px 48px;background:var(--bg);color:var(--ink);
       font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
       max-width:620px;margin-inline:auto}
  h1{font-size:19px;margin:0 0 2px;letter-spacing:-.01em}
  .sub{color:var(--muted);font-size:12.5px;margin-bottom:16px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
        padding:14px 15px;margin-bottom:12px}
  .card h2{font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);
           margin:0 0 12px;font-weight:600}
  .row{display:flex;align-items:center;justify-content:space-between;gap:12px;
       padding:9px 0;border-bottom:1px solid var(--line)}
  .row:last-child{border-bottom:0;padding-bottom:0}
  .row label{flex:1;min-width:0}
  .hint{display:block;color:var(--muted);font-size:11.5px;margin-top:1px}
  button{font:inherit;color:var(--ink);background:var(--card);border:1px solid var(--line);
         border-radius:9px;padding:8px 13px;cursor:pointer}
  button:active{transform:translateY(1px)}
  button.primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
  button.ghost{background:transparent}
  button.danger{color:var(--bad);border-color:var(--line);padding:6px 9px}
  .power{width:100%;padding:15px;font-size:16px;font-weight:600;border-radius:12px}
  .power.on{background:var(--accent);border-color:var(--accent);color:#fff}
  .pill{font-size:11.5px;padding:3px 9px;border-radius:99px;border:1px solid var(--line);color:var(--muted)}
  .pill.live{color:var(--ok);border-color:var(--ok)}
  .pill.dead{color:var(--bad);border-color:var(--bad)}
  input[type=range]{width:100%;accent-color:var(--accent);height:26px}
  input[type=number],input[type=time],input[type=text],input[type=password],select{
    font:inherit;color:var(--ink);background:var(--bg);border:1px solid var(--line);
    border-radius:8px;padding:7px 9px;max-width:110px}
  .val{font-variant-numeric:tabular-nums;font-weight:600;min-width:44px;text-align:right}
  .grid{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}
  .grid.two{grid-template-columns:repeat(2,1fr)}
  .sw{position:relative;width:44px;height:26px;flex:0 0 44px}
  .sw input{opacity:0;width:100%;height:100%;margin:0;cursor:pointer}
  .sw span{position:absolute;inset:0;background:var(--line);border-radius:99px;transition:.15s;pointer-events:none}
  .sw span:after{content:"";position:absolute;width:20px;height:20px;left:3px;top:3px;
                 background:#fff;border-radius:50%;transition:.15s}
  .sw input:checked+span{background:var(--accent)}
  .sw input:checked+span:after{transform:translateX(18px)}
  .bar{height:6px;background:var(--line);border-radius:99px;overflow:hidden;margin:9px 0 7px}
  .bar i{display:block;height:100%;background:var(--accent);transition:width .6s linear}
  .sched{display:flex;align-items:center;gap:10px;padding:9px 0;border-bottom:1px solid var(--line)}
  .sched:last-child{border-bottom:0}
  .sched .n{flex:1;min-width:0}
  .toast{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);background:var(--ink);
         color:var(--bg);padding:9px 15px;border-radius:9px;font-size:13px;opacity:0;
         transition:.2s;pointer-events:none;z-index:9;max-width:90vw;text-align:center}
  .toast.show{opacity:1}
  .add{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}
  .add > *{min-width:0}
  .days{display:flex;gap:4px;flex-wrap:wrap}
  .days button{padding:5px 8px;font-size:12px;border-radius:7px}
  .days button.sel{background:var(--accent);color:#fff;border-color:var(--accent)}
  .muted{color:var(--muted);font-size:12.5px}
  button.icon{flex:0 0 40px;width:40px;height:40px;padding:0;border-radius:10px;
              display:grid;place-items:center;font-size:15px;line-height:1;color:var(--muted)}
  button.icon:disabled{opacity:.35;cursor:default}
  .sliderrow{display:flex;align-items:center;gap:10px}
  .sliderrow input[type=range]{flex:1;min-width:0}
  .warn{color:var(--bad)}
  [hidden]{display:none !important}
</style>
</head>
<body>

<h1 id="title">Limelight</h1>
<div class="sub">
  <span id="dev">connecting…</span> <span id="live" class="pill">checking</span>
</div>

<div class="card">
  <button id="power" class="power" data-cap="power">…</button>
  <div data-cap="brightness">
    <div class="row" style="margin-top:13px">
      <label>Brightness<span class="hint">Main light</span></label>
      <div class="val" id="brightVal">–</div>
    </div>
    <input type="range" id="bright" min="1" max="100" value="50">
  </div>
</div>

<div class="card" id="rampCard" hidden>
  <h2>In progress</h2>
  <div id="rampLabel" class="muted"></div>
  <div class="bar"><i id="rampBar" style="width:0"></i></div>
  <div class="row">
    <label class="muted" id="rampLeft"></label>
    <button class="ghost" id="rampCancel">Cancel</button>
  </div>
</div>

<div class="card" data-cap="brightness">
  <h2>Wake up and wind down</h2>
  <div class="row">
    <label>Sunrise now<span class="hint">Ramps from 1% to the target. Runs in this service, so it stops if the host sleeps.</span></label>
  </div>
  <div class="grid two" style="margin-bottom:9px">
    <div><span class="muted">Minutes</span><br><input type="number" id="srMin" value="20" min="1" max="600"></div>
    <div><span class="muted">Target %</span><br><input type="number" id="srTgt" value="100" min="1" max="100"></div>
  </div>
  <button class="primary" style="width:100%" id="srGo">Start sunrise</button>

  <div class="row" style="margin-top:15px">
    <label>Fade to sleep<span class="hint">Dims to 1%, then powers off</span></label>
    <input type="number" id="fdMin" value="30" min="1" max="600">
  </div>
  <button style="width:100%" id="fdGo">Start fade out</button>
</div>

<div class="card" data-cap="sleep_timer">
  <h2>Sleep timer, on the device itself</h2>
  <div class="muted" style="margin-bottom:12px">
    Counts down on the device, so it still works after this service is closed.
  </div>
  <div class="row" style="border-bottom:0;padding-top:0">
    <label>Switch off after<span class="hint">Drag to zero, or use the cross, to cancel</span></label>
    <div class="val" id="dvLabel">Off</div>
  </div>
  <div class="sliderrow">
    <input type="range" id="dv" min="0" max="120" step="5" value="0"
           aria-label="Sleep timer in minutes">
    <button class="icon" id="dvClear" title="Cancel the sleep timer"
            aria-label="Cancel the sleep timer">&#10005;</button>
  </div>
</div>

<div class="card" id="modes">
  <h2>Modes</h2>
  <div class="row" data-cap="eyecare">
    <label>Eyecare<span class="hint">Flicker-reduced output. The mode sets its own brightness, and moving the brightness slider turns it off.</span></label>
    <div class="sw"><input type="checkbox" id="eyecare"><span></span></div>
  </div>
  <div data-cap="ambient">
    <div class="row">
      <label>Ambient light<span class="hint">The secondary light in the base</span></label>
      <div class="sw"><input type="checkbox" id="ambient"><span></span></div>
    </div>
  </div>
  <div data-cap="ambient_brightness">
    <div class="row" style="border-bottom:0">
      <label class="muted">Ambient brightness</label>
      <div class="val" id="ambVal">–</div>
    </div>
    <input type="range" id="amb" min="1" max="100" value="40">
  </div>
  <div class="row" data-cap="night_light">
    <label>Smart night light<span class="hint">Dim output when the room is dark</span></label>
    <div class="sw"><input type="checkbox" id="night"><span></span></div>
  </div>
  <div class="row" data-cap="reminder">
    <label>Eye-fatigue reminder<span class="hint">Prompts a break after prolonged use</span></label>
    <div class="sw"><input type="checkbox" id="reminder"><span></span></div>
  </div>
</div>

<div class="card" data-cap="scenes">
  <h2>Scenes</h2>
  <div class="grid" id="scenes"></div>
</div>

<div class="card">
  <h2>Schedules</h2>
  <div id="schedList"></div>
  <div class="add">
    <input type="text" id="nName" placeholder="Name" style="max-width:none">
    <select id="nKind" style="max-width:none">
      <option value="sunrise">Sunrise ramp</option>
      <option value="fade_off">Fade out then off</option>
      <option value="on">Turn on</option>
      <option value="off">Turn off</option>
      <option value="timer">Device sleep timer</option>
    </select>
    <div><span class="muted">Time</span><br><input type="time" id="nTime" value="07:00"></div>
    <div><span class="muted">Minutes</span><br><input type="number" id="nDur" value="20" min="0" max="600"></div>
    <div><span class="muted">Target %</span><br><input type="number" id="nTgt" value="100" min="1" max="100"></div>
    <div style="display:flex;align-items:flex-end"><label class="muted" style="display:flex;gap:7px;align-items:center">
      <input type="checkbox" id="nAmb" style="width:auto"> ambient</label></div>
  </div>
  <div class="days" id="nDays" style="margin:11px 0"></div>
  <button class="primary" style="width:100%" id="addGo">Add schedule</button>
</div>

<div class="toast" id="toast"></div>

<script>
"use strict";
const API = "/api/v1";
const $ = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));
const DAYS = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
let dragging = false, newDays = [0,1,2,3,4], caps = new Set(), scenesDrawn = false;

// The key is only needed when the service has authentication enabled. It is kept in
// localStorage so a phone does not have to be re-paired on every visit.
const keyStore = {
  get: () => localStorage.getItem("limelight_key") || "",
  set: v => localStorage.setItem("limelight_key", v),
};

function toast(msg, bad){
  const t = $("#toast");
  t.textContent = msg;
  t.style.background = bad ? "var(--bad)" : "";
  t.style.color = bad ? "#fff" : "";
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2200);
}

function headers(){
  const h = {"Content-Type": "application/json"};
  const k = keyStore.get();
  if(k) h["Authorization"] = "Bearer " + k;
  return h;
}

async function req(method, path, body){
  const r = await fetch(API + path, {
    method, headers: headers(),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if(r.status === 401){
    const k = prompt("This limelight service requires an API key.");
    if(k){ keyStore.set(k.trim()); return req(method, path, body); }
    throw new Error("authentication required");
  }
  if(!r.ok){
    let detail = r.status;
    try { detail = (await r.json()).detail || detail; } catch(e){}
    throw new Error(detail);
  }
  return r.json();
}

async function post(path, body, okMsg){
  try{
    await req("POST", path, body || {});
    if(okMsg) toast(okMsg);
    refresh();
  }catch(err){ toast("Failed: " + err.message, true); }
}

function applyCapabilities(list){
  caps = new Set(list || []);
  $$("[data-cap]").forEach(el => { el.hidden = !caps.has(el.dataset.cap); });
  const modes = $("#modes");
  if(modes) modes.hidden = !$$("#modes [data-cap]").some(el => !el.hidden);
}

function renderDays(){
  const box = $("#nDays");
  box.innerHTML = "";
  DAYS.forEach((d, i) => {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = d;
    b.className = newDays.includes(i) ? "sel" : "";
    b.onclick = () => {
      newDays = newDays.includes(i) ? newDays.filter(x => x !== i) : [...newDays, i].sort();
      renderDays();
    };
    box.appendChild(b);
  });
}

function renderScenes(scenes){
  if(scenesDrawn) return;
  const box = $("#scenes");
  box.innerHTML = "";
  Object.entries(scenes || {}).forEach(([n, name]) => {
    const b = document.createElement("button");
    b.textContent = name;
    b.onclick = () => post("/scene", {number: +n}, name + " scene");
    box.appendChild(b);
  });
  scenesDrawn = Object.keys(scenes || {}).length > 0;
}

function renderSchedules(list){
  const box = $("#schedList");
  box.innerHTML = list.length ? "" : '<div class="muted">No schedules yet.</div>';
  list.forEach(s => {
    const row = document.createElement("div"); row.className = "sched";
    const n = document.createElement("div"); n.className = "n";
    const note = s.service_driven ? " <span class='warn'>needs this service running</span>" : "";
    n.innerHTML = "<b></b><span class='hint'></span>";
    n.querySelector("b").textContent = s.name;
    n.querySelector(".hint").innerHTML = s.describe + note;
    const sw = document.createElement("div"); sw.className = "sw";
    sw.innerHTML = "<input type='checkbox'><span></span>";
    const cb = sw.querySelector("input");
    cb.checked = s.enabled;
    cb.onchange = e => post("/schedules", Object.assign({}, s, {enabled: e.target.checked}),
                            s.name + (e.target.checked ? " enabled" : " disabled"));
    const del = document.createElement("button");
    del.className = "danger"; del.textContent = "Delete";
    del.onclick = async () => {
      try{ await req("DELETE", "/schedules/" + s.id); toast("Deleted " + s.name); refresh(); }
      catch(err){ toast("Failed: " + err.message, true); }
    };
    row.append(n, sw, del);
    box.appendChild(row);
  });
}

function paint(d){
  const dev = d.device || {};
  $("#title").textContent = dev.name || "Limelight";
  $("#dev").textContent = (dev.display_name || dev.model || "device") + " · " + (dev.address || "?");
  const live = $("#live");
  live.textContent = d.reachable ? "online" : "unreachable";
  live.className = "pill " + (d.reachable ? "live" : "dead");

  applyCapabilities(dev.capabilities);
  renderScenes(dev.scenes);
  renderSchedules(d.schedules || []);

  const r = d.ramp || {};
  $("#rampCard").hidden = !r.active;
  if(r.active){
    $("#rampLabel").textContent = r.label || r.kind;
    $("#rampBar").style.width = Math.round((r.progress || 0) * 100) + "%";
    const m = Math.ceil((r.remaining_s || 0) / 60);
    $("#rampLeft").textContent = m + (m === 1 ? " minute remaining" : " minutes remaining");
  }

  const s = d.state;
  if(!s) return;
  const p = $("#power");
  p.textContent = s.on ? "On — tap to switch off" : "Off — tap to switch on";
  p.className = "power" + (s.on ? " on" : "");
  p.onclick = () => post("/power", {on: !s.on});

  if(!dragging){
    if(s.brightness != null) $("#bright").value = s.brightness;
    if(s.ambient_brightness != null) $("#amb").value = s.ambient_brightness;
  }
  if(s.brightness != null) $("#brightVal").textContent = s.brightness + "%";
  if(s.ambient_brightness != null) $("#ambVal").textContent = s.ambient_brightness + "%";
  if(s.sleep_timer_minutes != null){
    if(!dragging) $("#dv").value = Math.min(120, s.sleep_timer_minutes);
    $("#dvLabel").textContent = timerLabel(s.sleep_timer_minutes);
    $("#dvClear").disabled = s.sleep_timer_minutes === 0;
  }
  if(s.eyecare != null) $("#eyecare").checked = s.eyecare;
  if(s.ambient_on != null) $("#ambient").checked = s.ambient_on;
  if(s.night_light != null) $("#night").checked = s.night_light;
  if(s.reminder != null) $("#reminder").checked = s.reminder;
}

async function refresh(){
  try{ paint(await req("GET", "/state")); }
  catch(err){
    $("#live").textContent = "no service";
    $("#live").className = "pill dead";
  }
}

// Sliders commit on release, so one drag sends one command rather than dozens.
function wireSlider(sel, path, valSel){
  const el = $(sel);
  ["mousedown","touchstart"].forEach(ev => el.addEventListener(ev, () => dragging = true));
  el.addEventListener("input", () => $(valSel).textContent = el.value + "%");
  el.addEventListener("change", () => { dragging = false; post(path, {level: +el.value}); });
}
wireSlider("#bright", "/brightness", "#brightVal");
wireSlider("#amb", "/ambient_brightness", "#ambVal");

$("#eyecare").onchange  = e => post("/eyecare",     {on: e.target.checked});
$("#ambient").onchange  = e => post("/ambient",     {on: e.target.checked});
$("#night").onchange    = e => post("/night_light", {on: e.target.checked});
$("#reminder").onchange = e => post("/reminder",    {on: e.target.checked});

function timerLabel(m){
  if(!m) return "Off";
  if(m < 60) return m + " min";
  const h = Math.floor(m / 60), r = m % 60;
  return r ? h + " h " + r + " min" : h + " h";
}

// The timer slider commits on release, like the brightness sliders, so one drag sends one
// command rather than a datagram per pixel.
(function wireTimer(){
  const el = $("#dv");
  ["mousedown","touchstart"].forEach(ev => el.addEventListener(ev, () => dragging = true));
  el.addEventListener("input", () => $("#dvLabel").textContent = timerLabel(+el.value));
  el.addEventListener("change", () => {
    dragging = false;
    const m = +el.value;
    post("/sleep_timer", {minutes: m},
         m ? "Switching off in " + timerLabel(m) : "Sleep timer cancelled");
  });
  $("#dvClear").onclick = () => {
    el.value = 0;
    $("#dvLabel").textContent = "Off";
    post("/sleep_timer", {minutes: 0}, "Sleep timer cancelled");
  };
})();

$("#rampCancel").onclick = () => post("/cancel_ramp", {}, "Ramp cancelled");
$("#srGo").onclick = () => post("/sunrise",
  {duration_min: +$("#srMin").value, target: +$("#srTgt").value}, "Sunrise started");
$("#fdGo").onclick = () => post("/fade_off", {duration_min: +$("#fdMin").value}, "Fade out started");

$("#addGo").onclick = () => {
  post("/schedules", {
    name: $("#nName").value || "Untitled",
    kind: $("#nKind").value,
    time: $("#nTime").value,
    days: newDays,
    enabled: true,
    duration_min: +$("#nDur").value,
    target_brightness: +$("#nTgt").value,
    ambient: $("#nAmb").checked,
  }, "Schedule added");
  $("#nName").value = "";
};

renderDays();
refresh();
setInterval(() => { if(!dragging) refresh(); }, 3000);
</script>
</body>
</html>
"""
