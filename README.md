# AIOT 智慧垃圾分類桶 - 專案文件

## 專案簡介

本專案實作一個基於 AIOT 架構的智慧垃圾分類系統，整合影像辨識、音訊分析與多模態融合技術，實現自動化的垃圾分類與傾倒。系統分為三層：PC 運算層 (Inference Server)、Raspberry Pi 決策層 (Client) 與 ESP32 致動層 (Firmware)。

## 系統核心特色與演進

我們已經將垃圾桶系統進行了全方位的升級，從單一影像觸發與簡單歸檔，演進為高穩定、低延遲的智慧複合系統：
*   **多模態交叉融合 AI 模型**: 直接輸入影像與音訊頻譜至單一 `.keras` 模型，在網路內部進行跨模態特徵融合。
*   **Gemini 雲端備援** : 當本地信心值低於 `CONFIDENCE_THRESHOLD` 時，自動調用 Google Gemini Vision 進行思維鏈 (CoT) 輔助判斷；API 失敗時優雅降級回本地結果。
*   **複合觸發控制系統 (FSM Composite Trigger) ✅**: 樹莓派主控端採用生產級有限狀態機 (FSM)，支援 **Weight (重量)**、**Vision (影像動態)**、**IR (紅外線入口對射)** 三種觸發源，並在 `config.py` 中提供條件式啟用開關。
*   **單一串口共用與競態防丟機制 ✅**: 解決了串口 Port Busy 底層嚴重衝突，串口由 UART 連線共享給重量感測器；並引入全域佇列 `_shared_pending_events` 與非阻塞讀取，保證對入口物理事件 (`EVENT:INPUT_BLOCKED`) 的 100% 毫秒級無損捕獲。
*   **無偏見採集與側邊元資料歸檔 ✅**: Streamlit 標記面板預設 `index=None` 無偏置設計，防止自動標記污染；每次歸檔自動移送 JPG, WAV 並生成專屬 sidecar `.json` Metadata 描述檔（記錄重量、時間、觸發源與自訂備註描述）。
*   **互動式數據集瀏覽與一鍵導出 ✅**: 儀表板內嵌 **Dataset Explorer**，可切換類別、播放碰撞聲 Wav、預覽 JPG 與呈現 Metadata，提供一鍵永久刪除及「撤銷最近一次標記」防呆機制，並支援一鍵壓縮整個 `dataset/` 打包為 `.zip` WiFi 下載。
*   **全局代碼健壯性 (KeyError & TypeError 防護) ✅**: 徹底消除 Streamlit 按鈕 `width='stretch'` 引起的全體運行時崩潰，全面改用官方標準的 `use_container_width=True`；且在 DataFrame 歷史日誌表格解析中加入自動補全容錯，保證網頁 100% 穩定不崩潰。
*   **模組化專案結構**: 將 PC 端、Pi 端與 ESP32 端的程式碼徹底分離，提高維護性。

---

## 系統架構與檔案說明

本專案依照微服務與模組化概念，將目錄結構切分為以下主要區塊：

### 1. 💻 `pc_server/` (PC 運算層)
負責核心 AI 推論運算，接收感測資料並回傳分類結果。
*   **`app.py`**: 最新版 Inference Server。提供 `/predict` API 介面，載入雙輸入（影像+音訊頻譜）的 Keras 模型進行交叉融合推論，並整合 Gemini 備援與資料收集邏輯。
*   **`gemini_fallback.py`**: Gemini 雲端備援模組。封裝 CoT 提示策略、JSON 解析、重試與降級邏輯。
*   **`models/`**: 存放訓練好的 `.keras` 模型權重。
*   **`data/raw/`**: 生產資料收集目錄，依標籤分類儲存影像、音訊頻譜與元資料。
*   **`.env`**: 環境變數與金鑰配置檔（詳見下方參數說明）。
*   **`requirements.txt`**: PC 端專用的 Python 套件清單。

