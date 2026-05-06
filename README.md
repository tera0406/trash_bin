# AIOT 智慧垃圾分類桶 - 專案文件

## 專案簡介

本專案實作一個基於 AIOT 架構的智慧垃圾分類系統，整合影像辨識、音訊分析與多模態融合技術，實現自動化的垃圾分類與傾倒。系統分為三層：PC 運算層 (Inference Server)、Raspberry Pi 決策層 (Client) 與 ESP32 致動層 (Firmware)。

## 系統核心特色與演進

我們已經將多模態融合推論架構從舊版的「加權後融合 (Late Fusion)」升級為更先進的**「交叉融合 (Cross-Fusion)」**，並整合完整的備援與資料收集機制：
*   **多模態交叉融合 AI 模型**: 直接輸入影像與音訊頻譜至單一 `.keras` 模型，在網路內部進行跨模態特徵融合。
*   **Gemini 雲端備援** : 當本地信心值低於 `CONFIDENCE_THRESHOLD` 時，自動調用 Google Gemini Vision 進行思維鏈 (CoT) 輔助判斷；API 失敗時優雅降級回本地結果。
*   **生產資料收集** : 推論時可同步將影像、音訊頻譜與元資料（含標籤品質標記）儲存至 `data/raw/`，持續擴充訓練資料集。
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
*   **`pi_remote_controller.py`**: 主要執行腳本，整合相機拍照、錄音、PC 連線推論、UART 致動器控制。
*   **`pc_client.py`**: 封裝與 PC Server 的 HTTP 通訊協定。
*   **`esp32_uart.py`**: 負責透過 UART 傳送控制指令給 ESP32。

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
3. 修改 `pi_client/pi_remote_controller.py` 內的 `PC_SERVER_IP` 變數為上述 IP。

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