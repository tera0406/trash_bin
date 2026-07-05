# Pi Controller Layer - 層級 2: Raspberry Pi 系統控制

## 硬體限制

- **硬體**: Raspberry Pi (建議 Pi 4 或更新版本)
- **作業系統**: Raspberry Pi OS (Linux)
- **GPIO**: 用於感測器輸入
- **UART**: 用於與 ESP32 通訊
- **網路**: 用於與 PC 推論伺服器通訊

## 軟體職責

### 核心任務

1. **控制器 (Controller) 邏輯**
   - 接收使用者輸入或感測器訊號 [cite: 49]
   - 協調相機拍攝與資料傳輸
   - 處理錯誤恢復流程 (RECOVER 狀態) [cite: 47, 91, 324]

2. **與 PC 層通訊**
   - 透過 HTTP/JSON 發送影像與音訊資料給 PC 推論伺服器 [cite: 197]
   - 接收分類結果與信心值
   - 管理 Gemini 雲端備援判斷門檻 [cite: 51, 130]

3. **與 ESP32 層通訊**
   - 透過 UART Serial 發送雲台控制指令
   - 指令封包化 (cmd_id, params, CRC) [cite: 114, 137, 138]
   - 接收 ACK、完成訊號或錯誤碼 (ERR_CODE) [cite: 112, 117]

### 狀態定義 (概念上)

- **IDLE**: 待機狀態，等待感測器觸發
- **TRIGGER**: 觸發狀態，感測器偵測到物體
- **CAPTURE**: 擷取狀態，收集影像與音訊資料
- **INFER_L**: 本地推論狀態，等待 PC 推論結果
- **INFER_G**: Gemini 備援推論狀態 (可選)
- **ACTUATE**: 致動狀態，控制 ESP32 雲台執行傾倒動作
- **RECOVER**: 復原狀態，處理錯誤與超時 [cite: 47, 91, 324]

### 通訊協議

#### PC <-> Pi (Network)
- **格式**: JSON
- **內容**: `{"class": "Paper", "confidence": 0.95, "is_gemini": false, "reasoning": "..."}` [cite: 163, 200, 236]

#### Pi <-> ESP32 (UART Serial)
- **格式**: 文字型指令 (例如: `MOVE:P:45:Y:0\n`) 或二進制封包 [cite: 114]
- **參數**: Pitch (-θp 到 +θp), Yaw (-θy 到 +θy) [cite: 149, 150, 153, 154, 155, 156]

## 技術棧

- **語言**: Python 3.8+
- **串列通訊**: pyserial
- **HTTP 通訊**: requests
- **影像處理**: opencv-python

## 專案結構

```
pi_client/
├── composite_trigger_controller.py # 核心：生產級 FSM 複合觸發控制器 MVP (重量 + 影像幀差雙重去抖動)
├── interactive_controller.py       # 核心：互動式測試控制 CLI 工具 (Space/Enter 觸發)
├── pc_client.py                    # 核心：與 PC Inference Server 的 HTTP 通訊模組
├── esp32_uart.py                   # 核心：與 ESP32 的 UART Serial 雙向通訊模組
├── audio_processor.py              # 核心：聽覺採集與 Mel-spectrogram 頻譜純 Numpy/OpenCV 生成
├── env_loader.py                   # 核心：無縫載入 .env 檔案為環境變數之輔助模組
├── README.md                       # 本說明文件
├── tests/                          # 測試與校準工具目錄
│   ├── __init__.py
│   └── test_weight_sensor.py       # HX711 重量感測器 UART 校準與穩定性測試工具
└── legacy/                         # 歷史與封存舊版腳本目錄
    ├── impact_trigger_test.py      # 衝擊聲觸發獨立測試腳本
    └── pi_remote_controller.py     # 舊版 CV2 預覽控制腳本 (Client Mode)
```

## 安裝指南 (Raspberry Pi)

由於 Raspberry Pi OS (Bookworm 版本以上) 的安全性限制，直接使用 pip 可能會失敗。請依照以下方式安裝套件：

