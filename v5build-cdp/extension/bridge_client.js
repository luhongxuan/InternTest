/**
 * bridge_client.js  — background service worker
 *
 * 修正：getActiveTabId() 改成追蹤「最後活躍的一般網頁分頁」，
 * 排除 Extension 自身頁面（chrome-extension://、chrome://、about:）。
 * 這樣即使 side panel 取得焦點，目標分頁 id 仍然正確。
 */

"use strict";

const WS_URL = "ws://127.0.0.1:8000/ws/browser";
const RECONNECT_DELAY_MS_INITIAL = 2000;
const RECONNECT_DELAY_MS_MAX = 30000;

let ws = null;
let reconnectDelay = RECONNECT_DELAY_MS_INITIAL;
let isConnecting = false;

// ---------------------------------------------------------------------------
// 追蹤目標分頁（排除 Extension 自身頁面）
// ---------------------------------------------------------------------------
let _targetTabId = null;   // 最後活躍的一般網頁分頁

function _isRegularTab(url) {
  if (!url) return false;
  return !url.startsWith("chrome-extension://") &&
         !url.startsWith("chrome://") &&
         !url.startsWith("about:") &&
         !url.startsWith("edge://");
}

// 分頁切換時更新目標
chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  try {
    const tab = await chrome.tabs.get(tabId);
    if (_isRegularTab(tab.url)) {
      _targetTabId = tabId;
      console.log("[Bridge] 目標分頁更新:", tabId, tab.url);
    }
  } catch (_) {}
});

// 分頁 URL 更新時（導航）也更新
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete" && _isRegularTab(tab.url)) {
    if (tabId === _targetTabId) {
      console.log("[Bridge] 目標分頁重新載入完成:", tab.url);
    }
  }
});

// 分頁關閉時清掉 id，避免送到已關閉的分頁
chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId === _targetTabId) _targetTabId = null;
});

async function getTargetTabId() {
  // 若已有追蹤的目標分頁，直接用
  if (_targetTabId !== null) {
    try {
      const tab = await chrome.tabs.get(_targetTabId);
      if (_isRegularTab(tab.url)) return _targetTabId;
    } catch (_) {
      _targetTabId = null;
    }
  }
  // fallback：查所有視窗裡最後活躍的一般分頁
  const tabs = await chrome.tabs.query({ active: true });
  for (const t of tabs) {
    if (_isRegularTab(t.url)) {
      _targetTabId = t.id;
      return t.id;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// 截圖
// ---------------------------------------------------------------------------
async function captureScreenshot(tabId) {
  try {
    const tab = await chrome.tabs.get(tabId);
    const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "png" });
    return dataUrl.split(",")[1] || "";
  } catch (err) {
    console.warn("[Bridge] 截圖失敗:", err);
    return "";
  }
}

// ---------------------------------------------------------------------------
// 轉發命令給 content_observer.js
// ---------------------------------------------------------------------------
async function forwardToContentScript(tabId, commandType, params) {
  console.log("[Bridge] forwardToContentScript tabId=", tabId, "cmd=", commandType);
  return new Promise((resolve) => {
    chrome.tabs.sendMessage(
      tabId,
      { command_type: commandType, params },
      (response) => {
        if (chrome.runtime.lastError) {
          const errMsg = chrome.runtime.lastError.message || "unknown error";
          // content script 未注入時最常見："Could not establish connection"
          console.error(
            `[Bridge] sendMessage 失敗 tabId=${tabId} cmd=${commandType}: ${errMsg}`
          );
          console.error("[Bridge] 請確認目標頁面已重新整理（F5）以注入 content script");
          resolve({ ok: false, error: errMsg });
        } else {
          resolve(response || { ok: false, error: "content script 無回應" });
        }
      }
    );
  });
}

// ---------------------------------------------------------------------------
// 處理來自 Python 的命令
// ---------------------------------------------------------------------------
async function handleCommand(msg) {
  console.log("[Bridge] handleCommand received:", msg.command_type);
  const { command_id, command_type, params = {} } = msg;
  let result = {};

  try {
    const tabId = await getTargetTabId();
    if (!tabId) {
      const err = "找不到目標分頁，請先在瀏覽器開啟目標網頁";
      console.error("[Bridge]", err);
      result = { ok: false, error: err };
    } else if (command_type === "get_page_observation") {
      console.log("[Bridge] get_page_observation tabId=", tabId);
      const [domObs, screenshotB64] = await Promise.all([
        forwardToContentScript(tabId, "get_page_observation", {}),
        captureScreenshot(tabId),
      ]);
      result = { ...domObs, screenshot_base64: screenshotB64 };
      console.log(
        "[Bridge] observation elements=",
        result.elements?.length ?? "?",
        "url=", result.page?.url ?? "?"
      );
    } else {
      result = await forwardToContentScript(tabId, command_type, params);
    }
  } catch (err) {
    console.error("[Bridge] handleCommand 例外:", err);
    result = { ok: false, error: String(err) };
  }

  return { command_id, result };
}

// ---------------------------------------------------------------------------
// WebSocket 連線管理
// ---------------------------------------------------------------------------
function connect() {
  if (isConnecting || (ws && ws.readyState === WebSocket.OPEN)) return;
  isConnecting = true;
  console.log("[Bridge] 嘗試連線到", WS_URL);

  try {
    ws = new WebSocket(WS_URL);
  } catch (err) {
    console.warn("[Bridge] WebSocket 建立失敗:", err);
    isConnecting = false;
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    console.log("[Bridge] WebSocket 已連線");
    reconnectDelay = RECONNECT_DELAY_MS_INITIAL;
    isConnecting = false;
    chrome.runtime.sendMessage({ kind: "bridge_status", connected: true }).catch(() => {});
  };

  ws.onmessage = async (event) => {
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch {
      console.warn("[Bridge] 收到非 JSON 訊息:", event.data);
      return;
    }
    const response = await handleCommand(msg);
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(response));
    }
  };

  ws.onerror = (err) => console.warn("[Bridge] WebSocket 錯誤:", err);

  ws.onclose = () => {
    console.log("[Bridge] WebSocket 中斷");
    isConnecting = false;
    ws = null;
    chrome.runtime.sendMessage({ kind: "bridge_status", connected: false }).catch(() => {});
    scheduleReconnect();
  };
}

function scheduleReconnect() {
  setTimeout(() => {
    reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_DELAY_MS_MAX);
    connect();
  }, reconnectDelay);
}

connect();

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.kind === "get_bridge_status") {
    sendResponse({ connected: ws !== null && ws.readyState === WebSocket.OPEN });
    return true;
  }
});
