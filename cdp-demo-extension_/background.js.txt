// ================================================================
//  CDP Demo - Background Service Worker
//  
//  這個檔案是整個 demo 的核心。
//  它用 chrome.debugger API 直接發送 CDP 指令給瀏覽器，
//  跟 AI agent（Claude / Codex）操控瀏覽器的原理完全一樣。
//
//  chrome.debugger 就是 Chrome DevTools Protocol 的 JavaScript 封裝。
//  每一個 sendCommand() 呼叫都對應一個 CDP 指令。
// ================================================================

// ========== 工具函式 ==========

// 等待指定毫秒（讓你看清楚每一步在幹嘛）
function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

// 送 CDP 指令的封裝（核心中的核心）
function cdp(tabId, method, params = {}) {
  return new Promise((resolve, reject) => {
    chrome.debugger.sendCommand({ tabId }, method, params, (result) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else {
        resolve(result);
      }
    });
  });
}

// 連接 debugger 到指定 tab
function attach(tabId) {
  return new Promise((resolve, reject) => {
    chrome.debugger.attach({ tabId }, '1.3', () => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else {
        resolve();
      }
    });
  });
}

// 斷開 debugger
function detach(tabId) {
  return new Promise((resolve) => {
    chrome.debugger.detach({ tabId }, () => resolve());
  });
}

