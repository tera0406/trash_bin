# -*- coding: utf-8 -*-
"""
AIOT 智慧垃圾桶 - 系統設定模組
"""
import os
import sys

# 匯入專案既有模組
try:
    from env_loader import load_env
except ImportError:
    # 若直接執行此腳本，嘗試將當前目錄加入搜尋路徑
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from env_loader import load_env

# 載入 .env 環境變數 (PC_SERVER_IP, PC_SERVER_PORT, SERIAL_PORT)
load_env()

# ──────────────── 1. 重量感測器參數 ────────────────
# 重量觸發門檻 (單位: 公克)
# 物理意義: 當秤重值相對基準增加超過此值，代表「有東西被投入」
# 調校建議: 先用手丟一張紙 (~5g) 觀察讀數變化，設定為最小可偵測物的一半
WEIGHT_THRESHOLD_G = 3.0

# 重量輪詢間隔 (單位: 秒)
# 物理意義: 每隔多久向 HX711 查詢一次重量
# 設太快 → CPU 忙碌 + I2C 不穩定; 設太慢 → 反應遲鈍
# HX711 在 10Hz 模式下每 100ms 產出一筆新數據，故 0.2s 是合理下限
WEIGHT_POLL_INTERVAL_SEC = 0.2

# 重量基準線 (Tare) 校準取樣次數
# 物理意義: 開機時空桶量 N 次取平均，作為「零點」基準
# 太少 → 基準不穩; 太多 → 啟動慢
WEIGHT_TARE_SAMPLES = 10

# 重量校準係數 (已用 108.5g 砝碼校準)
# 物理意義: (原始讀數 - 歸零基準) / 此值 = 公克數
WEIGHT_CALIBRATION_FACTOR = -217.71


# ──────────────── 2. 影像幀差偵測參數 ────────────────
# 幀差法像素變化佔比門檻 (0.0 ~ 1.0)
# 物理意義: 相鄰兩幀中「變化像素數 / 總像素數」超過此比例，視為「有動靜」
# 0.01 = 1% 的畫面有變化就觸發 (非常靈敏)
# 0.05 = 5% 的畫面有變化才觸發 (適度)
# 0.15 = 15% 的畫面有變化才觸發 (適度，防止風/光影誤判)
# 優先自環境變數載入，預設改為 0.15 以降低靈敏度
FRAME_DIFF_THRESHOLD = float(os.getenv("FRAME_DIFF_THRESHOLD", "0.15"))

# 像素灰階差異門檻 (0 ~ 255)
# 物理意義: 兩幀同一像素的灰階差超過此值，才算「有變化」
# 設太低 → 相機噪訊/微小光線變化也算變動 (誤觸發)
# 設太高 → 只有非常劇烈的變化才被計入 (漏觸發)
# 25 是大多數室內場景的平衡點
PIXEL_DIFF_THRESHOLD = 25

# 影像偵測解析度 (寬, 高)
# 物理意義: 幀差計算用的降採樣解析度，越低越快但細節越少
# 160x120 在 Pi 上只需 ~1ms 處理一幀，幾乎不佔 CPU
DETECTION_RESOLUTION = (160, 120)

# 幀率 (FPS) - 影像偵測迴圈的目標幀率
# 物理意義: 每秒取幾幀來做幀差比較
# 5 FPS 對「偵測有沒有東西丟進來」已經綽綽有餘
DETECTION_FPS = 5

# ──────────────── 3. 狀態機時序參數 ────────────────
# 去抖動延遲 (單位: 秒)
# 物理意義: 從 TRIGGER 進入到正式確認 (CAPTURE) 之間的等待時間
# 目的: 等待投入的物體完全落定、停止彈跳
# 太短 → 物體還在彈跳就拍照 (模糊/位置不對)
# 太長 → 使用者等太久會不耐煩
DEBOUNCE_DELAY_SEC = float(os.getenv("DEBOUNCE_DELAY_SEC", "0.8"))

# 重量回落判定時間 (單位: 秒)
# 物理意義: 在 TRIGGER 狀態中，若重量在此時間內回落到基準線以下，
#           代表是假訊號 (例如震動、有人碰了桶子)，取消觸發回到 IDLE
WEIGHT_FALLBACK_SEC = 1.5

# 冷卻時間 (單位: 秒)
# 物理意義: 完成一次辨識後，暫時忽略新觸發的時間
# 防止「辨識完正在致動舵機時，舵機震動又觸發了重量感測」
COOLDOWN_SEC = float(os.getenv("COOLDOWN_SEC", "3.0"))

# 觸發前錄音時間 (單位: 秒)
# 物理意義: 碰撞觸發點「之前」收錄的聲音長度 (用以保留撞擊瞬間之前的環境或剛開始的碰撞聲音)
RECORD_PRE_TRIGGER_SEC = float(os.getenv("RECORD_PRE_TRIGGER_SEC", "1.0"))

# 觸發後錄音時間 (單位: 秒)
# 物理意義: 碰撞觸發點「之後」持續收錄的聲音長度 (用以完整保留撞擊彈跳與落定過程的尾音)
RECORD_POST_TRIGGER_SEC = float(os.getenv("RECORD_POST_TRIGGER_SEC", "1.0"))

