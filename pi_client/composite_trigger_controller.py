# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════╗
║  AIOT 智慧垃圾桶 - 複合觸發控制器 MVP                                ║
║  Composite Trigger Controller (Weight + Vision FSM)                ║
║                                                                    ║
║  架構: Raspberry Pi 控制節點 (不跑 AI 模型)                          ║
║  觸發策略: 重量感測器 (主) + 影像幀差動態偵測 (輔)                     ║
║  狀態機: IDLE → TRIGGER → CAPTURE → IDLE                           ║
║                                                                    ║
║  Author: Embedded System Engineer                                  ║
╚══════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import io
import time
import requests
import numpy as np
import cv2

# 匯入專案既有模組
try:
    from src.hardware.audio_processor import record_and_process_audio, audio_to_mel_spectrogram_image, BackgroundAudioRecorder, FS
    from src.hardware.esp32_uart import ESP32UART
    from env_loader import load_env
except ImportError:
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from src.hardware.audio_processor import record_and_process_audio, audio_to_mel_spectrogram_image, BackgroundAudioRecorder, FS
    from src.hardware.esp32_uart import ESP32UART
    from env_loader import load_env

# 載入 .env 環境變數 (PC_SERVER_IP, PC_SERVER_PORT, SERIAL_PORT)
load_env()

# 匯入模組設定與類別
try:
    from config import (
        WEIGHT_THRESHOLD_G,
        WEIGHT_POLL_INTERVAL_SEC,
        WEIGHT_TARE_SAMPLES,
        FRAME_DIFF_THRESHOLD,
        PIXEL_DIFF_THRESHOLD,
        DETECTION_RESOLUTION,
        DETECTION_FPS,
        DEBOUNCE_DELAY_SEC,
        WEIGHT_FALLBACK_SEC,
        COOLDOWN_SEC,
        RECORD_PRE_TRIGGER_SEC,
        RECORD_POST_TRIGGER_SEC,
        PC_SERVER_IP,
        PC_SERVER_PORT,
        PC_SERVER_URL,
        TIMEOUT_SECONDS,
        ENABLE_ACTUATOR,
        ESP32_PORT,
        CLASS_MAPPING,
        PHOTO_DELAY_SEC,
        CAMERA_EXPOSURE_VALUE,
        CAMERA_METERING_MODE,
        CAMERA_CONTRAST,
        CAMERA_BRIGHTNESS,
        PITCH_NEUTRAL,
        ENABLE_TRIGGER_WEIGHT,
        ENABLE_TRIGGER_VISION,
        ENABLE_TRIGGER_IR
    )
    from src.hardware.weight_sensor import WeightSensor
    from src.hardware.motion_detector import MotionDetector
except ImportError:
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from config import (
        WEIGHT_THRESHOLD_G,
        WEIGHT_POLL_INTERVAL_SEC,
        WEIGHT_TARE_SAMPLES,
        FRAME_DIFF_THRESHOLD,
        PIXEL_DIFF_THRESHOLD,
        DETECTION_RESOLUTION,
        DETECTION_FPS,
        DEBOUNCE_DELAY_SEC,
        WEIGHT_FALLBACK_SEC,
        COOLDOWN_SEC,
        RECORD_PRE_TRIGGER_SEC,
        RECORD_POST_TRIGGER_SEC,
        PC_SERVER_IP,
        PC_SERVER_PORT,
        PC_SERVER_URL,
        TIMEOUT_SECONDS,
        ENABLE_ACTUATOR,
        ESP32_PORT,
        CLASS_MAPPING,
        PHOTO_DELAY_SEC,
        CAMERA_EXPOSURE_VALUE,
        CAMERA_METERING_MODE,
        CAMERA_CONTRAST,
        CAMERA_BRIGHTNESS,
        PITCH_NEUTRAL,
        ENABLE_TRIGGER_WEIGHT,
        ENABLE_TRIGGER_VISION,
        ENABLE_TRIGGER_IR
    )
    from src.hardware.weight_sensor import WeightSensor
    from src.hardware.motion_detector import MotionDetector

import json
import wave

# FSM 的三個狀態常數
STATE_IDLE = "IDLE"           # 空閒監控中: 持續偵測重量與畫面
STATE_TRIGGER = "TRIGGER"     # 已觸發，等待去抖動確認
STATE_CAPTURE = "CAPTURE"     # 確認完成，正在拍照/錄音/推論

