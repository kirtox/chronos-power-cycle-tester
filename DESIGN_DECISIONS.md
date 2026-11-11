# Chronos — 設計決策紀錄

> 本文件記錄專案開發前 grilling 討論中確認的所有架構決策，供後續實作/接續對話時快速回顧上下文，不需要重新討論一遍。
>
> 專案命名沿革：最初以 Event Tracking 為主要需求開發，開發中期目的調整為以 **Power Cycle Test** 為主要功能，Event Tracking / Device Baseline 成為附加功能，因此專案改名為 `Chronos`（repo 名：`chronos-power-cycle-tester`）。

## 1. 核心需求

- 追蹤 Windows Event Viewer → Windows Logs → System 的事件
- 可自由選擇要 trace 的 Level / Source(Provider) / Event ID
- 符合條件時記錄下來並跳出提示
- 需處理追蹤過程中發生 power cycle（Sleep/Hibernate/Reboot）後，如何讓工具恢復到原本的追蹤狀態
- 提供簡單 UI 設定 filter 條件、顯示 filter 後的結果
- 用 PyInstaller 打包成 exe
- 額外需求：監控 Device Manager 中指定裝置（如 Bluetooth/WiFi adapter）在 power cycle 前後狀態是否一致；並能主動觸發 Power Cycle Test（Reboot / Sleep(Modern Standby) / Hibernate）自動化跑多輪驗證

## 2. Event Tracking 架構決策

