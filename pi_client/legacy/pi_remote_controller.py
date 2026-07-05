# -*- coding: utf-8 -*-
"""
Raspberry Pi Remote Controller (PC Client Mode)
對應專題計畫書 - 下層控制與通訊 [cite: 197, 102]

功能:
1. 感知層 (CAPTURE): 攝影機影像擷取
2. 通訊層 (COM): 將影像傳送至 PC Server 進行運算 (含 Gemini)
3. 致動層 (ACT): 接收結果並透過 UART 控制 ESP32

Requirements:
    pip install opencv-python pyserial requests
"""

import cv2
import time
import sys
import json
import os

try:
    from src.network.pc_client import PCClient
    from src.hardware.esp32_uart import ESP32UART
    from src.hardware.audio_processor import record_and_process_audio, audio_to_mel_spectrogram_image
except ImportError:
    # 支援從 legacy 資料夾執行時，導入父目錄的核心模組
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.append(parent_dir)
    try:
        from src.network.pc_client import PCClient
        from src.hardware.esp32_uart import ESP32UART
        from src.hardware.audio_processor import record_and_process_audio, audio_to_mel_spectrogram_image
    except ImportError as e:
        print(f"錯誤: 找不到 pc_client.py、esp32_uart.py 或 audio_processor.py - {e}")
        sys.exit(1)

from env_loader import load_env

# 載入環境變數設定
load_env()

# ==========================================
# 系統參數設定
# ==========================================

# PC Server IP 設定 (請依據實際網路環境修改)
PC_SERVER_IP = os.getenv("PC_SERVER_IP", "192.168.1.50") 
PC_SERVER_PORT = int(os.getenv("PC_SERVER_PORT", "5000"))

# UART 設定
SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/ttyUSB0")
BAUD_RATE = 115200

# 分類映射 (與 PC 端保持一致) [cite: 153-156]
# 這裡根據 PC 回傳的 "class" 字串 ("A", "B", "C", "D") 進行映射
CLASS_MAPPING = {
    "A": {"name": "Paper",   "pitch": 45, "yaw": 0},
    "B": {"name": "Plastic", "pitch": 135, "yaw": 0},
    "C": {"name": "Kitchen", "pitch": 45, "yaw": 60},
    "D": {"name": "Metal",   "pitch": 135, "yaw": 60},
    # 容錯處理 (若 PC 回傳數字)
    "0": {"name": "Paper",   "pitch": 45, "yaw": 0},
    "1": {"name": "Plastic", "pitch": 135, "yaw": 0},
    "2": {"name": "Kitchen", "pitch": 45, "yaw": 60},
    "3": {"name": "Metal",   "pitch": 135, "yaw": 60}
}

class RemoteController:
    """
    遠端控制系統
    負責將 Pi 的 I/O (相機、馬達) 與 PC 的 AI 運算串接
    """
    def __init__(self):
        self.pc_client = PCClient(pc_host=PC_SERVER_IP, pc_port=PC_SERVER_PORT)
        self.uart = ESP32UART(port=SERIAL_PORT, baudrate=BAUD_RATE)
        self.cap = None

    def initialize(self):
        """硬體初始化"""
        print("====== 系統初始化 (Client Mode) ======")
        
        # 1. 測試 PC 連線
        print(f"正在連線至 PC Server ({PC_SERVER_IP}:{PC_SERVER_PORT})...")
        if self.pc_client.check_connection():
            print("PC Server 連線成功！")
        else:
            print("警告: 無法連線至 PC Server，請確認 Server 已啟動且 IP 正確。")
            # 這裡不強制退出，允許稍後重試

        # 2. 連線 ESP32
        if self.uart.connect():
            print("ESP32 UART 連線成功！")
        else:
            print("錯誤: ESP32 UART 連線失敗。")
            return False

        # 3. 開啟相機
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            print("錯誤: 無法開啟攝影機。")
            return False
            
        return True

    def run(self):
        """主執行迴圈"""
        if not self.initialize():
            return

        print("========================================")
        print("  Pi Remote Controller 準備就緒")
        print("  [Space] 拍照並傳送至 PC 辨識")
        print("  [q]     離開程式")
        print("========================================")

        try:
            while True:
                ret, frame = self.cap.read()
                if not ret:
                    print("影像讀取錯誤")
                    time.sleep(1)
                    continue

                # 顯示預覽
                cv2.imshow("Pi Client View", frame)

                key = cv2.waitKey(1) & 0xFF
                
                # 按下 Space 鍵觸發 [cite: 49]
                if key == 32: 
                    print("\n[Trigger] 觸發辨識程序...")
                    
                    # 1. 影像編碼 (JPG)
                    _, img_encoded = cv2.imencode('.jpg', frame)
                    img_bytes = img_encoded.tobytes()
                    
                    # 2. 音訊採集與 Mel-spectrogram 頻譜生成
                    # 此錄音過程包含混音單聲道與自動音量補償
                    audio_data = record_and_process_audio()
                    spec_bytes = audio_to_mel_spectrogram_image(audio_data)
                    
                    # 3. 發送請求至 PC
                    print("[Upload] 上傳影像與音訊頻譜至 PC 推論伺服器...")
                    success, result = self.pc_client.send_inference_request(
                        image_data=img_bytes,
                        audio_data=spec_bytes
                    )
                    
                    if success and result:
                        # 3. 解析結果
                        cls = str(result.get("class")) # 轉字串以防萬一
                        conf = result.get("confidence")
                        is_gemini = result.get("is_gemini")
                        reason = result.get("reasoning", "")
                        
                        source = "Gemini" if is_gemini else "Local"
                        print(f"[Result] 來源: {source} | 類別: {cls} | 信心值: {conf}")
                        if is_gemini:
                            print(f"[Reason] {reason}")

                        # 4. 執行動作 [cite: 153]
                        action = CLASS_MAPPING.get(cls)
                        if action:
                            print(f"[Action] 執行分類: {action['name']} (P:{action['pitch']}, Y:{action['yaw']})")
                            success, err = self.uart.send_move_command(action['pitch'], action['yaw'])
                            if success:
                                # 等待 DONE 訊號
                                resp = self.uart.read_response(timeout=6.0)
                                if resp and "DONE" in resp:
                                    print("[Done] 動作完成")
                                    time.sleep(1.5) # 模擬掉落
                                    self.uart.send_reset_command() # 歸零
                                    self.uart.read_response(timeout=6.0) # 讀取歸零 DONE
                                else:
                                    print(f"[Error] 動作未完成或超時 (回應: {resp})")
                                    self.uart.send_reset_command() # 嘗試歸零恢復
                                    self.uart.read_response(timeout=6.0) # 讀取歸零 DONE
                            else:
                                print(f"[Error] 發送指令失敗: {err}")
                        else:
                            print(f"[Error] 未知類別代碼: {cls}")
                    else:
                        print("[Error] 推論請求失敗 (PC 無回應或錯誤)")

                elif key == ord('q'):
                    break

        except KeyboardInterrupt:
            print("\n程式中斷")
        finally:
            self.cap.release()
            self.uart.disconnect()
            cv2.destroyAllWindows()
            print("資源已釋放，程式結束。")

if __name__ == "__main__":
    controller = RemoteController()
    controller.run()