def save_wav_file(filepath, data, samplerate):
    """將 float32 音訊數據安全轉換為標準 16-bit PCM WAV 檔案，保證可在瀏覽器播放"""
    try:
        with wave.open(filepath, 'wb') as wf:
            wf.setnchannels(1)
            wf.setframerate(samplerate)
            # data 是 float32 且範圍在 -1.0 到 1.0 之間，轉為 16-bit int16 格式
            int_data = np.clip(data, -1.0, 1.0) * 32767.0
            int_data = int_data.astype(np.int16)
            wf.setsampwidth(2) # 16-bit
            wf.writeframes(int_data.tobytes())
    except Exception as e:
        print(f"  [Monitor Warning] WAV 檔案寫入失敗: {e}")

def update_monitor_state(state_name, current_weight=0.0, current_tare=None, event_data=None):
    """更新實時監測狀態 JSON 檔案，以非阻塞/覆寫方式寫入"""
    temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
    os.makedirs(temp_dir, exist_ok=True)
    state_file = os.path.join(temp_dir, "monitor_state.json")

    try:
        data = {}
        # 讀取既有數據以保持 history 清單
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                pass
                
        if "status" not in data:
            data["status"] = {}
            
        data["status"]["current_state"] = state_name
        data["status"]["last_update"] = time.time()
        data["status"]["current_weight"] = float(current_weight)
        
        if current_tare is not None:
            data["status"]["current_tare"] = float(current_tare)
        elif "current_tare" not in data["status"]:
            data["status"]["current_tare"] = 0.0
            
        if event_data:
            data["last_event"] = event_data
            if "history" not in data:
                data["history"] = []
            data["history"].insert(0, event_data)
            # 限制歷史記錄最大保存 50 筆
            data["history"] = data["history"][:50]
            
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  [Monitor Warning] 寫入監控狀態失敗: {e}")


def apply_camera_settings(picam2):
    """根據系統設定，套用 Picamera2 相機參數 (如曝光補償、測光模式等) 以防止過曝"""
    try:
        from libcamera import controls
        control_dict = {}
        
        # 1. 曝光補償 (Exposure Value)
        control_dict["ExposureValue"] = CAMERA_EXPOSURE_VALUE
        
        # 2. 測光模式 (Metering Mode)
        mode = CAMERA_METERING_MODE.lower().strip()
        if mode == "spot":
            control_dict["AeMeteringMode"] = controls.AeMeteringModeEnum.MeteringSpot
        elif mode in ("centre-weighted", "center-weighted"):
            control_dict["AeMeteringMode"] = controls.AeMeteringModeEnum.MeteringCentreWeighted
        elif mode == "matrix":
            control_dict["AeMeteringMode"] = controls.AeMeteringModeEnum.MeteringMatrix
            
        # 3. 對比度
        control_dict["Contrast"] = CAMERA_CONTRAST
        
        # 4. 亮度
        control_dict["Brightness"] = CAMERA_BRIGHTNESS
        
        # 5. 自動對焦 (AfMode) - 專為 Pi Camera 3 設計之馬達驅動鏡頭
        try:
            control_dict["AfMode"] = controls.AfModeEnum.Continuous
        except AttributeError:
            pass
        
        print(f"[Camera] 正在套用相機防過曝與自動對焦參數: {control_dict}")
        picam2.set_controls(control_dict)
    except ImportError:
        print("[Camera] [Warning] 無法載入 libcamera.controls，跳過測光與曝光參數設定 (僅在 Raspberry Pi 環境支援)")
    except Exception as e:
        print(f"[Camera] [Warning] 套用相機參數失敗: {e}")