// ========== Demo 1：CDP 基本操作 ==========
// 展示：導航 → 查詢 DOM 節點 → 聚焦 → 模擬打字 → 點擊
async function runDemo1(tabId, send) {

  // --- 步驟 1：用 CDP 導航到測試頁面 ---
  send('cdp', 'CDP', '發送指令：Page.navigate → 導航到 DuckDuckGo');
  await cdp(tabId, 'Page.navigate', {
    url: 'https://duckduckgo.com'
  });
  // 等頁面載入
  send('action', '等待', '等候頁面載入完成...');
  await sleep(2500);

  // --- 步驟 2：用 CDP 查詢 DOM 節點 ---
  // 這就是 AI agent 在做的事：透過 CSS selector 或語意查詢找到元素
  send('cdp', 'CDP', '發送指令：Runtime.evaluate → 在 DOM 中找搜尋框');
  
  // Runtime.evaluate 可以在頁面上執行任意 JavaScript
  // 這裡我們用它來找到搜尋框並回傳它的資訊
  const findInput = await cdp(tabId, 'Runtime.evaluate', {
    expression: `
      (() => {
        const input = document.querySelector('input[name="q"]');
        if (!input) return JSON.stringify({ found: false });
        const rect = input.getBoundingClientRect();
        return JSON.stringify({
          found: true,
          tagName: input.tagName,
          name: input.name,
          placeholder: input.placeholder,
          x: Math.round(rect.x + rect.width / 2),
          y: Math.round(rect.y + rect.height / 2)
        });
      })()
    `,
    returnByValue: true
  });

  const inputInfo = JSON.parse(findInput.result.value);
  if (!inputInfo.found) {
    send('error', '錯誤', '找不到搜尋框，頁面可能還沒載入完');
    return;
  }

  send('result', '結果', 
    `找到元素：&lt;${inputInfo.tagName} name="${inputInfo.name}"&gt; ` +
    `位置：(${inputInfo.x}, ${inputInfo.y})`
  );

  await sleep(800);

  // --- 步驟 3：用 CDP 聚焦並模擬打字 ---
  // 先用 DOM.focus 或點擊來聚焦元素
  send('cdp', 'CDP', '發送指令：Input.dispatchMouseEvent → 點擊搜尋框');
  
  // 模擬滑鼠點擊（跟真人點擊一樣的事件序列）
  await cdp(tabId, 'Input.dispatchMouseEvent', {
    type: 'mousePressed',
    x: inputInfo.x,
    y: inputInfo.y,
    button: 'left',
    clickCount: 1
  });
  await cdp(tabId, 'Input.dispatchMouseEvent', {
    type: 'mouseReleased',
    x: inputInfo.x,
    y: inputInfo.y,
    button: 'left',
    clickCount: 1
  });

  await sleep(500);

  // 逐字輸入（讓你看到打字過程）
  const textToType = 'What is Chrome DevTools Protocol';
  send('cdp', 'CDP', `發送指令：Input.dispatchKeyEvent × ${textToType.length} → 逐字輸入`);
  send('action', '動作', `正在輸入："${textToType}"`);

  for (const char of textToType) {
    // 每個字元都是一組 keyDown + keyUp 事件
    await cdp(tabId, 'Input.dispatchKeyEvent', {
      type: 'keyDown',
      text: char,
      key: char,
    });
    await cdp(tabId, 'Input.dispatchKeyEvent', {
      type: 'keyUp',
      key: char,
    });
    // 模擬人類打字速度（50-100ms 之間隨機）
    await sleep(50 + Math.random() * 50);
  }

  await sleep(800);

  // --- 步驟 4：找到搜尋按鈕並點擊 ---
  send('cdp', 'CDP', '發送指令：Runtime.evaluate → 找到搜尋按鈕');
  
  const findButton = await cdp(tabId, 'Runtime.evaluate', {
    expression: `
      (() => {
        // 嘗試多種方式找按鈕（不同網站結構不同）
        const btn = document.querySelector('button[type="submit"]')
                 || document.querySelector('input[type="submit"]')
                 || document.querySelector('[aria-label="Search"]');
        if (!btn) return JSON.stringify({ found: false });
        const rect = btn.getBoundingClientRect();
        return JSON.stringify({
          found: true,
          tagName: btn.tagName,
          text: btn.textContent.trim().substring(0, 20),
          ariaLabel: btn.getAttribute('aria-label') || '',
          x: Math.round(rect.x + rect.width / 2),
          y: Math.round(rect.y + rect.height / 2)
        });
      })()
    `,
    returnByValue: true
  });

  const btnInfo = JSON.parse(findButton.result.value);
  
  if (btnInfo.found) {
    send('result', '結果', 
      `找到按鈕：&lt;${btnInfo.tagName}&gt; ` +
      `text="${btnInfo.text}" aria-label="${btnInfo.ariaLabel}" ` +
      `位置：(${btnInfo.x}, ${btnInfo.y})`
    );
    
    await sleep(500);
    send('cdp', 'CDP', '發送指令：Input.dispatchMouseEvent → 點擊搜尋按鈕');
    
    await cdp(tabId, 'Input.dispatchMouseEvent', {
      type: 'mousePressed',
      x: btnInfo.x,
      y: btnInfo.y,
      button: 'left',
      clickCount: 1
    });
    await cdp(tabId, 'Input.dispatchMouseEvent', {
      type: 'mouseReleased',
      x: btnInfo.x,
      y: btnInfo.y,
      button: 'left',
      clickCount: 1
    });
  } else {
    // 找不到按鈕就用 Enter 鍵代替
    send('action', '備案', '找不到按鈕，改用模擬 Enter 鍵送出');
    await cdp(tabId, 'Input.dispatchKeyEvent', {
      type: 'keyDown',
      key: 'Enter',
      code: 'Enter',
      windowsVirtualKeyCode: 13
    });
    await cdp(tabId, 'Input.dispatchKeyEvent', {
      type: 'keyUp',
      key: 'Enter',
      code: 'Enter',
      windowsVirtualKeyCode: 13
    });
  }

  await sleep(1000);
  send('result', '總結', 
    '整個流程用了 4 個 CDP domain：Page（導航）、Runtime（執行 JS 查詢 DOM）、Input（模擬鍵盤滑鼠）'
  );
}


