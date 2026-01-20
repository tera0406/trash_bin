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
import cv2
import numpy as np

# 匯入同級模組
try:
    from esp32_uart import ESP32UART
except ImportError:
    # 若直接執行此腳本，可能需要調整路徑
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from esp32_uart import ESP32UART
except ImportError:
    print("[Error] 無法匯入 ESP32UART，請確認路徑或檔案是否存在。")
    sys.exit(1)

# ===== 配置參數 =====
PC_SERVER_URL = "http://100.85.67.115:5000/predict"
ESP32_PORT = "/dev/ttyUSB0"
TIMEOUT_SECONDS = 10

# 類別對應 (簡化版)
CLASS_MAPPING = {
    "Paper":   {"pitch": 45, "yaw": 0},
    "Plastic": {"pitch": -45, "yaw": 0},
    "General": {"pitch": 0, "yaw": -45},
    "Metal":   {"pitch": 0, "yaw": 45}
}

def main():
    camera_lib = None
    uart = None
    
    try:
        # 1. 初始化相機 (Picamera2)
        print("[Init] 正在初始化相機 (Picamera2)...")
        from picamera2 import Picamera2
        picam2 = Picamera2()
        # 設定預覽串流格式 (640x480, RGB)
        config = picam2.create_preview_configuration(main={"format": "XBGR8888", "size": (640, 480)})
        picam2.configure(config)
        picam2.start()
        print("[Init] 相機啟動成功")
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
            
            # 取得即時影像
            # 雖然不顯示預覽，但仍需擷取當下畫面
            frame = picam2.capture_array()
            
            print("[Trigger] 觸發！正在處理...")
            
            # 準備影像資料
            # 將 numpy array 編碼為 jpg bytes
            _, img_encoded = cv2.imencode('.jpg', frame)
            image_b64 = base64.b64encode(img_encoded.tobytes()).decode('utf-8')
            
            # 發送 HTTP 請求
            payload = {"image": image_b64, "audio": None, "timestamp": time.time()}
            print(f"[Network] 上傳至 PC ({PC_SERVER_URL})...")
            
            try:
                start_time = time.time()
                resp = requests.post(PC_SERVER_URL, json=payload, timeout=TIMEOUT_SECONDS)
                latency = (time.time() - start_time) * 1000
                
                if resp.status_code == 200:
                    res = resp.json()
                    cls = res.get("class", "unknown")
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
                        print(f"[Action] 傳送指令 -> Pitch:{action['pitch']}, Yaw:{action['yaw']}")
                        uart.send_move_command(action['pitch'], action['yaw'])
                        
                        # 簡單等待回應 (非阻塞)
                        time.sleep(0.1)
                        response = uart.read_response()
                        if response:
                            print(f"[ESP32] 回應: {response}")
                        
                        # 模擬動作時間後歸位
                        time.sleep(2)
                        print("[Action] 歸位")
                        uart.send_reset_command()
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
