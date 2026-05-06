# ESP32 Actuator Layer - 層級 3: ESP32 致動控制

## 硬體限制

- **硬體**: ESP32 / NodeMCU-32S
- **開發環境**: Arduino IDE 或 PlatformIO
- **GPIO**: 用於控制伺服馬達
- **UART**: 用於與 Raspberry Pi 通訊
- **電源**: 建議使用外部電源供應器 (伺服馬達需要較大電流)

## 軟體職責

### 核心任務

1. **UART 指令接收**
   - 接收來自 Raspberry Pi 的 UART Serial 指令
   - 解析指令格式 (文字型或二進制封包) [cite: 114]
   - 驗證指令有效性

2. **2-DOF 雲台控制**
   - 控制 Pitch 軸伺服馬達 (俯仰角)
   - 控制 Yaw 軸伺服馬達 (偏航角)
   - 執行傾倒動作 [cite: 146, 148, 296, 322]

3. **安全檢查**
   - 角度範圍驗證 (Pitch: -θp 到 +θp, Yaw: -θy 到 +θy) [cite: 149, 150, 153, 154, 155, 156]
   - 速度限制 (最大角速度) [cite: 111, 151, 323]
   - 超時檢測與自動回歸中立姿態 [cite: 111, 151, 323]

4. **狀態回報**
   - 回傳 ACK (確認訊號)
   - 回傳完成訊號 (DONE)
   - 回傳錯誤碼 (ERR_CODE) [cite: 112, 117]

### 通訊協議

#### Pi <-> ESP32 (UART Serial)
- **格式**: 文字型指令 (例如: `MOVE:P:45:Y:0\n`) 或二進制封包 [cite: 114]
- **參數**: 
  - Pitch: -45° 到 +45° (可調整)
  - Yaw: -90° 到 +90° (可調整)
- **回應格式**:
  - `ACK` - 指令已接收
  - `DONE` - 動作完成
  - `ERR:{錯誤碼}` - 錯誤訊息 [cite: 112, 117]

### 指令格式

1. **移動指令**
   ```
   MOVE:P:{pitch}:Y:{yaw}\n
   例如: MOVE:P:45:Y:0\n
   ```

2. **重置指令**
   ```
   RESET\n
   (回歸中立姿態)
   ```

3. **狀態查詢**
   ```
   STATUS\n
   回應: STATUS:P:{current_pitch}:Y:{current_yaw}
   ```

## 技術棧

- **語言**: Arduino/C++
- **庫**: ESP32Servo (ESP32 專用伺服馬達庫)
- **通訊**: Hardware Serial (UART)

## 專案結構

```
esp32_actuator/
├── actuator_control.ino  # Arduino 主程式
├── servo_config.h         # 伺服馬達參數設定
└── README.md              # 本檔案
```

## 使用方式

### 1. 安裝開發環境

**使用 Arduino IDE:**
1. 安裝 Arduino IDE (1.8.13 或更新版本)
2. 安裝 ESP32 開發板支援:
   - 檔案 → 偏好設定 → 額外的開發板管理員網址
   - 加入: `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
   - 工具 → 開發板 → 開發板管理員 → 搜尋 "ESP32" → 安裝

**使用 PlatformIO (推薦):**
```bash
# 安裝 PlatformIO
pip install platformio

# 在專案目錄下建立 platformio.ini
```

### 2. 硬體接線

- **Pitch 伺服馬達**: 連接到 GPIO 18 (定義於 `servo_config.h`)
- **Yaw 伺服馬達**: 連接到 GPIO 19 (定義於 `servo_config.h`)
- **UART**: ESP32 的 TX/RX 連接到 Raspberry Pi 的 UART

### 3. 編譯與上傳

**Arduino IDE:**
1. 選擇開發板: 工具 → 開發板 → ESP32 Arduino → 選擇你的 ESP32 型號
2. 選擇序列埠: 工具 → 序列埠 → 選擇對應的 COM 埠
3. 上傳程式碼: 點擊上傳按鈕

**PlatformIO:**
```bash
pio run --target upload
```

### 4. 測試

開啟序列埠監視器 (115200 baudrate)，應該會看到:
```
[ESP32] 致動控制系統已啟動
READY
```

發送測試指令:
```
MOVE:P:45:Y:0
```

應該會收到回應:
```
ACK
DONE
```

## 注意事項

- **絕對禁止**: 此層級**絕對禁止**進行邏輯決策或 AI
- **職責分離**: 僅負責接收指令並控制硬體，不包含任何決策邏輯
- **安全檢查**: 所有角度參數都必須通過驗證，防止超出安全範圍
- **超時機制**: 必須包含超時檢測，避免卡在移動狀態
- **電源供應**: 伺服馬達需要足夠的電流，建議使用外部電源

## 參數調整

在 `servo_config.h` 中可以調整以下參數:

- **角度範圍**: `PITCH_MIN_ANGLE`, `PITCH_MAX_ANGLE`, `YAW_MIN_ANGLE`, `YAW_MAX_ANGLE`
- **速度限制**: `MAX_ANGULAR_VELOCITY`
- **超時時間**: `MOVEMENT_TIMEOUT_MS`
- **傾倒參數**: `DUMP_ANGLE_PITCH`, `DUMP_ANGLE_YAW`, `DUMP_HOLD_TIME_MS` [cite: 157, 394]

## 參考文獻

- 對應計畫書章節: [cite: 108, 146, 148, 296, 322]
- 通訊協議: [cite: 114, 137, 138]
- 安全檢查: [cite: 111, 151, 323]
- 錯誤碼: [cite: 112, 117]