### 1. 更新系統
```bash
sudo apt update
sudo apt upgrade
```

### 2. 安裝必要的系統套件
這些套件包含 OpenCV 依賴與 Python 庫：
```bash
# 安裝 OpenCV 依賴、Serial 庫、HTTP 請求庫與 Picamera2
sudo apt install python3-opencv python3-serial python3-requests python3-picamera2
```

### 3. 如果需要使用 pip 安裝 (強制模式)
如果您發現透過 apt 無法安裝某些套件，或者您習慣使用 pip，請使用 `sudo` 加上 `--break-system-packages` 參數 (這是 Pi 新版系統的要求)：

```bash
# 例如安裝 requests 與 pyserial (如果 apt 沒裝成功)
sudo pip3 install requests pyserial opencv-python --break-system-packages
```

**⚠️ 注意：使用 sudo 安裝是全域安裝，請確保您是在 Pi 上操作。**

## 設定與執行

### 1. 設定 UART 權限
```bash
sudo usermod -a -G dialout $USER
# **務必重新開機或重新登入後生效**
```

### 2. 設定 PC 伺服器地址 (Tailscale)
編輯 `pi_remote_controller.py`：
```python
# 修改為您的 PC Tailscale IP
PC_SERVER_IP = "100.x.x.x" 
PC_SERVER_PORT = 5000
```

### 3. 執行主程式 (FSM 複合觸發控制器)
```bash
python composite_trigger_controller.py
```
或使用互動式測試 CLI 工具：
```bash
python interactive_controller.py
```

### 4. 啟動 Streamlit 實時監測與標記工具看板
看板提供 Live Dashboard (監測狀態與歷史日誌)、麥克風診斷、數據集標記與 ZIP 導出、網路/Tailscale 配置以及舵機與重量硬體校準五大模組。
```bash
# 執行 Streamlit 服務
streamlit run Streamlit.py
```
啟動後，瀏覽器將自動開啟：`http://localhost:8501`。

## 硬體連接檢查

1. **相機**: 確保 USB 相機已連接，可使用 `ls /dev/video*` 檢查。
2. **ESP32**: 確保 USB TTL 線已連接，可使用 `ls /dev/ttyUSB*` 檢查 (通常是 `/dev/ttyUSB0`)。
3. **麥克風 (USB 麥克風 - audio-technica ATR4650-USB)**:
   此麥克風為 USB 隨插即用裝置，免除了原有的 I2S GPIO 接線（原 Pin 12, 35, 38 等）。
   *   **硬體連接**: 直接插入樹莓派任一 USB 埠。
   *   **系統識別**: 在終端機執行 `lsusb` 確認系統有偵測到音效裝置。
   *   **列出錄音卡號**: 執行 `arecord -l` 取得 USB 麥克風的 Card ID 或裝置名稱。
   *   **設定優先目標**: 預設系統會自動尋找含 `usb`、`mic` 關鍵字的音效卡。若有多張音訊裝置，可在 `.env` 中設定 `AUDIO_DEVICE_TARGET=ATR4650` 進行明確鎖定。


4. **I2C 設備 (若適用)**:
   若使用 I2C 的感測器或 ADC 模組，請連接至樹莓派硬體 I2C1 介面：
   - **SDA** -> GPIO 2 (Pin 3)
   - **SCL** -> GPIO 3 (Pin 5)
   - 可在 `sudo raspi-config` 中開啟 I2C 功能，並使用 `i2cdetect -y 1` 檢查設備。

## 注意事項

- **絕對禁止**: 此層級**絕對禁止**執行 AI 推論模型 (僅接收結果)
- **職責分離**: 僅負責狀態管理與通訊協調，不包含 AI 邏輯
- **錯誤處理**: 必須包含完整的超時機制與 RECOVER 流程
- **安全檢查**: 在發送 UART 指令前，應驗證參數範圍與安全性

## 參考文獻

- 對應計畫書章節: [cite: 39, 103, 107]
- 通訊協議: [cite: 114, 137, 138, 197]
- 錯誤處理: [cite: 47, 91, 324]