| 決策點 | 結論 | 理由 |
|---|---|---|
| 擷取方式 | **`EvtSubscribe`** 即時訂閱，而非 polling | 低延遲、原生支援 bookmark 續傳，效能較好 |
| Reboot 續傳 | 用 `EvtCreateBookmark` 存檔；重啟後讀 bookmark 從斷點接續，並回溯補齊離線期間漏掉的事件 | 不漏記，且不用自己維護 RecordId 游標 |
| 第一次執行（無 bookmark） | 只追蹤「之後」新事件，**不回溯**安裝前的歷史 | 避免第一次啟動就被歷史事件灌爆通知 |
| Filter 邏輯 | 單一 Filter 組合：Level / Source / Event ID 三者 **AND**，同欄位內 **OR** | 可直接轉成 XPath query 交給 Event Log service 端過濾，效能好；滿足原始需求不需要更複雜的多規則系統 |
| Source 清單 | 自動偵測 System log 中出現過的 Provider，下拉多選（可重新整理） | 避免手動打錯 Provider 全名 |
| 通知方式 | PyQt5 `QSystemTrayIcon.showMessage`（系統匣 Balloon） | 內建、不卡成堆彈窗、可背景執行 |
| 記錄儲存 | **SQLite**（可匯出 CSV） | 可查詢/排序/篩選，重啟後資料不遺失 |
| 資料存放路徑 | `%LOCALAPPDATA%\Chronos\`（config、bookmark、db 都放這） | 不受 exe 執行路徑權限影響 |
| UI 框架 | **PyQt5**（需留意 GPL 授權，若未來要散布/商用需注意） | 使用者偏好 |
| 開機自動啟動 | UI 勾選開關，透過 Task Scheduler（Logon trigger）自動註冊/移除 | 重開機後自動恢復追蹤，不用人工介入 |
| 打包 | PyInstaller **`--onefile --windowed`** | 單一 exe 方便散布；windowed 避免背景跳黑色 console |
| 權限需求 | App 全程**一般使用者權限**即可（讀 System log 不需要 admin） | 符合最小權限原則 |

## 3. Device Manager Baseline 監控

| 決策點 | 結論 | 理由 |
|---|---|---|
| 監控方式 | 用 **WMI (`Win32_PnPEntity`)** 拍 Baseline 快照（Status / ConfigManagerErrorCode / 是否存在），而非即時裝置變化監聽（`WM_DEVICECHANGE`） | 需求是「驗證 power cycle 後有沒有恢復原狀」，不需要抓拔插瞬間，用輪詢快照比對就夠，複雜度低很多 |
| 裝置清單 | 跟 Source 清單一樣，即時從這台機器的 Device Manager 讀取讓使用者勾選，**不寫死裝置名稱** | 裝置友善名稱會因驅動版本/OEM/機器而不同（已實測驗證，詳見下方「已驗證事實」） |
| 比對時機 | 開始追蹤時拍 Baseline；偵測到 reboot/power-cycle 後自動比對一次；另提供手動「立即比對」按鈕 | 跟既有的 reboot 偵測機制共用，不用額外背景輪詢 |

## 4. Power Cycle Test

| 決策點 | 結論 | 理由 |
|---|---|---|
| 支援的循環類型 | **Reboot、Sleep (Modern Standby)、Hibernate**（可複選） | 使用者需求 |
| 支援偵測 | 跑測試前用 `powercfg /a` 偵測機器實際支援的睡眠狀態，不支援的選項灰掉 | 避免選到機器跑不動的模式 |
| Sleep/Hibernate 喚醒機制 | **工作排程器「喚醒電腦執行此工作」**，一次性任務，用完即刪 | 純軟體層面設定，不用碰 BIOS，相容性較一致 |
| 「真的有睡著嗎」驗證 | 排程喚醒**只保證喚醒時間，不保證真的有睡著**（呼叫 `SetSuspendState` 的執行緒本身也會被凍結，無法自我檢查）。驗證方式：喚醒後回頭查 System log 的 `Kernel-Power` / `Power-Troubleshooter` 事件，包含判斷 **Event ID 41（未正常關機/意外斷電）** 當作失敗訊號 | 需求方確認的折衷方案；具體 Event ID 細節會在實作時用這台機器實測驗證，不憑印象硬寫死 |
| 各類型驗證把握度 | Reboot ~95%、Hibernate ~85%、Sleep ~85%、Modern Standby ~85%（實測後上修，見第 7 節） | `Kernel-Power` 506/507 在這台機器上記錄完整，比原先預期可靠 |
| Modern Standby 加強驗證 | `powercfg /sleepstudy` 報告解析 —— **已決議暫不實作**，先以 System log 驗證為主 | 使用者決定先緩著，之後可能再加 |
| 失敗處理 | **預設失敗即停止**（標示第幾輪/原因），提供「忽略失敗繼續跑」勾選選項 | 保留失敗當下現場方便人工排查 |
| Hibernate 權限 | App 本身一般權限執行；若 `powercfg /a` 顯示 Hibernate 未啟用，才跳一次 UAC 執行 `powercfg /hibernate on` | 符合最小權限原則，不用整個 App 常駐 admin |
| 測試參數（UI 可設定） | 總輪數 N、喚醒延遲時間、恢復後穩定等待時間 | — |
| 執行模式 | **預設「每種類型各跑 N 次」**（依序跑完一種類型才換下一種），可切換成「混合大迴圈跑 N 輪（隨機/輪流挑類型）」 | 使用者指定預設值 |
| 結果儲存 | SQLite 新增 `power_cycle_test` 表（類型、開始/結束時間、pass/fail、失敗原因），可匯出報告（CSV/簡易 HTML） | 跟既有儲存機制一致 |

## 5. 已驗證事實（在目標機器上實測）

在這台開發機器（`C:\Python\chronos-power-cycle-tester` 所在機器）上用 `Get-PnpDevice` 實測驗證：

- `Intel(R) Wireless Bluetooth(R)` ✅ 確實存在於這台機器
- `Intel(R) Wireless Dual Bluetooth(R)` ❌ **不存在**，這台機器查無此裝置名稱（可能是跟 Wi-Fi 側的 `Dual Band Wireless-AC` 命名搞混）
- `Intel(R) Wi-Fi 6 AX201 160MHz`（注意大小寫是 `MHz` 不是 `Mhz`）✅ 存在

> ⚠️ 裝置友善名稱因機器/驅動版本而異，工具設計上一律**即時偵測，不寫死字串**，上面只是這次 grilling 過程中順手驗證的個案記錄。

## 6. 檔案結構（規劃）

```
chronos-power-cycle-tester/
├── chronos/
│   ├── __init__.py
│   ├── main.py                  # 進入點（單一實例檢查、初始化 DB、啟動 UI）
│   ├── paths.py                 # %LOCALAPPDATA%\Chronos 底下各檔案路徑
│   ├── event_watcher.py         # EvtSubscribe + bookmark 管理 + XPath query 組裝
│   ├── device_baseline.py       # WMI 裝置快照 + 比對
│   ├── power_cycle.py           # Reboot/Sleep/Hibernate 觸發 + 喚醒排程 + 驗證
│   ├── storage.py               # SQLite 讀寫、CSV/報告匯出
│   ├── providers.py             # System log 出現過的 Provider 偵測
│   ├── autostart.py             # Task Scheduler 開機自動啟動
│   ├── wake_scheduler.py        # 一次性喚醒工作（WakeToRun XML）建立/刪除
│   ├── config.py                # 設定存讀 (JSON)
│   └── ui/
│       ├── main_window.py       # 主視窗（Event Tracking / Device Baseline / Power Cycle Test 三分頁）
│       └── tray.py              # 系統匣 + balloon 通知
├── run.py                        # PyInstaller 進入點包裝
├── requirements.txt              # pywin32, PyQt5, wmi
├── requirements-dev.txt          # pyinstaller
├── build.ps1                     # 打包腳本
├── DESIGN_DECISIONS.md           # 本檔案
└── README.md
```

> 註：Device Baseline / Power Cycle Test 的 UI 最終合併寫在 `ui/main_window.py` 的分頁中，沒有拆成獨立的 `device_panel.py` / `power_cycle_panel.py`，避免過早拆分增加不必要的檔案。

## 7. 實作階段已驗證的 Power Cycle 事件 ID（在開發機器上實測）

- `Kernel-Power` Event 41：未正常關機/意外斷電（失敗訊號）
- `Kernel-Power` Event 42：進入睡眠
- `Kernel-Power` Event 107：由睡眠恢復
- `Kernel-Power` Event 109：kernel power manager 發起關機/重開機轉換（`Action` 欄位可見是否為 `Power Action Reboot`）
- `Kernel-Power` Event 506 / 507：進入／離開 Modern Standby（**比原先預期更可靠**，這台機器上有完整記錄，Modern Standby 驗證信心度可上修至 ~85%）
- `Power-Troubleshooter` Event 1：由低電力狀態恢復，`EventData` 內含結構化欄位 `SleepTime` / `WakeTime` / `SleepDuration` / `TargetState` / `WakeSourceType` 等，可直接解析 XML 取得（比解析本地化訊息文字可靠）

對應實作：[chronos/power_cycle.py](chronos/power_cycle.py)

## 8. 尚未決議 / 待實作時確認

- Modern Standby 的 `powercfg /sleepstudy` 報告解析（暫緩，目前靠 System log 506/507 + Power-Troubleshooter 1 已有不錯的信心度）

