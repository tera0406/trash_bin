# AIOT 智慧垃圾分類桶 - 專案文件

## 專案簡介

本專案實作一個基於 AIOT 架構的智慧垃圾分類系統，整合影像辨識、音訊分析與多模態融合技術，實現自動化的垃圾分類與傾倒。系統分為三層：PC 運算層、Raspberry Pi 決策層與 ESP32 致動層。

## 最新實作進度 (Level 1 & Level 2)

我們已完成 PC 端推論伺服器與 Raspberry Pi 端影像上傳客戶端的開發與整合。

### 核心功能

*   **多模態 AI 推論**: 結合 EfficientNet (視覺) 與 MFCC+CNN (聽覺) 進行分類。
*   **混合決策邏輯 (Hybrid Decision Gate)**: 使用音訊信心值修正視覺結果。
*   **Gemini 雲端備援**: 當本地信心值低於 0.8 時，自動調用 Google Gemini Pro Vision 進行思維鏈 (CoT) 判斷。
*   **Pi 影像串流**: Raspberry Pi 透過 `picamera2` 擷取影像並即時上傳至 PC。

---

## 系統架構與檔案說明

### 1. Level 1: PC Inference Server (運算層)

負責核心 AI 運算，運行於高效能 PC 或伺服器。

*   **[app.py](app.py)**: 
    *   **角色**: 主要 Inference Server (Flask App)。
    *   **功能**: 提供 `/predict` API，接收 JSON (Image+Audio)，回傳分類結果。
    *   **邏輯**: 整合 Vision, Audio, Fusion 與 Gemini Fallback。
*   **[test_client_simulation.py](test_client_simulation.py)**:
    *   **角色**: 測試工具。
    *   **功能**: 模擬 Pi 發送請求，用於驗證 Server 功能正常。
*   **src/inference/**:
    *   `vision_engine.py`: EfficientNet 影像模型封裝。
    *   `audio_engine.py`: 音訊 MFCC 特徵提取與 CNN 推論。
    *   `fusion_logic.py`: 多模態加權融合邏輯。
    *   `gemini_fallback.py`: Google Gemini API 整合 (CoT)。

### 2. Level 2: Raspberry Pi Controller (決策與控制層)

負責感測器控制、影像擷取與流程決策。

*   **[pi_controller/pi_remote_controller.py](pi_controller/pi_remote_controller.py)**:
    *   **角色**: 主要執行腳本 (Client Mode)。
    *   **功能**: 整合相機拍照、PC 連線推論、UART 致動器控制。
*   **[pi_controller/pc_client.py](pi_controller/pc_client.py)**:
    *   **角色**: HTTP 客戶端模組。
    *   **功能**: 封裝與 PC Server 的通訊協定。
*   **[pi_controller/esp32_uart.py](pi_controller/esp32_uart.py)**:
    *   **角色**: UART 驅動模組。
    *   **功能**: 負責傳送 `MOVE` 指令給 ESP32。

---

## 安裝與執行指南

### 1. 環境準備 (PC 端)

確保 Python 3.8+ 已安裝，並設定虛擬環境：

### 1a. 環境變數設定 (重要)

本專案使用 `.env` 檔案來管理敏感設定 (如 Google Gemini API Key)。GitHub 上僅會上傳範本檔 `.env.example`。

1.  **複製範本**: 將 `.env.example` 複製一份並重新命名為 `.env`。
2.  **填寫設定**: 打開 `.env` 檔案，將 `GOOGLE_API_KEY` 填入您的實際金鑰。
    ```ini
    GOOGLE_API_KEY=AIzaSy... (您的金鑰)
    ```
    *其他參數 (如權重、模型路徑) 可維持預設值。*

```bash
# 啟動虛擬環境 (Windows)
.venv\Scripts\Activate.ps1

# 安裝依賴
pip install -r requirements.txt
```

### 2. Tailscale 網路設定 (重要)

本專案強烈建議使用 **Tailscale** 建立跨網域的安全虛擬區網，大幅簡化 PC 與 Raspberry Pi 之間的連線。

1.  **安裝 Tailscale**: 分別在 PC 與 Raspberry Pi 上安裝 Tailscale 客戶端。
    *   PC: 下載 Windows 安裝檔。
    *   Pi: `curl -fsSL https://tailscale.com/install.sh | sh`
2.  **登入帳號**: 在兩台裝置上登入相同的帳號，綁定裝置。
3.  **取得 IP**:
    *   在 PC 開啟 Tailscale 控制台，記下 PC 的 **Tailscale IP** (例如 `100.85.67.115`)。
    *   這組 IP 是固定的，且不受區域網路限制，只要有網路就能通。
4.  **修改設定**:
    *   打開 `pi_controller/pi_remote_controller.py`。
    *   修改 `PC_SERVER_IP` 變數為你的 **Tailscale IP**。

### 3. 啟動推論伺服器 (PC 端)

```bash
# 務必使用虛擬環境 Python
python app.py
```

*   伺服器將啟動於 `0.0.0.0:5000`。
*   若使用 Tailscale，則 Pi 可透過 `100.x.x.x:5000` 存取。

### 4. 啟動控制程式 (Raspberry Pi 端)

1.  **安裝依賴**:
    ```bash
    pip install opencv-python pyserial requests
    ```

2.  **硬體連線**:
    *   USB 相機 (或 Pi Camera)。
    *   ESP32 (透過 USB TTL 線接上 Pi)。

3.  **執行主程式**:
    ```bash
    python pi_controller/interactive_controller.py
    ```

4.  **操作**:
    *   按 `Enter` 鍵拍照並觸發辨識。
    *   觀察 PC 端 Console 顯示 AI 推論結果。
    *   觀察 ESP32 伺服馬達動作。

---

## API 介面說明

### `POST /predict`

*   **Request JSON**:
    ```json
    {
      "image": "base64_string...",
      "audio": "base64_string... (optional)",
      "timestamp": 12345678.9
    }
    ```

*   **Response JSON**:
    ```json
    {
      "class": "Paper",
      "confidence": 0.95,
      "is_gemini": false,
      "reasoning": "Local inference sufficient."
    }
    ```

---

## 專題計畫對應

*   **1111 架構設計**: 實作於 `app.py` 與 `pi_fsm/` 結構。
*   **3333 視覺模型**: 對應 `src/inference/vision_engine.py`。
*   **Hybrid Decision Gate**: 對應 `src/inference/fusion_logic.py`。
*   **Gemini CoT**: 對應 `src/inference/gemini_fallback.py`。
