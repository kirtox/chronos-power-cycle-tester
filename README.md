# Chronos — Power Cycle Test & Recovery Verifier

自動化觸發並驗證 Windows 的 Reboot / Sleep (Modern Standby) / Hibernate 電源循環測試：每輪都會喚醒系統、比對 System log 的電源事件是否乾淨、比對 Device Manager 裝置狀態是否與測試前一致，記錄 pass/fail 並可匯出報告。另外附加 System log 即時事件追蹤（自訂 Level / Source / Event ID 篩選）與 Device Manager 狀態比對功能。

> 完整的設計決策與討論紀錄見 [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md)。

## 功能

- **Power Cycle Test（主要功能）**：自動化觸發 Reboot / Sleep(Modern Standby) / Hibernate 循環，每輪都會：
  1. 透過工作排程器「喚醒電腦執行此工作」機制確保系統會被喚醒
  2. 喚醒/重開機後，查詢 System log 的 `Kernel-Power` / `Power-Troubleshooter` 事件驗證本輪是否乾淨完成（偵測 Event 41 未正常關機等異常）
  3. 比對 Device Manager Baseline 是否一致
  4. 記錄 pass/fail 結果，可匯出報告
- **Device Manager Baseline（附加功能）**：可勾選要追蹤的裝置（例如 Bluetooth / Wi-Fi adapter），拍攝狀態快照，之後可手動或自動（偵測到 reboot 後）比對目前狀態是否與 Baseline 一致。
- **System Log 事件追蹤（附加功能）**：用 `EvtSubscribe` 即時監控 System log，依 Level / Source(Provider) / Event ID 自由組合篩選條件（同欄位 OR，跨欄位 AND）；用 Bookmark 記錄追蹤進度，重啟後自動從斷點接續；符合條件立即跳出系統匣通知；記錄存入本機 SQLite，可在 UI 檢視或匯出 CSV。
- **開機自動啟動**：UI 勾選後透過工作排程器（Logon trigger）自動註冊/移除，確保 Power Cycle Test 在 Reboot 循環後能自動恢復。

## 系統需求

- Windows 10/11
- Python 3.10+（開發/打包環境）

## 安裝（開發環境）

```powershell
# 建立虛擬環境
python -m venv .venv

# 安裝套件
.\.venv\Scripts\pip.exe install -r requirements.txt

# 完成 pywin32 的 post-install 設定（登錄 COM 等，只需執行一次）
.\.venv\Scripts\python.exe .\.venv\Scripts\pywin32_postinstall.py -install
```

## 執行

```powershell
.\.venv\Scripts\python.exe -m chronos.main
```

啟動後主視窗會開啟（同時建立系統匣圖示），分成三個分頁：

### 1. Event Tracking

- **Level**：勾選要追蹤的事件等級（Critical / Error / Warning / Information / Verbose）
- **Source**：按「重新整理」自動掃描 System log 中出現過的 Provider，勾選要追蹤的來源
- **Event ID**：用逗號分隔輸入要追蹤的事件 ID（例如 `41,1,6008`）
- 按「開始追蹤」啟動 `EvtSubscribe`；符合條件的事件會即時顯示在右側表格並跳出系統匣通知
- 可勾選「開機自動啟動」，讓工具在重開機後自動恢復追蹤
- 「匯出 CSV」可將目前記錄的事件匯出

### 2. Device Baseline

- 勾選要追蹤的裝置（預設列出 Net / Bluetooth 類別裝置）
- 「拍攝 Baseline」會記錄目前勾選裝置的狀態
- 「立即比對」會將目前裝置狀態與最新 Baseline 比對，列出差異（狀態改變、Error Code 改變、裝置消失等）
- 當工具偵測到系統 reboot 後，也會自動執行一次比對

### 3. Power Cycle Test

- 勾選要測試的循環類型（Reboot / Sleep / Hibernate）；不支援或未啟用的選項會灰掉
  - 若 Hibernate 未啟用，可按「啟用 Hibernate」，會跳出一次 UAC 提示執行 `powercfg /hibernate on`
- 設定總輪數、喚醒延遲時間、恢復後穩定等待秒數、失敗是否停止、執行模式（每種類型各跑 N 次 / 混合大迴圈）
- 按「開始 Power Cycle Test」啟動；過程中系統會實際進入 Sleep/Hibernate 或重開機，請留意**手邊工作先儲存**
- 結果會即時顯示在表格中，可匯出報告

> ⚠️ **注意**：Sleep / Hibernate 觸發後，呼叫執行緒會跟著系統一起暫停，直到喚醒才會繼續執行，這是正常現象。Reboot 類型則會直接重開機，工具靠「開機自動啟動」機制在重開機後自動恢復測試進度（存放在 `%LOCALAPPDATA%\Chronos\power_cycle_state.json`）。

## 資料存放位置

所有設定、Bookmark、資料庫、Log 都存在：

```
%LOCALAPPDATA%\Chronos\
├── config.json              # 篩選條件 / 裝置選擇 / Power Cycle Test 參數
├── bookmark.xml              # EvtSubscribe 續傳用的 Bookmark
├── chronos.db                 # SQLite：符合條件的事件、裝置快照、Power Cycle Test 結果
├── chronos.log                # 執行 log
└── power_cycle_state.json    # Power Cycle Test 進行中的狀態（測試結束後會清除）
```

## 打包成 exe

```powershell
.\build.ps1
```

會產生單一執行檔 `dist\Chronos.exe`（PyInstaller `--onefile --windowed`）。首次啟動會比一般 Python 執行稍慢（需要解壓縮到暫存目錄），屬正常現象。

## 權限說明

- 一般追蹤、Device Baseline、觸發 Reboot/Sleep、建立屬於自己的工作排程器工作，皆不需要系統管理員權限。
- 只有在這台機器**尚未啟用 Hibernate** 時，啟用它才需要一次 UAC 提示（`powercfg /hibernate on`）。

## 已知限制

- Power Cycle Test 針對 Modern Standby 的驗證目前僅依賴 System log 的 `Kernel-Power` 506/507 事件，尚未整合 `powercfg /sleepstudy` 報告（詳見 DESIGN_DECISIONS.md 的待辦事項）。
- Source（Provider）清單是掃描最近的 System log 記錄取得，若該 Provider 很久沒有記錄過事件，可能不會出現在清單中，可手動多掃描幾次或擴大掃描筆數。
