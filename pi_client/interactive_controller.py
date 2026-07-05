"""
AIOT 智慧垃圾桶 - Interactive Test Tool (Spacebar -> Capture -> Infer -> Actuate)
功能:
1. 顯示相機即時預覽 (OpenCV Window)
2. 按下 '空白鍵 (Space)' 觸發拍攝與辨識流
3. 連接 PC 伺服器取得結果
4. 連接 ESP32 進行致動測試 (UART)

Author: Embedded System Engineer
"""

import time
import requests
import base64
import json
import sys
import os
import io
import cv2
import numpy as np

try:
    from src.hardware.esp32_uart import ESP32UART
    from src.hardware.audio_processor import record_and_process_audio, audio_to_mel_spectrogram_image
except ImportError:
    # 若直接執行此腳本，可能需要調整路徑
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    try:
        from src.hardware.esp32_uart import ESP32UART
        from src.hardware.audio_processor import record_and_process_audio, audio_to_mel_spectrogram_image
    except ImportError as e:
        print(f"[Error] 無法匯入必要模組 (ESP32UART 或 audio_processor)，錯誤: {e}")
        sys.exit(1)

import os
from env_loader import load_env

# 載入環境變數設定
load_env()

# 匯入系統相機防過曝與延遲設定
try:
    from config import (
        PHOTO_DELAY_SEC,
        CAMERA_EXPOSURE_VALUE,
        CAMERA_METERING_MODE,
        CAMERA_CONTRAST,
        CAMERA_BRIGHTNESS,
        PITCH_NEUTRAL
    )
except ImportError:
    PHOTO_DELAY_SEC = 0.5
    CAMERA_EXPOSURE_VALUE = -1.0
    CAMERA_METERING_MODE = "spot"
    CAMERA_CONTRAST = 1.0
    CAMERA_BRIGHTNESS = 0.0
    PITCH_NEUTRAL = 98

# ===== 配置參數 =====
PC_SERVER_IP = os.getenv("PC_SERVER_IP", "192.168.31.18")
PC_SERVER_PORT = os.getenv("PC_SERVER_PORT", "5000")
PC_SERVER_URL = f"http://{PC_SERVER_IP}:{PC_SERVER_PORT}/predict"
ESP32_PORT = os.getenv("SERIAL_PORT", "/dev/ttyUSB0")
TIMEOUT_SECONDS = 10