# 錄音低通濾波器截止頻率 (單位: Hz)
# 物理意義: 濾除高於此頻率的所有音訊，用以徹底消除樹莓派電磁高頻雜音或線圈音 (Coil Whine)
# 設定為 8000.0 代表濾除 8kHz 以上的高頻噪聲；設為 0.0 代表關閉濾波器
AUDIO_LOWPASS_CUTOFF = float(os.getenv("AUDIO_LOWPASS_CUTOFF", "0.0"))

# 音訊標準化最低門檻與最大增益限制
# 目的: 避免在完全靜音或只有微弱底噪時過度放大雜音；同時允許放大極輕微的實體碰撞聲
# AUDIO_NORM_MIN_THRESHOLD: 振幅高於此值才進行標準化 (預設 1e-5，即 -100dB)
# AUDIO_NORM_MAX_GAIN: 最大自動補償增益限制 (預設 100.0，即 +40dB)
AUDIO_NORM_MIN_THRESHOLD = float(os.getenv("AUDIO_NORM_MIN_THRESHOLD", "1e-5"))
AUDIO_NORM_MAX_GAIN = float(os.getenv("AUDIO_NORM_MAX_GAIN", "100.0"))


# ──────────────── 4. PC 推論伺服器設定 ────────────────
PC_SERVER_IP = os.getenv("PC_SERVER_IP", "192.168.31.18")
PC_SERVER_PORT = os.getenv("PC_SERVER_PORT", "5000")
PC_SERVER_URL = f"http://{PC_SERVER_IP}:{PC_SERVER_PORT}/predict"
TIMEOUT_SECONDS = 10

# ──────────────── 5. ESP32 致動與連線設定 ────────────────
# 安全開關: 設為 True 才會真正控制舵機 (支援從 .env 動態讀取與載入)
ENABLE_ACTUATOR = os.getenv("ENABLE_ACTUATOR", "True").lower() == "true"
ESP32_PORT = os.getenv("SERIAL_PORT", "/dev/ttyUSB0")
PITCH_NEUTRAL = int(os.getenv("PITCH_NEUTRAL", "98"))

# 分類結果 → 舵機角度映射表
CLASS_MAPPING = {
    "paper":   {"pitch": 45, "yaw": 0},
    "plastic": {"pitch": 135, "yaw": 0},
    "general": {"pitch": 45, "yaw": 60},
    "metal":   {"pitch": 135, "yaw": 60},
}


# ──────────────── 6. 相機參數調整 (防過曝與延遲) ────────────────
# 拍照延遲時間 (單位: 秒)
# 物理意義: 觸發後/確認後延遲多久才拍照，用以確保投入的物體已經完全靜止
# 預設為 0.5 秒，可依測試調整 (例如 1.0 或 1.5 秒)
PHOTO_DELAY_SEC = float(os.getenv("PHOTO_DELAY_SEC", "0.5"))

# 相機曝光調整值 (Exposure Value, EV)
# 物理意義: 曝光補償，單位為 stops。設為負值可讓畫面變暗，防止白色/亮色物體過曝
# 預設為 -1.0，若白色物體常過曝，建議設為 -1.0 到 -2.5 之間 (例如 -1.5)
CAMERA_EXPOSURE_VALUE = float(os.getenv("CAMERA_EXPOSURE_VALUE", "-1.0"))

# 相機測光模式 (Metering Mode)
# 物理意義: 決定自動曝光 (AE) 如何衡量畫面亮度。
# 可選值: "centre-weighted" (中央重點), "spot" (單點測光), "matrix" (矩陣測光)
# 設為 "spot" 可以讓曝光專注於中央物體，顯著防過曝
CAMERA_METERING_MODE = os.getenv("CAMERA_METERING_MODE", "spot")

# 相機對比度調整 (Contrast)
# 物理意義: 調整畫面明暗對比。預設 1.0 (正常)
CAMERA_CONTRAST = float(os.getenv("CAMERA_CONTRAST", "1.0"))

# 相機亮度調整 (Brightness)
# 物理意義: 調整畫面整體亮度。預設 0.0 (正常)，範圍 -1.0 ~ 1.0
CAMERA_BRIGHTNESS = float(os.getenv("CAMERA_BRIGHTNESS", "0.0"))

# ──────────────── 7. 觸發源啟用開關 ────────────────
# 決定是否啟用以下三種觸發來源 (Weight 重量、Vision 影像動態、IR 紅外線對射)
ENABLE_TRIGGER_WEIGHT = os.getenv("ENABLE_TRIGGER_WEIGHT", "Faulse").lower() == "true"
ENABLE_TRIGGER_VISION = os.getenv("ENABLE_TRIGGER_VISION", "True").lower() == "true"
ENABLE_TRIGGER_IR = os.getenv("ENABLE_TRIGGER_IR", "True").lower() == "true"


# ──────────────── 8. 紅外線對射消抖參數 ────────────────
# 單次信號瞬時中斷門檻 (單位: 毫秒)，高於此值視為可能發生遮擋
IR_GAP_THRESHOLD_MS = int(os.getenv("IR_GAP_THRESHOLD_MS", "12"))

# 遮擋確認持續時間 (單位: 毫秒)，連續無信號大於此時間才算作「真實遮擋」，防飛蟲與震動
IR_BLOCK_DEBOUNCE_MS = int(os.getenv("IR_BLOCK_DEBOUNCE_MS", "30"))

# 恢復確認持續時間 (單位: 毫秒)，連續穩定有訊號大於此時間才判定為「完全清空」，防抖動與重複觸發
IR_CLEAR_DEBOUNCE_MS = int(os.getenv("IR_CLEAR_DEBOUNCE_MS", "100"))