// ========== Demo 2：讀取 Accessibility Tree ==========
// 展示：AI agent 實際看到的不是 HTML，而是這棵精簡的語意樹
async function runDemo2(tabId, send) {
  
  send('step', '說明', 
    'Accessibility Tree 是 DOM 的語意精簡版。AI agent 讀這個而不是讀原始 HTML。'
  );
  await sleep(500);

  // 啟用 Accessibility domain
  send('cdp', 'CDP', '發送指令：Accessibility.enable → 啟用無障礙功能');
  await cdp(tabId, 'Accessibility.enable');
  await sleep(300);

  // 取得完整的 accessibility tree
  send('cdp', 'CDP', '發送指令：Accessibility.getFullAXTree → 擷取完整 Accessibility Tree');
  
  let tree;
  try {
    tree = await cdp(tabId, 'Accessibility.getFullAXTree', { depth: 5 });
  } catch (e) {
    send('error', '錯誤', `無法取得 AX Tree：${e.message}。試試切換到一個有內容的分頁再執行。`);
    return;
  }

  const nodes = tree.nodes || [];
  send('result', '結果', `Accessibility Tree 共有 ${nodes.length} 個節點`);
  await sleep(300);

  // 過濾出可互動的元素（這是 AI agent 真正關心的）
  const interactable = nodes.filter(n => {
    const role = n.role?.value || '';
    return ['textbox', 'button', 'link', 'combobox', 'checkbox', 
            'radio', 'menuitem', 'tab', 'searchbox', 'slider'].includes(role);
  });

  send('result', '結果', `其中可互動的元素有 ${interactable.length} 個`);
  await sleep(300);

  send('step', '以下', '這就是 AI agent 實際會收到的元素列表 ↓');
  await sleep(200);

  // 顯示前 15 個可互動元素
  const toShow = interactable.slice(0, 15);
  for (const node of toShow) {
    const role = node.role?.value || '?';
    const name = node.name?.value || '(無名稱)';
    const desc = node.description?.value || '';
    
    let display = `<b>${role}</b> → "${name}"`;
    if (desc) display += ` (${desc})`;
    
    send('result', 'AX', display);
    await sleep(100);
  }

  if (interactable.length > 15) {
    send('step', '...', `還有 ${interactable.length - 15} 個元素未顯示`);
  }

  await sleep(300);
  send('result', '總結', 
    'AI 看到的是 role + name，不是 CSS class 或 DOM 結構。' +
    '所以不管網站怎麼改版，只要按鈕還叫 "搜尋"，AI 就能找到它。'
  );
}


