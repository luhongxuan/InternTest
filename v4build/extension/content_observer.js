/**
 * content_observer.js
 *
 * 注入到目標頁面，負責：
 * 1. 收到 background.js 的 OBSERVE_PAGE 訊息 → 掃描 DOM 可互動元素 → 回傳 observation
 * 2. 收到 background.js 的執行命令 → 找到對應 element → 執行 click / type / key / scroll
 *
 * 不直接連 WebSocket；由 background.js 橋接 WebSocket ↔ content script。
 */

"use strict";

// ---------------------------------------------------------------------------
// 可互動元素選擇器
// ---------------------------------------------------------------------------
const INTERACTIVE_SELECTOR = [
  "a[href]",
  "button",
  "input:not([type=hidden])",
  "textarea",
  "select",
  "[role=button]",
  "[role=link]",
  "[role=tab]",
  "[role=menuitem]",
  "[role=textbox]",
  "[role=combobox]",
  "[role=listbox]",
  "[role=option]",
  "[role=checkbox]",
  "[role=radio]",
  "[contenteditable=true]",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

// 可輸入的 input type
const INPUTTABLE_INPUT_TYPES = new Set([
  "text", "email", "password", "search", "url", "tel", "number",
  "date", "time", "datetime-local", "month", "week", "color", "",
]);

/**
 * 取得元素最近的文字標籤（label / aria-labelledby / 前後文字）
 */
function getNearbyText(el) {
  // aria-labelledby
  const labelledBy = el.getAttribute("aria-labelledby");
  if (labelledBy) {
    const ref = document.getElementById(labelledBy);
    if (ref) return ref.innerText.trim().slice(0, 80);
  }
  // <label for=...>
  if (el.id) {
    const lbl = document.querySelector(`label[for="${el.id}"]`);
    if (lbl) return lbl.innerText.trim().slice(0, 80);
  }
  // 父元素裡最近的文字
  const parent = el.parentElement;
  if (parent) {
    const text = Array.from(parent.childNodes)
      .filter((n) => n.nodeType === Node.TEXT_NODE)
      .map((n) => n.textContent.trim())
      .filter(Boolean)
      .join(" ");
    if (text) return text.slice(0, 80);
  }
  return "";
}

/**
 * 掃描頁面可互動元素，回傳正規化的 element 陣列
 */
function collectInteractiveElements() {
  const candidates = document.querySelectorAll(INTERACTIVE_SELECTOR);
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const elements = [];
  let rawCount = 0;

  candidates.forEach((el) => {
    rawCount++;
    const rect = el.getBoundingClientRect();

    // 過濾不可見
    const isVisible =
      rect.width > 0 &&
      rect.height > 0 &&
      rect.bottom > 0 &&
      rect.right > 0 &&
      rect.top < vh &&
      rect.left < vw;
    if (!isVisible) return;

    const style = window.getComputedStyle(el);
    if (
      style.display === "none" ||
      style.visibility === "hidden" ||
      style.opacity === "0"
    )
      return;

    const tag = el.tagName.toLowerCase();
    const role =
      el.getAttribute("role") ||
      (tag === "input" ? el.type || "text" : "") ||
      (tag === "a" ? "link" : "") ||
      tag;

    const isInput =
      tag === "textarea" ||
      el.getAttribute("contenteditable") === "true" ||
      (tag === "input" && INPUTTABLE_INPUT_TYPES.has((el.type || "").toLowerCase()));

    const isClickable =
      tag === "button" ||
      tag === "a" ||
      el.onclick !== null ||
      el.getAttribute("role") !== null ||
      style.cursor === "pointer";

    // elementFromPoint 遮擋判斷（簡易版）
    const cx = Math.round(rect.left + rect.width / 2);
    const cy = Math.round(rect.top + rect.height / 2);
    let occluded = false;
    try {
      const topEl = document.elementFromPoint(cx, cy);
      occluded = topEl !== null && topEl !== el && !el.contains(topEl);
    } catch (_) {}

    // 元素文字
    const text = (el.innerText || el.value || "").trim().slice(0, 120);

    elements.push({
      element_id: `el_${elements.length}`,
      tag,
      role,
      text,
      label: (el.getAttribute("aria-label") || "").slice(0, 80),
      aria_label: (el.getAttribute("aria-label") || "").slice(0, 80),
      placeholder: (el.getAttribute("placeholder") || "").slice(0, 80),
      title: (el.getAttribute("title") || "").slice(0, 80),
      bounds: {
        x: Math.round(rect.left),
        y: Math.round(rect.top),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
      visible: true,
      enabled: !el.disabled,
      clickable: isClickable || !isInput,
      inputtable: isInput,
      nearby_text: getNearbyText(el),
      occluded,
    });
  });

  return { elements, rawCount };
}

// ---------------------------------------------------------------------------
// 依 element_id 找 DOM 元素（在本次 observation 回傳的清單裡對應）
// ---------------------------------------------------------------------------
let _lastElements = [];   // 保留最近一次 observation 的元素，供執行時索引

function findDomElement(elementId) {
  const idx = parseInt(elementId.replace("el_", ""), 10);
  if (Number.isNaN(idx)) return null;
  const candidates = document.querySelectorAll(INTERACTIVE_SELECTOR);
  const visible = [];
  candidates.forEach((el) => {
    const rect = el.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) visible.push(el);
  });
  return visible[idx] || null;
}

// ---------------------------------------------------------------------------
// Action 執行
// ---------------------------------------------------------------------------

function dispatchInputEvents(el) {
  ["input", "change"].forEach((type) => {
    el.dispatchEvent(new Event(type, { bubbles: true }));
  });
}

function executeClickElement(elementId) {
  const el = findDomElement(elementId);
  if (!el) return { ok: false, error: `找不到元素 element_id=${elementId}` };
  el.scrollIntoView({ behavior: "instant", block: "center" });
  el.focus();
  el.click();
  return { ok: true, tag: el.tagName.toLowerCase() };
}

function executeTypeText(text, elementId) {
  let el = elementId ? findDomElement(elementId) : document.activeElement;
  if (!el || el === document.body) return { ok: false, error: "找不到可輸入元素" };
  el.focus();
  if (el.tagName.toLowerCase() === "input" || el.tagName.toLowerCase() === "textarea") {
    el.value = (el.value || "") + text;
    dispatchInputEvents(el);
  } else if (el.getAttribute("contenteditable") === "true") {
    el.textContent = (el.textContent || "") + text;
    dispatchInputEvents(el);
  } else {
    return { ok: false, error: "目標元素不可輸入" };
  }
  return { ok: true, typed_length: text.length };
}

function executePressKey(key) {
  const target = document.activeElement || document.body;
  ["keydown", "keyup"].forEach((type) => {
    target.dispatchEvent(new KeyboardEvent(type, { key, bubbles: true, cancelable: true }));
  });
  return { ok: true, key };
}

function executeScroll(amount) {
  window.scrollBy({ top: -amount, behavior: "smooth" });
  return { ok: true, amount };
}

// ---------------------------------------------------------------------------
// 訊息監聽（來自 background.js）
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  const { command_type, params = {} } = msg;

  if (command_type === "get_page_observation") {
    // 截圖由 background.js 用 chrome.tabs.captureVisibleTab 取，
    // content script 只回傳 DOM observation。
    const { elements, rawCount } = collectInteractiveElements();
    _lastElements = elements;
    sendResponse({
      page: {
        url: location.href,
        title: document.title,
      },
      viewport: {
        width: window.innerWidth,
        height: window.innerHeight,
        device_scale_factor: window.devicePixelRatio || 1,
      },
      elements,
      raw_elements_count: rawCount,
    });
    return true; // 非同步
  }

  if (command_type === "click_element") {
    sendResponse(executeClickElement(params.element_id));
    return true;
  }

  if (command_type === "type_text") {
    sendResponse(executeTypeText(params.text, params.element_id));
    return true;
  }

  if (command_type === "press_key") {
    sendResponse(executePressKey(params.key));
    return true;
  }

  if (command_type === "scroll") {
    sendResponse(executeScroll(params.amount));
    return true;
  }

  // 未知命令
  sendResponse({ ok: false, error: `content_observer 不支援 command_type=${command_type}` });
  return true;
});
