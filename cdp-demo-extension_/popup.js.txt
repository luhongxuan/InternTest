const logEl = document.getElementById('log');

// ========== Log 工具 ==========
function log(type, tag, msg) {
  const entry = document.createElement('div');
  entry.className = `log-entry ${type}`;
  entry.innerHTML = `<span class="tag">[${tag}]</span>${msg}`;
  logEl.appendChild(entry);
  logEl.scrollTop = logEl.scrollHeight;
}

function clearLog() {
  logEl.innerHTML = '';
  log('step', '等待', '點擊上方按鈕開始 demo');
}

// ========== 與 background.js 通訊 ==========

// 所有 demo 邏輯都在 background.js 裡跑（因為 chrome.debugger 只能在 service worker 用）
// popup 只負責發指令 + 顯示 log

function runDemo(demoName) {
  // 禁用所有按鈕
  document.querySelectorAll('.demo-btn').forEach(b => b.disabled = true);
  logEl.innerHTML = '';
  log('step', '開始', `正在執行 ${demoName}...`);

  let port;
  try {
    port = chrome.runtime.connect({ name: 'demo-log' });
  } catch (e) {
    log('error', '錯誤', 'Background service worker 未回應，請到 chrome://extensions 重新載入擴充功能');
    document.querySelectorAll('.demo-btn').forEach(b => b.disabled = false);
    return;
  }

  // 10 秒超時保護
  const timeout = setTimeout(() => {
    log('error', '超時', '超過 10 秒沒有回應，可能是 debugger 連接失敗。請確認沒有開啟 DevTools。');
    document.querySelectorAll('.demo-btn').forEach(b => b.disabled = false);
    try { port.disconnect(); } catch(e) {}
  }, 30000);

  port.onDisconnect.addListener(() => {
    clearTimeout(timeout);
    document.querySelectorAll('.demo-btn').forEach(b => b.disabled = false);
  });

  port.onMessage.addListener((msg) => {
    if (msg.type === 'log') {
      log(msg.level, msg.tag, msg.text);
    }
    if (msg.type === 'done') {
      clearTimeout(timeout);
      log('step', '完成', '✓ Demo 結束');
      document.querySelectorAll('.demo-btn').forEach(b => b.disabled = false);
      try { port.disconnect(); } catch(e) {}
    }
    if (msg.type === 'error') {
      clearTimeout(timeout);
      log('error', '錯誤', msg.text);
      document.querySelectorAll('.demo-btn').forEach(b => b.disabled = false);
      try { port.disconnect(); } catch(e) {}
    }
  });

  port.postMessage({ action: demoName });
}

// ========== 綁定按鈕 ==========
document.getElementById('demo1').addEventListener('click', () => runDemo('demo1'));
document.getElementById('demo2').addEventListener('click', () => runDemo('demo2'));
document.getElementById('demo3').addEventListener('click', () => runDemo('demo3'));
document.getElementById('clearLog').addEventListener('click', clearLog);
