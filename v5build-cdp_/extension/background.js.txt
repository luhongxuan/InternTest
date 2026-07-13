/**
 * background.js — Service Worker
 *
 * 1. 點圖示開側邊欄
 * 2. 啟動 bridge_client（WebSocket 連線）
 *
 * Service Worker 在 MV3 可能隨時被終止，
 * bridge_client 的重連機制確保連線能自動恢復。
 */

"use strict";

// 點圖示開側邊欄
chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel
    .setPanelBehavior({ openPanelOnActionClick: true })
    .catch((e) => console.warn("setPanelBehavior 失敗:", e));
});

// 引入 bridge_client（透過 importScripts，Service Worker 方式）
importScripts("bridge_client.js");
