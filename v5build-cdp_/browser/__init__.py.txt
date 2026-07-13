"""Browser CDP / DOM 操作層。

包含：
- BrowserObservationProvider：透過 WebSocket bridge 取得頁面觀察資料
- BrowserBridgeManager：管理與 Extension 的 WebSocket 連線
- BrowserActionExecutor：透過 WebSocket 在瀏覽器執行 action
"""
