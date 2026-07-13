/**
 * sidepanel.js — 聊天式控制面板
 *
 * 主要改動（相對 V3）：
 * 1. API 端點改為 /task/plan 和 /task/approve
 * 2. 新增 bridge 連線狀態顯示（WebSocket to Python）
 * 3. 事件輪詢同步顯示每步 element 操作
 * 其餘 UI 邏輯不動。
 */

"use strict";

const API = "http://127.0.0.1:8000";

let sessionId = null;
let eventCursor = 0;
let pollTimer = null;
let mode = "task";
let finished = false;

const $ = (id) => document.getElementById(id);
const messages = () => $("messages");

// ---------------------------------------------------------------------------
// HTTP API
// ---------------------------------------------------------------------------
async function api(path, method = "GET", body = null) {
  const opt = { method, headers: { "Content-Type": "application/json" } };
  if (body) opt.body = JSON.stringify(body);
  const res = await fetch(API + path, opt);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// 連線狀態
// ---------------------------------------------------------------------------
async function checkHealth() {
  try {
    const data = await api("/health");
    setStatus("backend", true);
    setStatus("bridge", data.bridge_connected === true);
    return true;
  } catch {
    setStatus("backend", false);
    setStatus("bridge", false);
    return false;
  }
}

function setStatus(type, on) {
  if (type === "backend") {
    $("statusDot").classList.toggle("on", on);
    $("connText").textContent = on ? "後端已連線" : "後端未連線";
    $("connText").className = "conn-text " + (on ? "on" : "off");
  }
  if (type === "bridge") {
    const el = $("bridgeDot");
    const txt = $("bridgeText");
    if (!el || !txt) return;
    el.classList.toggle("on", on);
    txt.textContent = on ? "Extension 已橋接" : "Extension 未橋接";
    txt.className = "conn-text " + (on ? "on" : "off");
  }
}

// ---------------------------------------------------------------------------
// 訊息渲染
// ---------------------------------------------------------------------------
function addMsg(role) {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  wrap.appendChild(bubble);
  messages().appendChild(wrap);
  scrollDown();
  return bubble;
}
function addUser(text) { const b = addMsg("user"); b.textContent = text; }
function addAgentText(text) { const b = addMsg("agent"); b.textContent = text; return b; }
function addSystem(text) { const b = addMsg("system"); b.textContent = text; }
function addMuted(text) { const b = addMsg("agent"); b.className = "bubble muted"; b.textContent = text; }
function scrollDown() { const m = messages(); m.scrollTop = m.scrollHeight; }

function addTyping() {
  const b = addMsg("agent");
  b.innerHTML = '<span class="typing"><span></span><span></span><span></span></span>';
  return b.parentElement;
}

function mkBtn(label, kind, onClick) {
  const btn = document.createElement("button");
  btn.className = "act" + (kind ? " " + kind : "");
  btn.textContent = label;
  btn.addEventListener("click", onClick);
  return btn;
}

// ---------------------------------------------------------------------------
// 計畫卡
// ---------------------------------------------------------------------------
function renderPlanCard(plan) {
  const b = addMsg("agent");
  b.classList.add("plan-card");
  const sc = plan.safety_check || {};

  const safe = document.createElement("div");
  safe.className = "plan-safety " + (sc.is_safe ? "low" : "high");
  safe.textContent = `安全：${sc.is_safe ? "通過" : "高風險"} (${sc.risk_level}) — ${sc.reason}`;
  b.appendChild(safe);

  const sum = document.createElement("div");
  sum.className = "plan-summary";
  sum.textContent = plan.task_summary || "";
  b.appendChild(sum);

  const ol = document.createElement("ol");
  ol.className = "plan-steps";
  (plan.plan || []).forEach((s) => {
    const li = document.createElement("li");
    li.textContent = `${s.goal} (${s.expected_action_type})`;
    ol.appendChild(li);
  });
  b.appendChild(ol);

  const actions = document.createElement("div");
  actions.className = "plan-actions";
  const approveBtn = mkBtn("同意，開始執行", "primary", () => {
    disableCard(actions);
    approve();
  });
  const cancelBtn = mkBtn("取消", "danger", () => {
    disableCard(actions);
    addSystem("已取消");
    resetSession();
  });
  actions.append(approveBtn, cancelBtn);
  b.appendChild(actions);
  scrollDown();
}

function disableCard(actionsEl) {
  actionsEl.querySelectorAll("button").forEach((x) => (x.disabled = true));
}

// ---------------------------------------------------------------------------
// 執行步驟渲染
// ---------------------------------------------------------------------------
const _stepEls = {};

function renderStep(e) {
  const b = addMsg("agent");
  const line = document.createElement("div");
  line.className = "step-line";
  const num = document.createElement("span");
  num.className = "step-num";
  num.textContent = e.step;
  const body = document.createElement("span");
  body.className = "step-body";
  const act = document.createElement("span");
  act.className = "step-action";
  const actionName = e.action?.action || "";
  const elementId = e.action?.element_id || "";
  act.textContent = elementId ? `${actionName} [${elementId}]` : actionName;
  body.appendChild(act);
  if (e.action?.reason) {
    const r = document.createElement("span");
    r.className = "step-reason";
    r.textContent = " · " + e.action.reason;
    body.appendChild(r);
  }
  const status = document.createElement("span");
  status.className = "step-status";
  if (e.ok === true) { status.className += " ok"; status.textContent = "✓"; }
  else if (e.ok === false) { status.className += " fail"; status.textContent = "✗ " + (e.error || ""); }
  if (e.elements_count != null) {
    const cnt = document.createElement("span");
    cnt.className = "step-reason";
    cnt.textContent = ` | ${e.elements_count} 個元素`;
    body.appendChild(cnt);
  }
  line.append(num, body, status);
  b.appendChild(line);
  scrollDown();
}

function renderResult(state, reason) {
  const label = { completed: "✅ 任務完成", failed: "❌ 任務失敗", cancelled: "⏹ 已取消" }[state] || state;
  const b = addMsg("agent");
  b.classList.add("result-" + state);
  b.textContent = `${label}：${reason}`;
  scrollDown();
}

// ---------------------------------------------------------------------------
// 動作
// ---------------------------------------------------------------------------
async function startPlan(task) {
  if (!(await checkHealth())) {
    addMuted("無法連線後端，請先執行 python run_backend.py");
    return;
  }
  resetSession();
  addUser(task);
  const typing = addTyping();
  try {
    const data = await api("/task/plan", "POST", {
      task,
      use_mock_plan: true,
    });
    sessionId = data.session_id;
    typing.remove();
    renderPlanCard(data.plan);
  } catch (e) {
    typing.remove();
    addMuted("規劃失敗：" + e.message);
  }
}

async function approve() {
  try {
    await api("/task/approve", "POST", {
      session_id: sessionId,
      observation_mode: "browser",
    });
    addSystem("開始執行（Browser DOM + Screenshot 模式）");
    $("livePreview").classList.remove("hidden");
    eventCursor = 0;
    finished = false;
    startPolling();
  } catch (e) {
    addMuted("無法開始執行：" + e.message);
  }
}

function resetSession() {
  stopPolling();
  sessionId = null;
  eventCursor = 0;
  finished = false;
  mode = "task";
  $("livePreview")?.classList.add("hidden");
}

// ---------------------------------------------------------------------------
// 輪詢
// ---------------------------------------------------------------------------
function startPolling() { stopPolling(); pollTimer = setInterval(poll, 1500); poll(); }
function stopPolling() { if (pollTimer) clearInterval(pollTimer); pollTimer = null; }

async function poll() {
  if (!sessionId) return;
  try {
    const st = await api(`/session/${sessionId}/status`);
    const chip = $("stateChip");
    if (chip) {
      chip.textContent = st.state;
      chip.className = `chip ${st.state}`;
      chip.classList.remove("hidden");
    }

    const ev = await api(`/session/${sessionId}/events?since=${eventCursor}`);
    ev.events.forEach(handleEvent);
    eventCursor = ev.next;

    if (["completed", "failed", "cancelled"].includes(st.state)) {
      if (!finished) {
        finished = true;
        renderResult(st.state, st.result?.reason || "");
      }
      stopPolling();
    }
  } catch (_) {}
}

function handleEvent(e) {
  switch (e.kind) {
    case "step": renderStep(e); break;
    case "done": if (!finished) { finished = true; renderResult(e.state, e.reason || ""); } break;
    default: break;
  }
}

// ---------------------------------------------------------------------------
// 輸入
// ---------------------------------------------------------------------------
function send() {
  const input = $("input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  autoresize();
  startPlan(text);
}

function autoresize() {
  const input = $("input");
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 120) + "px";
}

$("sendBtn").addEventListener("click", send);
$("input").addEventListener("input", autoresize);
$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});
$("newChatBtn")?.addEventListener("click", () => {
  resetSession();
  messages().innerHTML = "";
  addAgentText("開新任務。用一句話告訴我你想完成什麼。");
});

// bridge 狀態訊息（從 background.js）
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.kind === "bridge_status") setStatus("bridge", msg.connected);
});

checkHealth();
setInterval(checkHealth, 5000);