### 2. 🍓 `pi_client/` (Raspberry Pi 決策與控制層)
負責感測器控制、影像與音訊擷取與流程決策。
*   **`composite_trigger_controller.py`**: 核心生產級 FSM 複合觸發控制器，整合重量 (HX711) + 畫面幀差偵測 + IR 入口物理對射偵測的去抖動確認機制。
*   **`Streamlit.py`**: 最新版實時監控與數據集標記工具看板。整合 Live Dashboard、麥克風診斷、無偏見數據標記與詮釋元資料 Sidecar 儲存、Wav/JPG 聯合預覽 Explorer 與一鍵 ZIP 打包導出。
*   **`interactive_controller.py`**: 互動式測試控制 CLI 工具，支援 Picamera2 與手動觸發流程。
*   **`pc_client.py`**: 封裝與 PC Server 的 HTTP 通訊協定。
*   **`esp32_uart.py`**: 負責透過 UART 傳送控制指令與雙向狀態同步，支援主動事件監聽與全域佇列競態防護。
*   **`audio_processor.py`**: 輕量化音訊錄製與 Mel-spectrogram 純 Numpy 生成模組。

### 3. 🔌 `esp32_firmware/` (ESP32 致動層)
負責硬體作動控制，包含伺服馬達與實體開關的 C/C++ 韌體程式碼。

### 4. 🗄️ `legacy/` (歷史遺留區)
封存舊版的架構，作為學術參考與功能備用。
*   **`app_legacy.py`**: 舊版基於加權融合的伺服器主程式。
*   **`src/`**: 舊版獨立的視覺/聽覺推論引擎與加權邏輯引擎 (Late Fusion)。

---

## 安裝與執行指南

### 1. 環境準備 (PC 端)

請確保 Python 3.8+ 已安裝，並在專案根目錄下設定虛擬環境：

```bash
# 啟動虛擬環境 (Windows PowerShell)
.venv\Scripts\Activate.ps1

# 進入伺服器目錄並安裝依賴
cd pc_server
pip install -r requirements.txt
```

#### 1a. 環境變數設定 (.env)
在 `pc_server` 目錄中：
1. 將 `.env.example` 複製一份並重新命名為 `.env`。
2. 填寫以下參數：

    | 參數 | 說明 | 預設值 |
    |---|---|---|
    | `GOOGLE_API_KEY` | Google Gemini API 金鑰 (必填) | — |
    | `CONFIDENCE_THRESHOLD` | 低於此值觸發 Gemini 備援 | `0.50` |
    | `GEMINI_MODEL_NAME` | Gemini 模型名稱 | `gemini-2.0-flash` |
    | `DATA_COLLECTION` | 啟用生產資料收集 (`true`/`false`) | `false` |

### 2. Tailscale 網路設定 (強烈建議)
為簡化跨網域連線，建議使用 Tailscale：
1. 在 PC 與 Pi 上安裝 Tailscale 並登入綁定。
2. 記下 PC 的 Tailscale IP (例如 `100.85.67.115`)。
3. 於 `pi_client` 目錄下的 `.env` 檔案中，設定 `PC_SERVER_IP=您的_PC_Tailscale_IP`。

### 3. 啟動推論伺服器 (PC 端)

```bash
cd pc_server
python app.py
```
*   伺服器將啟動於 `0.0.0.0:5000`。
*   若使用 Tailscale，則 Pi 可透過 `100.x.x.x:5000` 存取。

### 4. 啟動控制程式 (Raspberry Pi 端)

1. **安裝依賴**: 
    ```bash
    pip install opencv-python pyserial requests numpy
    ```
2. **硬體連線**: 
    *   USB 相機 / Pi Camera 與麥克風。
    *   ESP32 (透過 USB TTL 線接上 Pi)。
3. **執行主程式**:
    ```bash
    python pi_client/interactive_controller.py
    ```
4. **操作**: 
    *   按 `Enter` 拍照、錄音並觸發推論。
    *   觀察 PC 端 Console 顯示的交叉融合 (Cross-Fusion) AI 推論結果。
    *   若信心值低於閾值，Console 會顯示 Gemini 備援啟動訊息。
    *   觀察 ESP32 伺服馬達作動。