// ========== Demo 3：DOM vs Accessibility 對比 ==========
async function runDemo3(tabId, send) {

  send('step', '說明', '對比原始 DOM 的節點數量 vs Accessibility Tree 的節點數量');
  await sleep(500);

  // 計算 DOM 節點數
  send('cdp', 'CDP', '發送指令：Runtime.evaluate → 計算 DOM 節點總數');
  const domCount = await cdp(tabId, 'Runtime.evaluate', {
    expression: `document.querySelectorAll('*').length`,
    returnByValue: true
  });
  const domTotal = domCount.result.value;
  send('result', 'DOM', `原始 DOM 節點總數：<b>${domTotal}</b> 個`);
  await sleep(300);

  // 計算可互動 DOM 元素
  send('cdp', 'CDP', '發送指令：Runtime.evaluate → 計算可互動 DOM 元素');
  const interactiveCount = await cdp(tabId, 'Runtime.evaluate', {
    expression: `
      document.querySelectorAll(
        'a, button, input, select, textarea, [role="button"], [role="link"], [tabindex]'
      ).length
    `,
    returnByValue: true
  });
  send('result', 'DOM', `其中可互動的 DOM 元素：<b>${interactiveCount.result.value}</b> 個`);
  await sleep(300);

  // 計算 Accessibility Tree 節點數
  send('cdp', 'CDP', '發送指令：Accessibility.getFullAXTree → 取得 AX Tree');
  await cdp(tabId, 'Accessibility.enable');
  
  let tree;
  try {
    tree = await cdp(tabId, 'Accessibility.getFullAXTree', { depth: 10 });
  } catch(e) {
    send('error', '錯誤', `AX Tree 取得失敗：${e.message}`);
    return;
  }
  
  const axNodes = tree.nodes || [];
  const axInteractable = axNodes.filter(n => {
    const role = n.role?.value || '';
    return ['textbox', 'button', 'link', 'combobox', 'checkbox',
            'radio', 'menuitem', 'tab', 'searchbox', 'slider'].includes(role);
  });

  send('result', 'AX', `Accessibility Tree 節點總數：<b>${axNodes.length}</b> 個`);
  await sleep(200);
  send('result', 'AX', `其中可互動的 AX 節點：<b>${axInteractable.length}</b> 個`);
  await sleep(500);

  // 計算壓縮比
  const ratio = ((1 - axNodes.length / domTotal) * 100).toFixed(1);
  send('step', '對比', `Accessibility Tree 比原始 DOM 精簡了約 <b>${ratio}%</b>`);
  await sleep(300);

  // 估算 token 數量
  const domTokenEstimate = Math.round(domTotal * 15); // 粗估每個 DOM 節點 ~15 token
  const axTokenEstimate = Math.round(axInteractable.length * 20); // 每個 AX 節點 ~20 token

  send('result', 'Token', 
    `如果把整個 DOM 送給 LLM：約 <b>${domTokenEstimate.toLocaleString()}</b> tokens（$$$）`
  );
  send('result', 'Token', 
    `只送 AX 可互動元素：約 <b>${axTokenEstimate.toLocaleString()}</b> tokens（便宜幾十倍）`
  );

  await sleep(300);
  send('result', '總結', 
    '這就是為什麼 Playwright MCP 用 Accessibility Tree 而不是原始 DOM。' +
    '資料量小 → LLM 處理快 → 成本低 → 精準度反而更高。'
  );
}


// ========== 連線處理 ==========
chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== 'demo-log') return;

  port.onMessage.addListener(async (msg) => {
    const send = (level, tag, text) => {
      try { port.postMessage({ type: 'log', level, tag, text }); } catch(e) {}
    };

    try {
      let tabId;

      if (msg.action === 'demo1') {
        // Demo 1 自己開新分頁（避免卡在 chrome:// 頁面）
        send('step', '準備', '正在開啟新分頁...');
        const newTab = await chrome.tabs.create({ url: 'about:blank', active: true });
        tabId = newTab.id;
        // 等新分頁準備好
        await sleep(500);
      } else {
        // Demo 2, 3 用當前分頁
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab) {
          port.postMessage({ type: 'error', text: '找不到活動分頁' });
          return;
        }
        // 檢查是否是 chrome:// 頁面
        if (tab.url && (tab.url.startsWith('chrome://') || tab.url.startsWith('edge://'))) {
          port.postMessage({ type: 'error', 
            text: '無法在 chrome:// 或 edge:// 頁面執行。請先切到一個普通網頁（例如 google.com）再試。' 
          });
          return;
        }
        tabId = tab.id;
      }

      // 連接 CDP debugger
      send('cdp', 'CDP', `正在連接 debugger 到 tab ${tabId}...`);
      await attach(tabId);
      send('action', '連接', '✓ CDP debugger 已連接（就像 AI agent 連接到瀏覽器）');
      await sleep(300);

      // 啟用必要的 CDP domain
      await cdp(tabId, 'Page.enable');
      await cdp(tabId, 'DOM.enable');

      // 執行對應的 demo
      if (msg.action === 'demo1') {
        await runDemo1(tabId, send);
      } else if (msg.action === 'demo2') {
        await runDemo2(tabId, send);
      } else if (msg.action === 'demo3') {
        await runDemo3(tabId, send);
      }

      // 斷開 debugger
      await detach(tabId);
      send('action', '斷開', 'CDP debugger 已斷開');
      port.postMessage({ type: 'done' });

    } catch (err) {
      port.postMessage({ type: 'error', text: err.message });
    }
  });
});
