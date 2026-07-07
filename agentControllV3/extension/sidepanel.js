// 聊天式側邊欄：呼叫本地後端 API，把計畫、執行步驟、確認、結果都渲染成對話訊息。
const API = "http://127.0.0.1:8000";

let sessionId = null;
let eventCursor = 0;
let pollTimer = null;
let mode = "task";           // "task" | "revise"
let stepEls = {};            // step number -> { statusEl }
let confirmShownFor = null;  // 目前已顯示的待確認訊息，避免重複
let finished = false;

const $ = (id) => document.getElementById(id);
const messages = () => $("messages");

async function api(path, method = "GET", body = null) {
  const opt = { method, headers: { "Content-Type": "application/json" } };
  if (body) opt.body = JSON.stringify(body);
  const res = await fetch(API + path, opt);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

// ---------- 連線 ----------
async function checkHealth() {
  try {
    await api("/health");
    $("statusDot").classList.add("on");
    $("connText").textContent = "後端已連線";
    $("connText").className = "conn-text on";
    return true;
  } catch {
    $("statusDot").classList.remove("on");
    $("connText").textContent = "後端未連線";
    $("connText").className = "conn-text off";
    return false;
  }
}

// // ---------- 訊息渲染 ----------
// function addMsg(role) {
//   const wrap = document.createElement("div");
//   wrap.className = `msg ${role}`;
//   const bubble = document.createElement("div");
//   bubble.className = "bubble";
//   wrap.appendChild(bubble);
//   messages().appendChild(wrap);
//   scrollDown();
//   return bubble;
// }
// function addUser(text) { const b = addMsg("user"); b.textContent = text; }
// function addAgentText(text) { const b = addMsg("agent"); b.textContent = text; return b; }
// function addSystem(text) { const b = addMsg("system"); b.textContent = text; }
// function addMuted(text) { const b = addMsg("agent"); b.className = "bubble muted"; b.textContent = text; }
// function scrollDown() { const m = messages(); m.scrollTop = m.scrollHeight; }

// function addTyping() {
//   const b = addMsg("agent");
//   b.innerHTML = '<span class="typing"><span></span><span></span><span></span></span>';
//   return b.parentElement; // 回傳整個 .msg 以便移除
// }

// function renderPlanCard(plan) {
//   const b = addMsg("agent");
//   b.classList.add("plan-card");
//   const sc = plan.safety_check || {};
//   const safe = document.createElement("div");
//   safe.className = "plan-safety " + (sc.is_safe ? "low" : "high");
//   safe.textContent = `安全檢查：${sc.is_safe ? "通過" : "高風險"}（${sc.risk_level}）— ${sc.reason}`;
//   b.appendChild(safe);

//   const sum = document.createElement("div");
//   sum.className = "plan-summary";
//   sum.textContent = plan.task_summary || "計畫";
//   b.appendChild(sum);

//   const ol = document.createElement("ol");
//   ol.className = "plan-steps";
//   (plan.plan || []).forEach((s) => {
//     const li = document.createElement("li");
//     li.textContent = s.goal + " ";
//     const t = document.createElement("span");
//     t.className = "atype";
//     t.textContent = `（${s.expected_action_type}）`;
//     li.appendChild(t);
//     ol.appendChild(li);
//   });
//   b.appendChild(ol);

//   const actions = document.createElement("div");
//   actions.className = "plan-actions";
//   const approveBtn = mkBtn("同意，開始執行", "primary", () => { disableCard(actions); approve(); });
//   const reviseBtn = mkBtn("修改", "", () => enterReviseMode());
//   const cancelBtn = mkBtn("取消", "danger", () => { disableCard(actions); cancel(); });
//   actions.append(approveBtn, reviseBtn, cancelBtn);
//   b.appendChild(actions);
//   scrollDown();
// }
// function disableCard(actions) { actions.querySelectorAll("button").forEach((x) => (x.disabled = true)); }

// function mkBtn(label, kind, onClick) {
//   const btn = document.createElement("button");
//   btn.className = "act" + (kind ? " " + kind : "");
//   btn.textContent = label;
//   btn.addEventListener("click", onClick);
//   return btn;
// }

// function renderStep(e) {
//   const b = addMsg("agent");
//   const line = document.createElement("div");
//   line.className = "step-line";
//   const num = document.createElement("span");
//   num.className = "step-num";
//   num.textContent = e.step;
//   const body = document.createElement("span");
//   body.className = "step-body";
//   const act = document.createElement("span");
//   act.className = "step-action";
//   act.textContent = e.action;
//   body.appendChild(act);
//   if (e.reason) {
//     const r = document.createElement("span");
//     r.className = "step-reason";
//     r.textContent = " · " + e.reason;
//     body.appendChild(r);
//   }
//   const status = document.createElement("span");
//   status.className = "step-status";
//   line.append(num, body, status);
//   b.appendChild(line);
//   stepEls[e.step] = { statusEl: status };
//   scrollDown();
// }

// function updateStepResult(e) {
//   const ref = stepEls[e.step];
//   if (!ref) return;
//   ref.statusEl.className = "step-status " + (e.ok ? "ok" : "fail");
//   ref.statusEl.textContent = e.ok ? "✓" : "✗ " + (e.error || "失敗");
//   scrollDown();
// }

// function renderConfirm(message) {
//   const b = addMsg("agent");
//   b.classList.add("warn");
//   const p = document.createElement("div");
//   p.textContent = "需要你確認：" + message;
//   const acts = document.createElement("div");
//   acts.className = "confirm-actions";
//   const yes = mkBtn("允許", "danger", () => { disableCard(acts); answerConfirm(true); });
//   const no = mkBtn("拒絕", "", () => { disableCard(acts); answerConfirm(false); });
//   acts.append(yes, no);
//   b.append(p, acts);
//   scrollDown();
// }

// function renderResult(state, reason) {
//   const label = { completed: "任務完成", failed: "任務失敗", cancelled: "已取消" }[state] || state;
//   const b = addMsg("agent");
//   b.classList.add("result-" + state);
//   b.textContent = `${label}：${reason}`;
//   scrollDown();
// }

// ---------- 動作 ----------
async function startPlan() {
  if (!(await checkHealth())) { console.log("無法連線後端，請先執行 python run_backend.py"); return; }
  try {
    const data = await api("/test_screenshot", "POST");
    console.log("規劃成功，計畫：", data);
  } catch (e) {
    console.log("規劃失敗：" + e.message);
  }
}

// async function submitRevise(note) {
//   exitReviseMode();
//   addUser(note);
//   const typing = addTyping();
//   try {
//     const data = await api(`/session/${sessionId}/revise`, "POST", { note });
//     typing.remove();
//     renderPlanCard(data.plan);
//   } catch (e) {
//     typing.remove();
//     addMuted("重新規劃失敗：" + e.message);
//   }
// }

// async function approve() {
//   try {
//     await api(`/session/${sessionId}/approve`, "POST");
//     addSystem("開始執行");
//     setExecuting(true);
//     eventCursor = 0;
//     stepEls = {};
//     finished = false;
//     startPolling();
//   } catch (e) {
//     addMuted("無法開始執行：" + e.message);
//   }
// }

// async function cancel() {
//   if (sessionId) await api(`/session/${sessionId}/cancel`, "POST").catch(() => {});
//   addSystem("已取消");
//   setExecuting(false);
// }

// async function answerConfirm(approved) {
//   confirmShownFor = null;
//   if (sessionId) await api(`/session/${sessionId}/confirm`, "POST", { approved }).catch((e) => addMuted(e.message));
// }

// // ---------- 輪詢 ----------
// function startPolling() { stopPolling(); pollTimer = setInterval(poll, 1200); poll(); }
// function stopPolling() { if (pollTimer) clearInterval(pollTimer); pollTimer = null; }

// async function poll() {
//   if (!sessionId) return;
//   try {
//     const st = await api(`/session/${sessionId}/status`);
//     updateStateChip(st.state);
//     if (st.latest_screenshot) refreshShot();

//     if (st.pending_confirm && st.pending_confirm.message !== confirmShownFor) {
//       confirmShownFor = st.pending_confirm.message;
//       renderConfirm(st.pending_confirm.message);
//     } else if (!st.pending_confirm) {
//       confirmShownFor = null;
//     }

//     const ev = await api(`/session/${sessionId}/events?since=${eventCursor}`);
//     ev.events.forEach(handleEvent);
//     eventCursor = ev.next;

//     if (["completed", "failed", "cancelled"].includes(st.state)) {
//       if (!finished) { finished = true; renderResult(st.state, st.reason || ""); }
//       stopPolling();
//       setExecuting(false);
//     }
//   } catch (e) { /* 後端暫時無回應，下次再試 */ }
// }

// function handleEvent(e) {
//   switch (e.kind) {
//     case "action":
//       if (e.result_ok === null || e.result_ok === undefined) renderStep(e);
//       break;
//     case "result": updateStepResult(e); break;
//     case "blocked": addMuted("已封鎖高風險動作：" + (e.reason || "")); break;
//     case "parse_fail": addMuted("模型輸出無法解析，重試中"); break;
//     case "invalid_action": addMuted("動作不合法：" + (e.error || "")); break;
//     case "done": if (!finished) { finished = true; renderResult(e.state, e.reason || ""); } break;
//     default: break; // state / observe / await_confirm 不另外冒泡
//   }
// }

// // ---------- UI 狀態 ----------
// function updateStateChip(state) {
//   const chip = $("stateChip");
//   if (!state || state === "idle") { chip.classList.add("hidden"); return; }
//   chip.className = "chip " + state;
//   chip.textContent = { planning: "規劃中", awaiting_user_approval: "待確認", executing: "執行中",
//     paused: "已暫停", completed: "完成", failed: "失敗", cancelled: "已取消" }[state] || state;
//   chip.classList.remove("hidden");
// }

// function setExecuting(on) {
//   $("input").disabled = on;
//   $("sendBtn").disabled = on;
//   $("livePreview").classList.toggle("hidden", !on);
//   if (!on) { $("liveShot").src = ""; }
// }

// function refreshShot() {
//   $("liveShot").src = `${API}/session/${sessionId}/screenshot?t=${Date.now()}`;
// }

// function enterReviseMode() {
//   mode = "revise";
//   $("modeChip").classList.remove("hidden");
//   $("modeChipText").textContent = "修改計畫中";
//   $("input").placeholder = "輸入修改意見，例如：只點搜尋框，不要輸入文字";
//   $("input").focus();
// }
// function exitReviseMode() {
//   mode = "task";
//   $("modeChip").classList.add("hidden");
//   $("input").placeholder = "輸入任務…";
// }

// function resetSessionState() {
//   stopPolling();
//   eventCursor = 0;
//   stepEls = {};
//   confirmShownFor = null;
//   finished = false;
// }

// function newChat() {
//   resetSessionState();
//   sessionId = null;
//   exitReviseMode();
//   setExecuting(false);
//   updateStateChip("idle");
//   messages().innerHTML = "";
//   addAgentText("開新任務。用一句話告訴我你想完成什麼。");
// }

// ---------- 事件綁定 ----------
function send() {
  startPlan();
}

// function autoresize() {
//   const input = $("input");
//   input.style.height = "auto";
//   input.style.height = Math.min(input.scrollHeight, 120) + "px";
// }

$("sendBtn").addEventListener("click", send);
// $("input").addEventListener("input", autoresize);
// $("input").addEventListener("keydown", (e) => {
//   if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
// });
// $("newChatBtn").addEventListener("click", newChat);
// $("modeChipClear").addEventListener("click", exitReviseMode);

checkHealth();
setInterval(() => { if (!pollTimer) checkHealth(); }, 5000);