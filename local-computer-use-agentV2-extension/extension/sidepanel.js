// 側邊欄前端邏輯：呼叫本地後端 API，輪詢狀態與事件。
const API = "http://127.0.0.1:8756";

let sessionId = null;
let eventCursor = 0;
let pollTimer = null;

const $ = (id) => document.getElementById(id);

async function api(path, method = "GET", body = null) {
  const opt = { method, headers: { "Content-Type": "application/json" } };
  if (body) opt.body = JSON.stringify(body);
  const res = await fetch(API + path, opt);
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`${res.status} ${txt}`);
  }
  return res.json();
}

// --- 連線狀態 ---
async function checkHealth() {
  try {
    await api("/health");
    $("conn").textContent = "後端已連線";
    $("conn").className = "badge on";
    return true;
  } catch {
    $("conn").textContent = "後端未連線";
    $("conn").className = "badge off";
    return false;
  }
}

// --- 產生計畫 ---
$("planBtn").addEventListener("click", async () => {
  const task = $("task").value.trim();
  if (!task) return alert("請輸入任務");
  if (!(await checkHealth())) return alert("無法連線後端，請先啟動 python run_backend.py");

  $("planBtn").disabled = true;
  $("planBtn").textContent = "規劃中...";
  try {
    const data = await api("/plan", "POST", { task, max_steps: Number($("maxSteps").value) });
    sessionId = data.session_id;
    renderPlan(data.plan);
    $("plan-section").classList.remove("hidden");
  } catch (e) {
    alert("規劃失敗：" + e.message);
  } finally {
    $("planBtn").disabled = false;
    $("planBtn").textContent = "產生計畫";
  }
});

function renderPlan(plan) {
  const sc = plan.safety_check || {};
  const safeEl = $("safety");
  safeEl.className = "safety " + (sc.is_safe ? "low" : "high");
  safeEl.textContent = `安全檢查：${sc.is_safe ? "通過" : "高風險"} (${sc.risk_level}) — ${sc.reason}`;
  $("summary").textContent = plan.task_summary || "";
  const ol = $("planSteps");
  ol.innerHTML = "";
  (plan.plan || []).forEach((s) => {
    const li = document.createElement("li");
    li.textContent = `${s.goal}（${s.expected_action_type}）`;
    ol.appendChild(li);
  });
  refreshShot("planShot");
}

// --- Approve / Revise / Cancel ---
$("approveBtn").addEventListener("click", async () => {
  if (!sessionId) return;
  await api(`/session/${sessionId}/approve`, "POST");
  $("plan-section").classList.add("hidden");
  $("exec-section").classList.remove("hidden");
  eventCursor = 0;
  $("events").innerHTML = "";
  startPolling();
});

$("reviseBtn").addEventListener("click", () => $("reviseBox").classList.toggle("hidden"));

$("reviseSubmit").addEventListener("click", async () => {
  const note = $("reviseNote").value.trim();
  if (!note || !sessionId) return;
  try {
    const data = await api(`/session/${sessionId}/revise`, "POST", { note });
    renderPlan(data.plan);
    $("reviseBox").classList.add("hidden");
  } catch (e) {
    alert("重新規劃失敗：" + e.message);
  }
});

$("cancelBtn").addEventListener("click", async () => {
  if (sessionId) await api(`/session/${sessionId}/cancel`, "POST").catch(() => {});
  resetUI();
});

$("stopBtn").addEventListener("click", async () => {
  if (sessionId) await api(`/session/${sessionId}/cancel`, "POST").catch(() => {});
});

// --- 確認高風險動作 ---
$("confirmYes").addEventListener("click", () => answerConfirm(true));
$("confirmNo").addEventListener("click", () => answerConfirm(false));
async function answerConfirm(approved) {
  if (!sessionId) return;
  await api(`/session/${sessionId}/confirm`, "POST", { approved }).catch((e) => alert(e.message));
  $("confirmBox").classList.add("hidden");
}

// --- 輪詢 ---
function startPolling() {
  stopPolling();
  pollTimer = setInterval(poll, 1200);
  poll();
}
function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

async function poll() {
  if (!sessionId) return;
  try {
    const st = await api(`/session/${sessionId}/status`);
    $("stateBadge").textContent = st.state;
    $("stepInfo").textContent = `步數 ${st.steps_done}/${st.max_steps}` +
      (st.reason ? ` — ${st.reason}` : "");
    refreshShot("liveShot");

    if (st.pending_confirm) {
      $("confirmMsg").textContent = st.pending_confirm.message;
      $("confirmBox").classList.remove("hidden");
    } else {
      $("confirmBox").classList.add("hidden");
    }

    const ev = await api(`/session/${sessionId}/events?since=${eventCursor}`);
    ev.events.forEach(renderEvent);
    eventCursor = ev.next;

    if (["completed", "failed", "cancelled"].includes(st.state)) {
      stopPolling();
      $("stopBtn").disabled = true;
    }
  } catch (e) {
    // 後端暫時無回應時不中斷輪詢
  }
}

function renderEvent(e) {
  const div = document.createElement("div");
  let cls = "";
  let text = `[${e.time}] ${e.kind}`;
  if (e.kind === "action" && e.action) { cls = "ev-action"; text += ` → ${e.action} ${e.reason ? "(" + e.reason + ")" : ""}`; }
  else if (e.kind === "result") { cls = e.ok ? "ev-result-ok" : "ev-result-fail"; text += e.ok ? " ok" : ` FAIL: ${e.error || ""}`; }
  else if (e.kind === "blocked") { cls = "ev-blocked"; text += ` ${e.reason}`; }
  else if (e.kind === "await_confirm") { cls = "ev-await_confirm"; text += ` ${e.message}`; }
  else if (e.kind === "done") { text += ` → ${e.state}: ${e.reason}`; }
  else if (e.reason) { text += ` ${e.reason}`; }
  div.className = cls;
  div.textContent = text;
  const box = $("events");
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function refreshShot(imgId) {
  if (!sessionId) return;
  const img = $(imgId);
  img.src = `${API}/session/${sessionId}/screenshot?t=${Date.now()}`;
  img.classList.remove("hidden");
  img.onerror = () => img.classList.add("hidden");
}

function resetUI() {
  stopPolling();
  sessionId = null;
  $("plan-section").classList.add("hidden");
  $("exec-section").classList.add("hidden");
  $("stopBtn").disabled = false;
}

// 啟動時檢查一次連線，並每 5 秒重試。
checkHealth();
setInterval(checkHealth, 5000);