---

## 生產資料收集

在 `.env` 中設定 `DATA_COLLECTION=true` 後，每次 `/predict` 呼叫都會將原始資料儲存至 `pc_server/data/raw/{label}/`：

```
data/raw/
  paper/
    20260506_020351_123456_img.jpg    ← 原始影像
    20260506_020351_123456_aud.bin    ← 音訊頻譜 (有提供時)
    20260506_020351_123456_meta.json  ← 元資料
  plastic/ ...
  general/ ...
  metal/ ...
```

元資料 (`_meta.json`) 欄位說明：

| 欄位 | 說明 |
|---|---|
| `label` | 最終分類標籤 |
| `confidence` | 最終信心值 |
| `is_gemini` | `true` 表示此標籤由 Gemini CoT 提供，品質較高 |
| `has_audio` | `false` 表示音訊欄位由影像替代，訓練時應注意 |
| `timestamp` | 推論時間戳記 (ISO 8601) |

---

## API 介面說明

### `POST /predict`
由 `pc_server/app.py` 提供。接收影像與音訊頻譜以進行交叉融合推論。

*   **Request Form-Data**：
    *   `image`: 影像二進位檔案
    *   `audio_spec`: 音訊頻譜二進位檔案

*   **Response JSON**:
    ```json
    {
      "label": "paper",
      "confidence": 0.95,
      "is_gemini": false,
      "reasoning": "Local cross-fusion inference sufficient.",
      "latency_ms": 42.5,
      "status": "success"
    }
    ```

    | 欄位 | 說明 |
    |---|---|
    | `label` | 分類結果: `paper` / `plastic` / `general` / `metal` |
    | `confidence` | 最終信心值 (0.0~1.0) |
    | `is_gemini` | `true` 表示本次由 Gemini 雲端備援提供結果 |
    | `reasoning` | Gemini 的 CoT 推理摘要 (本地推論時為預設文字) |
    | `latency_ms` | 本次推論總耗時 (毫秒) |

---

## 專題計畫對應

*   **架構設計**: 實作於 `app.py` 與模組化的前後端通訊。
*   **模型設計**: 採用最新的多模態交叉融合 (Cross-Fusion) 模型於 `models/best_multimodal_model.keras`。
*   **Hybrid Decision Gate**: 取代舊有的 Late Fusion 加權機制，目前統一由交叉融合模型直接輸出預測。
*   **Gemini CoT 備援** ✅: 已實作於 `pc_server/gemini_fallback.py`。當信心值低於 `CONFIDENCE_THRESHOLD` 時自動觸發，API 失敗則優雅降級回本地結果。
*   **資料集擴充** ✅: 已實作於 `app.py` 的 `save_sample()`。推論時同步收集有標籤資料，`is_gemini=true` 的樣本標籤品質最高。
*   **複合物理/軟體觸發閘 ✅**: 已在 `composite_trigger_controller.py` 中實作生產級 FSM 複合觸發器，整合紅外線對射 (IR)、重量感測 (Weight) 與影像幀差動態 (Vision) 條件式三合一觸發，保證了在各種光線與物體重量下的極致感應性能。
*   **詮釋詮釋元資料標記與導出系統 ✅**: 實作於 `Streamlit.py` (Tab 3)。包含 `index=None` 無偏見標記、sidecar `.json` Metadata 自動生成（含自訂描述、增量重量與觸發源記錄）、互動式預覽 Explorer，以及一鍵壓縮整個採集目錄並透過 WiFi 打包下載。
*   **UI 跨版本健壯防護 ✅**: 標準化 Streamlit 視窗按鈕排版為 `use_container_width=True`，並在 Live Dashboard 歷史 log 解析中注入 KeyError 補欄位防護，確保在不同 Streamlit 軟體版本與舊資料庫下維持 100% 不崩潰運行。