def main():
    """
    主控制迴圈。
    實作有限狀態機 (FSM)，在三個狀態之間循環：
    IDLE (空閒監控) -> TRIGGER (去抖動確認) -> CAPTURE (拍照/錄音/推論/致動) -> IDLE
    """
    picam2 = None
    uart = None
    audio_recorder = None

    try:
        # ────────────────────────────────────────────────────────────
        # 1. 初始化相機
        # ────────────────────────────────────────────────────────────
        print("[Init] 正在初始化相機 (Picamera2)...")
        # pyrefly: ignore [missing-import]
        from picamera2 import Picamera2
        picam2 = Picamera2()

        # 設定相機輸出格式:
        #   RGB888   = 每像素 3 bytes (R, G, B)，最相容的硬體串流格式
        #   640x480  = 足以辨識垃圾種類，同時不會讓 Pi 過載
        config = picam2.create_preview_configuration(
            main={"format": "RGB888", "size": (640, 480)}
        )
        picam2.configure(config)
        apply_camera_settings(picam2)
        picam2.start()
        print("[Init] ✅ 相機啟動成功與防過曝參數設定")

        # ────────────────────────────────────────────────────────────
        # 2. 初始化重量感測器
        # ────────────────────────────────────────────────────────────
        # 2. 初始化 ESP32 UART 致動控制 (隨時準備接收動態啟用)
        # ────────────────────────────────────────────────────────────
        print(f"[Init] 正在連接 ESP32 ({ESP32_PORT})...")
        uart = ESP32UART(port=ESP32_PORT)
        if uart.connect():
            print("[Init] ✅ ESP32 連接成功")
            time.sleep(2)  # 等待 ESP32 啟動完成
        else:
            print("[Warning] ESP32 連接失敗，但主控程序仍可正常啟動，隨時可於看板啟用致動")
            uart = None

        # ────────────────────────────────────────────────────────────
        # 3. 初始化重量感測器 (共用 UART 連線以防止埠口衝突與搶訊號)
        # ────────────────────────────────────────────────────────────
        print("[Init] 正在校準重量感測器...")
        shared_conn = uart.serial_conn if (uart and uart.serial_conn) else None
        weight_sensor = WeightSensor(uart_conn=shared_conn)
        weight_sensor.tare(samples=WEIGHT_TARE_SAMPLES)
        print(f"[Init] ✅ 重量感測器校準完成 (取樣 {WEIGHT_TARE_SAMPLES} 次)")

        # ────────────────────────────────────────────────────────────
        # 4. 初始化影像動態偵測器
        # ────────────────────────────────────────────────────────────
        motion_detector = MotionDetector(resolution=DETECTION_RESOLUTION)
        print(f"[Init] ✅ 幀差偵測器已建立 (解析度: {DETECTION_RESOLUTION}, FPS: {DETECTION_FPS})")

        # ────────────────────────────────────────────────────────────
        # 4b. 初始化背景音訊環形緩衝區與錄音器
        # ────────────────────────────────────────────────────────────
        print("[Init] 正在初始化背景環形音訊緩衝區...")
        total_audio_duration = RECORD_PRE_TRIGGER_SEC + RECORD_POST_TRIGGER_SEC
        audio_recorder = BackgroundAudioRecorder(buffer_duration=max(5.0, total_audio_duration + 2.0))
        audio_recorder.start()

        # ────────────────────────────────────────────────────────────
        # 5. 顯示啟動資訊
        # ────────────────────────────────────────────────────────────
        print("\n" + "=" * 60)
        print("  AIOT 智慧垃圾桶 - 複合觸發控制器 MVP")
        print("  ⚖️  重量門檻: {:.1f}g".format(WEIGHT_THRESHOLD_G))
        print("  📷 幀差門檻: {:.1%}".format(FRAME_DIFF_THRESHOLD))
        print("  ⏱️  去抖延遲: {:.1f}s | 冷卻: {:.1f}s".format(DEBOUNCE_DELAY_SEC, COOLDOWN_SEC))
        
        # 建立動態啟用的觸發源狀態說明
        active_triggers = []
        if ENABLE_TRIGGER_IR:
            active_triggers.append("IR (紅外線)")
        if ENABLE_TRIGGER_WEIGHT:
            active_triggers.append("WEIGHT (重量)")
        if ENABLE_TRIGGER_VISION:
            active_triggers.append("VISION (影像)")
        trigger_status = " + ".join(active_triggers) if active_triggers else "無 (所有觸發已關閉)"
        print("  🎯 觸發配置: {}".format(trigger_status))
        
        print("  🔧 致動功能: {}".format("啟用" if ENABLE_ACTUATOR else "關閉"))
        print("  按下 Ctrl+C 結束程式")
        print("=" * 60 + "\n")

        # ────────────────────────────────────────────────────────────
        # 6. FSM 主迴圈
        # ────────────────────────────────────────────────────────────
        state = STATE_IDLE           # 當前狀態
        trigger_time = 0.0           # 觸發時刻 (用於去抖計時)
        trigger_source = ""          # 觸發來源 ("WEIGHT" / "VISION" / "BOTH")
        last_capture_time = 0.0      # 上次完成辨識的時間 (用於冷卻計時)
        last_monitor_update = 0.0    # 上次更新監測看板時間
        need_auto_tare = False       # 是否需要在冷卻後進行動態去皮 (Auto-Tare)

        # 幀率控制: 每幀之間應等待的秒數
        frame_interval = 1.0 / DETECTION_FPS

        print(f"[FSM] 狀態: {STATE_IDLE} | 開始監控...\n")
        
        # 初始化實時監測狀態檔
        update_monitor_state(STATE_IDLE, current_weight=0.0, current_tare=weight_sensor.tare_value)

        while True:
            loop_start = time.time()

            # ══════════════════════════════════════════════════════
            #  STATE: IDLE - 空閒監控
            # ══════════════════════════════════════════════════════
            if state == STATE_IDLE:

                # 冷卻期間不做偵測
                if (time.time() - last_capture_time) < COOLDOWN_SEC and last_capture_time > 0:
                    time.sleep(0.1)
                    continue

                # 若冷卻剛結束，進行動態基準校準 (Auto-Tare)
                if need_auto_tare:
                    print("[FSM] ⚖️ 平台已歸位且冷卻結束，開始自動校準重量基準值 (Auto-Tare)...")
                    
                    # 清空冷卻期間積累的舊紅外線事件，避免開機/歸位後瞬間誤觸發
                    if uart:
                        try:
                            from src.hardware.esp32_uart import _shared_pending_events
                            _shared_pending_events.clear()
                            while uart.check_unsolicited_event() is not None:
                                pass
                            print("[FSM] 🧹 已成功清空冷卻期間積累的舊紅外線事件，開始乾淨監測")
                        except Exception as e:
                            print(f"[FSM] ⚠️ 清除冷卻期事件失敗: {e}")
                            
                    weight_sensor.tare(samples=5)
                    need_auto_tare = False
                    print(f"[FSM] 基準值動態更新完成 (新 Tare 偏移量: {weight_sensor.tare_value:.1f})，開始主動監測")

                # ── 6a. 讀取重量 ──
                weight_g = 0.0
                if ENABLE_TRIGGER_WEIGHT:
                    weight_g = weight_sensor.read_grams()

                # 每秒定時將重量與 IDLE 狀態寫入監控檔
                if time.time() - last_monitor_update > 1.0:
                    update_monitor_state(STATE_IDLE, current_weight=weight_g, current_tare=weight_sensor.tare_value)
                    last_monitor_update = time.time()

                # ── 6b. 影像幀差偵測 ──
                is_motion = False
                change_ratio = 0.0
                if ENABLE_TRIGGER_VISION:
                    rgb_frame = picam2.capture_array()
                    # 取前 3 個通道 (防止相機靜默回傳 4 通道陣列)
                    # MotionDetector.detect() 需要 BGR 格式，故此處做轉換
                    rgb3 = rgb_frame[:, :, :3]
                    frame = cv2.cvtColor(rgb3, cv2.COLOR_RGB2BGR)
                    is_motion, change_ratio = motion_detector.detect(frame)

                # ── 6c. 檢查 ESP32 紅外線主動上報事件 ──
                ir_triggered = False
                if ENABLE_TRIGGER_IR and uart:
                    event = uart.check_unsolicited_event()
                    if event == "EVENT:INPUT_BLOCKED":
                        ir_triggered = True

                # ── 6d. 判斷是否觸發 ──
                weight_triggered = ENABLE_TRIGGER_WEIGHT and (weight_g > WEIGHT_THRESHOLD_G)
                vision_triggered = ENABLE_TRIGGER_VISION and is_motion

                if ir_triggered:
                    trigger_source = "IR"
                elif weight_triggered and vision_triggered:
                    trigger_source = "BOTH"
                elif weight_triggered:
                    trigger_source = "WEIGHT"
                elif vision_triggered:
                    trigger_source = "VISION"
                else:
                    trigger_source = ""

                # ── 6e. 狀態轉移: IDLE → TRIGGER ──
                if trigger_source:
                    state = STATE_TRIGGER
                    trigger_time = time.time()
                    print(f"[FSM] ⚡ IDLE → TRIGGER")
                    if trigger_source == "IR":
                        print(f"       來源: IR (紅外線感測器物理觸發) | 重量: {weight_g:+.1f}g")
                    else:
                        print(f"       來源: {trigger_source} | "
                              f"重量: {weight_g:+.1f}g | "
                              f"畫面變化: {change_ratio:.2%}")
                    update_monitor_state(STATE_TRIGGER, current_weight=weight_g, current_tare=weight_sensor.tare_value)

            # ══════════════════════════════════════════════════════
            #  STATE: TRIGGER - 去抖動確認
            # ══════════════════════════════════════════════════════
            elif state == STATE_TRIGGER:

                elapsed = time.time() - trigger_time

                # 等待去抖動延遲
                if elapsed < DEBOUNCE_DELAY_SEC:
                    time.sleep(0.05)  # 短暫休眠，避免 CPU 空轉
                    continue

                confirm_weight = weight_sensor.read_grams()

                # 判定是否確認觸發
                should_capture = False
                confirm_reason = ""

                if "VISION" in trigger_source or trigger_source == "BOTH" or trigger_source == "IR":
                    # 影像、紅外線或複合觸發：去抖動時間到即進行拍照（不強制要求重量達到高門檻，以支援輕量與物理觸發物體）
                    should_capture = True
                    if trigger_source == "IR":
                        confirm_reason = f"紅外線物理觸發去抖完成 | 當前重量: {confirm_weight:+.1f}g"
                    else:
                        confirm_reason = f"影像觸發去抖完成 | 當前重量: {confirm_weight:+.1f}g"
                elif confirm_weight > WEIGHT_THRESHOLD_G:
                    # 純重量觸發：去抖動後重量仍需高於門檻
                    should_capture = True
                    confirm_reason = f"重量去抖確認通過 | 確認重量: {confirm_weight:+.1f}g"

                if should_capture:
                    print(f"[FSM] ✅ TRIGGER → CAPTURE")
                    print(f"       {confirm_reason}")
                    state = STATE_CAPTURE
                    update_monitor_state(STATE_CAPTURE, current_weight=confirm_weight, current_tare=weight_sensor.tare_value)

                elif elapsed > WEIGHT_FALLBACK_SEC:
                    # 超時且重量未達標 → 判定為假訊號
                    print(f"[FSM] ❌ TRIGGER → IDLE (假訊號: 重量未達門檻 {confirm_weight:+.1f}g)")
                    state = STATE_IDLE
                    motion_detector.reset()  # 重置影像基準，避免重回 IDLE 後瞬間誤觸發
                    update_monitor_state(STATE_IDLE, current_weight=confirm_weight, current_tare=weight_sensor.tare_value)

                else:
                    # 還在等待中，繼續輪詢
                    time.sleep(0.1)

            # ══════════════════════════════════════════════════════
            #  STATE: CAPTURE - 拍照 / 錄音 / 推論 / 致動
            # ══════════════════════════════════════════════════════
            elif state == STATE_CAPTURE:

                # ── 7a. 提取預錄音訊 + Mel-spectrogram ──
                # 確保收錄完整的觸發後音訊 (等待到 trigger_time + RECORD_POST_TRIGGER_SEC)
                target_end_time = trigger_time + RECORD_POST_TRIGGER_SEC
                now = time.time()
                if now < target_end_time:
                    sleep_needed = target_end_time - now
                    print(f"[Capture] ⏳ 等待觸發後錄音完成 (需補錄 {sleep_needed:.2f} 秒)...")
                    time.sleep(sleep_needed)

                total_audio_duration = RECORD_PRE_TRIGGER_SEC + RECORD_POST_TRIGGER_SEC
                print(f"[Capture] 🎤 提取音訊: 觸發前 {RECORD_PRE_TRIGGER_SEC} 秒 + 觸發後 {RECORD_POST_TRIGGER_SEC} 秒 (共 {total_audio_duration:.1f} 秒)...")
                audio_data = audio_recorder.get_last_seconds(total_audio_duration)
                
                # 實時監測：將錄製的 WAV 保存
                temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
                os.makedirs(temp_dir, exist_ok=True)
                wav_path = os.path.join(temp_dir, "last_audio.wav")
                save_wav_file(wav_path, audio_data, FS)
                
                spec_bytes = audio_to_mel_spectrogram_image(audio_data)
                
                # 實時監測：保存 Mel-Spectrogram 圖片
                if spec_bytes:
                    spec_path = os.path.join(temp_dir, "last_spec.jpg")
                    try:
                        with open(spec_path, 'wb') as f:
                            f.write(spec_bytes)
                    except Exception as e:
                        print(f"  [Monitor Warning] 寫入 last_spec.jpg 失敗: {e}")

                # ── 7b. 拍照 (物體已穩定) ──
                # 使用 capture_file(format="jpeg") 讓 Picamera2 ISP 直接輸出 JPEG
                # 完全繞開 Python 端的 numpy 陣列通道轉換，是最可靠的顏色正確保證方式
                # (與 web_stream.py 使用相同做法)
                if PHOTO_DELAY_SEC > 0:
                    print(f"[Capture] ⏳ 拍照前延遲 {PHOTO_DELAY_SEC:.2f} 秒，確保物體完全靜止...")
                    time.sleep(PHOTO_DELAY_SEC)
                
                print("[Capture] 📸 拍照中 (物體已穩定)...")
                # 實時監測：拍照前更新連線狀態防斷線
                update_monitor_state(STATE_CAPTURE, current_weight=confirm_weight, current_tare=weight_sensor.tare_value)
                buf = io.BytesIO()
                picam2.capture_file(buf, format="jpeg")
                img_bytes = buf.getvalue()
                print("[Capture] 拍照完成")
                
                # 實時監測：保存快照照片
                img_path = os.path.join(temp_dir, "last_capture.jpg")
                try:
                    with open(img_path, 'wb') as f:
                        f.write(img_bytes)
                except Exception as e:
                    print(f"  [Monitor Warning] 寫入 last_capture.jpg 失敗: {e}")


                # ── 7c. 上傳 PC 推論伺服器 ──
                files = {
                    "image": ("capture.jpg", img_bytes, "image/jpeg")
                }
                if spec_bytes:
                    files["audio_spec"] = ("spectrogram.jpg", spec_bytes, "image/jpeg")
                    print("[Capture] ✅ 已附帶 Mel-spectrogram 頻譜圖")
                else:
                    print("[Capture] ⚠️ 未能生成頻譜圖 (僅影像辨識)")

                print(f"[Network] 上傳至 PC 推論伺服器 ({PC_SERVER_URL})...")
                # 實時監測：網路推論前更新連線狀態防斷線
                update_monitor_state(STATE_CAPTURE, current_weight=confirm_weight, current_tare=weight_sensor.tare_value)

                cls = "unknown"
                conf = 0.0
                is_gemini = False
                reason = "連線失敗"
                latency = 0.0
                model_used = "N/A"
                probs = None
                local_probs = None

                try:
                    start_time = time.time()
                    resp = requests.post(PC_SERVER_URL, files=files, timeout=TIMEOUT_SECONDS)
                    latency = (time.time() - start_time) * 1000

                    if resp.status_code == 200:
                        res = resp.json()
                        cls = res.get("label", "unknown")
                        conf = res.get("confidence", 0.0)
                        is_gemini = res.get("is_gemini", False)
                        reason = res.get("reasoning", "")
                        model_used = res.get("model_used", "gemini-flash-latest" if is_gemini else "best_hierarchical_modelV04.keras")
                        probs = res.get("probabilities")
                        local_probs = res.get("local_probabilities")

                        print(f"[Result] 🏷️  類別: {cls} | 信心值: {conf:.2f} | Gemini: {is_gemini} | 採用模型: {model_used}")
                        if probs:
                            prob_str = ", ".join([f"{k}: {v:.2%}" for k, v in probs.items()])
                            print(f"         機率分布: {prob_str}")
                        if is_gemini and local_probs:
                            local_prob_str = ", ".join([f"{k}: {v:.2%}" for k, v in local_probs.items()])
                            print(f"         本地推論分佈: {local_prob_str}")
                        if is_gemini:
                            print(f"         原因: {reason}")
                        print(f"         耗時: {latency:.0f}ms")

                        # ── 7d. [選用] ESP32 致動 ──
                        try:
                            load_env()
                        except Exception:
                            pass
                        env_val = os.getenv("ENABLE_ACTUATOR")
                        if env_val is not None:
                            dynamic_actuator_enable = env_val.strip().lower() == "true"
                        else:
                            dynamic_actuator_enable = ENABLE_ACTUATOR
                        if dynamic_actuator_enable and uart and cls in CLASS_MAPPING:
                            action = CLASS_MAPPING[cls]
                            adjusted_pitch = PITCH_NEUTRAL + (action['pitch'] - 90)
                            print(f"[Action] 傳送指令 → Pitch:{adjusted_pitch} (原本:{action['pitch']}), Yaw:{action['yaw']}")
                            # 實時監測：舵機致動前更新連線狀態防斷線
                            update_monitor_state(STATE_CAPTURE, current_weight=confirm_weight, current_tare=weight_sensor.tare_value)
                            success, err = uart.send_move_command(adjusted_pitch, action['yaw'])
                            if success:
                                print("[ESP32] 收到指令 (ACK)，等待動作完成...")
                                resp_uart = uart.read_response(timeout=6.0)
                                if resp_uart and "DONE" in resp_uart:
                                    print("[ESP32] ✅ 移動到位 (DONE)")
                                else:
                                    print(f"[Warning] 未確認動作完成 (回應: {resp_uart})")
                            else:
                                print(f"[Warning] 致動指令失敗: {err}")

                            # 停留讓垃圾滑落，然後歸位
                            time.sleep(1.5)
                            # 實時監測：舵機歸位前更新連線狀態防斷線
                            update_monitor_state(STATE_CAPTURE, current_weight=confirm_weight, current_tare=weight_sensor.tare_value)
                            print("[Action] 傳送歸位指令...")
                            uart.send_reset_command()
                            uart.read_response(timeout=6.0)
                    else:
                        reason = f"伺服器錯誤: {resp.status_code}"
                        model_used = "Error"
                        print(f"[Error] 伺服器錯誤: {resp.status_code} - {resp.text}")

                except Exception as e:
                    reason = f"連線異常: {e}"
                    model_used = "N/A"
                    print(f"[Error] 連線失敗: {e}")

                # 實時監測：寫入辨識事件數據到監測 JSON
                event_data = {
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                    "weight": float(confirm_weight),
                    "source": trigger_source,
                    "label": cls,
                    "confidence": float(conf),
                    "is_gemini": bool(is_gemini),
                    "model_used": model_used,
                    "latency_ms": float(latency),
                    "reasoning": reason,
                    "probabilities": probs,
                    "local_probabilities": local_probs
                }
                update_monitor_state(STATE_CAPTURE, current_weight=confirm_weight, current_tare=weight_sensor.tare_value, event_data=event_data)

                # ── 7e. 完成! 記錄時間 → 冷卻 → 回到 IDLE ──
                last_capture_time = time.time()
                state = STATE_IDLE
                need_auto_tare = True    # 標記在冷卻結束時執行 Auto-Tare 以重置重量基準
                motion_detector.reset()  # 重置影像基準，防止冷卻結束後瞬間誤觸發
                print(f"\n[FSM] CAPTURE → IDLE (冷卻 {COOLDOWN_SEC}s)")
                print(f"[FSM] 等待下一次投入...\n")
                
                # 實時監測：重置回空閒狀態並記錄冷卻後重量
                update_monitor_state(STATE_IDLE, current_weight=confirm_weight, current_tare=weight_sensor.tare_value)

            # ── 幀率控制 ──
            # 確保每次迴圈至少間隔 frame_interval 秒
            # 避免 CPU 滿載空轉 (尤其在 IDLE 狀態下)
            elapsed = time.time() - loop_start
            sleep_time = max(0, frame_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

    # ────────────────────────────────────────────────────────────
    # 例外處理與資源釋放
    # ────────────────────────────────────────────────────────────
    except KeyboardInterrupt:
        print("\n\n[System] 使用者中斷 (Ctrl+C)，正在結束...")

    except ImportError as e:
        print(f"[Error] 缺少必要套件: {e}")
        print("        請確認已安裝: picamera2, opencv-python, sounddevice, requests")

    except Exception as e:
        import traceback
        print(f"[System Error] {e}")
        traceback.print_exc()

    finally:
        # 無論如何都要釋放硬體資源，避免相機/串口被鎖住
        if picam2:
            try:
                picam2.stop()
                picam2.close()
                print("[Cleanup] 相機已釋放")
            except Exception:
                pass
        if uart:
            try:
                uart.disconnect()
                print("[Cleanup] ESP32 UART 已斷開")
            except Exception:
                pass
        if audio_recorder:
            try:
                audio_recorder.stop()
                print("[Cleanup] 背景音訊緩衝區已釋放")
            except Exception:
                pass
        print("[System] 程式結束。")


# ═══════════════════════════════════════════════════════════════════
# 程式入口
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    main()
