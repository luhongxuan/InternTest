// 點擊工具列圖示即開啟側邊欄（side panel 會持續存在，適合長時間任務）。
chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true })
    .catch((e) => console.warn("setPanelBehavior 失敗:", e));
});