# 類別對應 (Yaw 軸為 270° Servo: write(60) = 物理 90°)
CLASS_MAPPING = {
    "paper":   {"pitch": 45, "yaw": 0},
    "plastic": {"pitch": 135, "yaw": 0},
    "general": {"pitch": 45, "yaw": 60},
    "metal":   {"pitch": 135, "yaw": 60}
}

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
    camera_lib = None
    uart = None
    
    try:
        # 1. 初始化相機 (Picamera2)
        print("[Init] 正在初始化相機 (Picamera2)...")
        # pyrefly: ignore [missing-import]
        from picamera2 import Picamera2
        picam2 = Picamera2()
        # 設定預覽串流格式 (640x480, RGB)
        config = picam2.create_preview_configuration(main={"format": "RGB888", "size": (640, 480)})
        picam2.configure(config)
        apply_camera_settings(picam2)
        picam2.start()
        print("[Init] 相機啟動成功與防過曝參數設定")
        camera_lib = picam2
        
        # 2. 初始化 ESP32 UART
        print(f"[Init] 正在連接 ESP32 ({ESP32_PORT})...")
        uart = ESP32UART(port=ESP32_PORT)
        if uart.connect():
            print("[Init] ESP32 連接成功")
            print("[Init] 等待 ESP32 啟動 (2s)...")
            time.sleep(2) # 等待 ESP32重啟完成
        else:
            print("[Warning] ESP32 連接失敗，致動功能將無法使用")

        print("\n========================================")
        print("  AIOT Interactive Tester (Headless Mode)")
        print("  [Enter] 拍照 -> 上傳 -> 致動")
        print("  [q]     離開程式")
        print("========================================")

        while True:
            # 等待使用者輸入
            user_input = input("\n請按 Enter 拍照 (或輸入 'q' 離開): ").strip().lower()
            
            if user_input == 'q':
                break
            
            print("[Trigger] 觸發！正在進行影像與音訊採集...")
            
            # 1. 音訊錄製與 Mel-spectrogram 頻譜生成
            # 此錄音過程包含混音單聲道與音量自動補償 (與 collect_audio 方法一致)
            audio_data = record_and_process_audio()
            spec_bytes = audio_to_mel_spectrogram_image(audio_data)
            
            # 2. 取得即時影像與編碼
            # 使用 capture_file(format='jpeg') 讓 Picamera2 ISP 直接輸出 JPEG
            # 顏色由硬體處理，不經 Python 通道轉換，與 web_stream.py 做法相同
            if PHOTO_DELAY_SEC > 0:
                print(f"[Capture] ⏳ 拍照前延遲 {PHOTO_DELAY_SEC:.2f} 秒，確保物體完全靜止...")
                time.sleep(PHOTO_DELAY_SEC)
                
            buf = io.BytesIO()
            picam2.capture_file(buf, format="jpeg")
            img_bytes = buf.getvalue()
            
            # 3. 發送 HTTP 請求 (multipart/form-data)
            files = {
                "image": ("capture.jpg", img_bytes, "image/jpeg")
            }
            if spec_bytes:
                files["audio_spec"] = ("spectrogram.jpg", spec_bytes, "image/jpeg")
                print("[Audio] 已附帶 Mel-spectrogram 音訊頻譜圖")
            else:
                print("[Audio] [Warning] 未能成功附帶音訊頻譜圖")
                
            print(f"[Network] 上傳資料至 PC 推論伺服器 ({PC_SERVER_URL})...")
            
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
                    
                    print(f"[Result] 類別: {cls} | 信心值: {conf:.2f} | Gemini: {is_gemini}")
                    if is_gemini:
                        print(f"         原因: {reason}")
                    print(f"         耗時: {latency:.0f}ms")
                    
                    # ESP32 致動
                    if uart and cls in CLASS_MAPPING:
                        action = CLASS_MAPPING[cls]
                        adjusted_pitch = PITCH_NEUTRAL + (action['pitch'] - 90)
                        print(f"[Action] 傳送指令 -> Pitch:{adjusted_pitch} (原本:{action['pitch']}), Yaw:{action['yaw']}")
                        success, err = uart.send_move_command(adjusted_pitch, action['yaw'])
                        if success:
                            print("[ESP32] 收到指令並確認 (ACK)")
                            print("[Action] 正在執行平滑移動，等待 DONE 訊號...")
                            resp = uart.read_response(timeout=6.0)
                            if resp and "DONE" in resp:
                                print("[ESP32] 移動到位 (DONE)")
                            else:
                                print(f"[Warning] 未能確認動作完成 (回應: {resp})")
                        else:
                            print(f"[Error] 致動指令發送失敗: {err}")
                        
                        # 停留 1.5 秒讓垃圾滑落，然後歸位
                        time.sleep(1.5)
                        print("[Action] 傳送歸位指令...")
                        success, err = uart.send_reset_command()
                        if success:
                            print("[ESP32] 收到歸位指令並確認 (ACK)")
                            print("[Action] 正在執行歸位，等待 DONE 訊號...")
                            resp = uart.read_response(timeout=6.0)
                            if resp and "DONE" in resp:
                                print("[ESP32] 歸位完成 (DONE)")
                            else:
                                print(f"[Warning] 未能確認歸位完成 (回應: {resp})")
                        else:
                            print(f"[Error] 歸位指令發送失敗: {err}")
                    elif uart:
                        print(f"[Action] 未知類別 '{cls}'，不進行動作")
                            
                else:
                    print(f"[Error] 伺服器錯誤: {resp.status_code} - {resp.text}")
            
            except Exception as e:
                print(f"[Error] 連線失敗: {e}")

    except ImportError:
        print("[Error] 缺少必要套件 (picamera2, cv2)。請確認已執行 apt install。")
    except Exception as e:
        print(f"[System Error] {e}")
    finally:
        # 釋放資源
        if camera_lib:
            camera_lib.stop()
            camera_lib.close()
        if uart:
            uart.disconnect()
        cv2.destroyAllWindows()
        print("程式結束")

if __name__ == "__main__":
    main()
