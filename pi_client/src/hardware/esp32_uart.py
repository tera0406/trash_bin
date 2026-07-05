"""
ESP32 UART - 與 ESP32 通訊模組
對應計畫書:

職責:
- 透過 UART Serial 與 ESP32 通訊
- 封包化指令 (cmd_id, params, CRC)
- 接收 ACK、完成訊號或錯誤碼 (ERR_CODE)

硬體限制: 僅在 Raspberry Pi 執行
技術棧: Python, pyserial
"""

import serial
import time
from typing import Optional, Tuple, Dict
import struct

# 全域共用事件暫存區，防止重量查詢或其它 UART 指令攔截並丟失紅外線主動上報事件
_shared_pending_events = []

class ESP32UART:
    """
    ESP32 UART 通訊模組
    
    負責與 ESP32 層的 UART Serial 通訊
    對應計畫書:
    """
    
    def __init__(
        self,
        port: str = "/dev/ttyUSB0",
        baudrate: int = 115200,
        timeout: float = 1.0
    ):
        """
        初始化 UART 連線
        
        Args:
            port: UART 串口路徑 (例如: /dev/ttyUSB0, /dev/ttyACM0)
            baudrate: 鮑率 (預設 115200)
            timeout: 讀取超時時間 (秒)
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial_conn: Optional[serial.Serial] = None
        self.done_received = False
    
    def connect(self) -> bool:
        """
        建立 UART 連線
        
        Returns:
            是否連線成功
        """
        import os
        import sys
        import glob
        import serial.tools.list_ports

        target_port = self.port
        
        # 檢查連接埠是否存在，若不存在或發生連線錯誤，嘗試自動搜尋可用埠口
        port_exists = False
        try:
            port_exists = os.path.exists(target_port) or sys.platform.startswith('win')
        except:
            pass

        if not port_exists:
            print(f"[ESP32 UART] 警告: 指定的埠口 {target_port} 不存在，正在搜尋可用的序列埠...")
            ports = list(serial.tools.list_ports.comports())
            found_ports = []
            
            # 優先檢查帶有 USB/ACM/CH340/CP210 關鍵字的裝置
            for p in ports:
                desc = p.description or ""
                hwid = p.hwid or ""
                dev = p.device or ""
                if any(x in dev.upper() or x in desc.upper() or x in hwid.upper() for x in ["USB", "ACM", "CH340", "CP210"]):
                    found_ports.append(p.device)
            
            # 備用方案：使用 glob 搜尋 Linux /dev/ttyUSB* 或 /dev/ttyACM*
            if not found_ports:
                found_ports = glob.glob('/dev/ttyUSB*') + glob.glob('/dev/ttyACM*')
                
            if found_ports:
                # 選擇第一個找到的序列埠
                target_port = found_ports[0]
                print(f"[ESP32 UART] 自動選取可用序列埠: {target_port}")
                self.port = target_port
            else:
                print("[ESP32 UART] 錯誤: 未能找到任何可用的序列埠")
                return False

        try:
            self.serial_conn = serial.Serial(
                port=target_port,
                baudrate=self.baudrate,
                timeout=self.timeout
            )
            print(f"[ESP32 UART] 已連線到 {target_port} (baudrate: {self.baudrate})")
            
            # 等待 ESP32 啟動並穩定 (防止 Reset 期間發送指令導致遺失或亂碼)
            print("[ESP32 UART] 正在等待 ESP32 啟動與初始化完成...")
            time.sleep(2.0)
            
            # 清空緩衝區，避免雜訊與開機日誌
            self.serial_conn.reset_input_buffer()
            self.serial_conn.reset_output_buffer()
            print("[ESP32 UART] 緩衝區已清除，準備進行同步")
            
            self._sync_pitch_neutral()
            self._sync_ir_params()
            return True
        except Exception as e:
            print(f"[ESP32 UART] 連線錯誤: {e}")
            # 如果連線失敗，且還有其他可用埠口，在此嘗試搜尋一次
            try:
                ports = list(serial.tools.list_ports.comports())
                found_ports = [p.device for p in ports if p.device != target_port and ("USB" in p.device or "ACM" in p.device or "CH340" in p.description or "CP210" in p.description)]
                if found_ports:
                    alt_port = found_ports[0]
                    print(f"[ESP32 UART] 嘗試備用序列埠連線: {alt_port}")
                    self.serial_conn = serial.Serial(
                        port=alt_port,
                        baudrate=self.baudrate,
                        timeout=self.timeout
                    )
                    self.port = alt_port
                    print(f"[ESP32 UART] 已成功連線到備用序列埠: {alt_port}")
                    # 等待 ESP32 啟動並穩定
                    print("[ESP32 UART] 正在等待 ESP32 啟動與初始化完成...")
                    time.sleep(2.0)
                    
                    self.serial_conn.reset_input_buffer()
                    self.serial_conn.reset_output_buffer()
                    print("[ESP32 UART] 緩衝區已清除，準備進行同步")
                    
                    self._sync_pitch_neutral()
                    self._sync_ir_params()
                    return True
            except:
                pass
            return False
    
    def disconnect(self):
        """關閉 UART 連線"""
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
            print("[ESP32 UART] 連線已關閉")
            
    def _sync_pitch_neutral(self):
        """自動同步 Pi 端的 PITCH_NEUTRAL 基準點給 ESP32"""
        try:
            from config import PITCH_NEUTRAL
            print(f"[ESP32 UART] 正在同步 Pi 端的 Pitch 中立角度 ({PITCH_NEUTRAL}°) 至 ESP32...")
            success, err = self.send_set_neutral(PITCH_NEUTRAL)
            if success:
                print("[ESP32 UART] ✅ Pitch 中立角度同步成功")
            else:
                print(f"[ESP32 UART] ⚠️ Pitch 中立角度同步失敗: {err}")
        except Exception as sync_err:
            print(f"[ESP32 UART] ⚠️ 同步 Pitch 中立角度失敗: {sync_err}")

    def _sync_ir_params(self):
        """自動同步 Pi 端的紅外線消抖參數至 ESP32"""
        try:
            from config import IR_GAP_THRESHOLD_MS, IR_BLOCK_DEBOUNCE_MS, IR_CLEAR_DEBOUNCE_MS
            print(f"[ESP32 UART] 正在同步 Pi 端的紅外線參數 (Gap:{IR_GAP_THRESHOLD_MS}ms, Block:{IR_BLOCK_DEBOUNCE_MS}ms, Clear:{IR_CLEAR_DEBOUNCE_MS}ms) 至 ESP32...")
            success, err = self.send_set_ir_params(IR_GAP_THRESHOLD_MS, IR_BLOCK_DEBOUNCE_MS, IR_CLEAR_DEBOUNCE_MS)
            if success:
                print("[ESP32 UART] ✅ 紅外線消抖參數同步成功")
            else:
                print(f"[ESP32 UART] ⚠️ 紅外線消抖參數同步失敗: {err}")
        except Exception as sync_err:
            print(f"[ESP32 UART] ⚠️ 同步紅外線參數失敗: {sync_err}")

    def send_set_ir_params(self, gap: int, block: int, clear: int) -> Tuple[bool, Optional[str]]:
        """發送設定紅外線消抖參數指令給 ESP32"""
        if not self.serial_conn or not self.serial_conn.is_open:
            if not self.connect():
                return (False, "UART 未連線且重新連線失敗")
        try:
            command = f"SET_IR_PARAM:G:{gap}:B:{block}:C:{clear}\n"
            self.serial_conn.reset_input_buffer()
            self.serial_conn.write(command.encode('utf-8'))
            
            start_time = time.time()
            timeout_limit = 3.0
            while True:
                if time.time() - start_time > timeout_limit:
                    return (False, "等待設定紅外線參數回應超時 (3s)")
                
                response = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                if not response:
                    time.sleep(0.01)
                    continue
                if response.startswith("EVENT:"):
                    _shared_pending_events.append(response)
                    continue
                if "[Debug]" in response:
                    continue
                if response.startswith("ACK"):
                    return (True, None)
                elif response.startswith("ERR"):
                    return (False, response)
        except Exception as e:
            self.disconnect()
            return (False, f"發送紅外線參數指令錯誤: {str(e)}")

    def send_set_neutral(self, pitch: float) -> Tuple[bool, Optional[str]]:
        """
        發送設定 Pitch 中立角指令給 ESP32
        
        Args:
            pitch: Pitch 中立角度 (度)
            
        Returns:
            (success: bool, error_message: Optional[str])
        """
        if not self.serial_conn or not self.serial_conn.is_open:
            print("[ESP32 UART] 偵測到斷線，正在嘗試自動重新連線...")
            if not self.connect():
                return (False, "UART 未連線且重新連線失敗")
        
        try:
            command = f"SET_NEUTRAL:P:{pitch}\n"
            
            # 清除輸入緩衝區，避免殘留資料
            self.serial_conn.reset_input_buffer()
            
            # 發送指令
            self.serial_conn.write(command.encode('utf-8'))
            
            # 等待回應 (過濾 Debug 訊息，尋找 ACK 或 ERR)
            start_time = time.time()
            timeout_limit = 3.0
            
            while True:
                if time.time() - start_time > timeout_limit:
                    return (False, "等待設定中立回應超時 (3s)")
                
                response = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                if not response:
                    time.sleep(0.01)
                    continue
                
                # 攔截並暫存主動上報事件，避免在此遺失
                if response.startswith("EVENT:"):
                    _shared_pending_events.append(response)
                    continue
                
                if "[Debug]" in response:
                    print(f"  [ESP32 Debug] {response}")
                    continue
                
                if response.startswith("ACK"):
                    return (True, None)
                elif response.startswith("ERR"):
                    return (False, response)
                else:
                    print(f"  [ESP32 Info] {response}")
                    continue
                
        except Exception as e:
            print(f"[ESP32 UART] 發送設定中立角指令異常: {e}")
            self.disconnect()
            return (False, f"發送指令錯誤: {str(e)}")
    
    def send_move_command(
        self,
        pitch: float,
        yaw: float
    ) -> Tuple[bool, Optional[str]]:
        """
        發送雲台移動指令
        
        對應計畫書:
        參數範圍: Pitch (-θp 到 +θp), Yaw (-θy 到 +θy)
        
        格式: 文字型指令 `MOVE:P:{pitch}:Y:{yaw}\n`
        或二進制封包 (cmd_id, params, CRC)
        
        Args:
            pitch: Pitch 角度 (度)
            yaw: Yaw 角度 (度)
        
        Returns:
            (success: bool, error_message: Optional[str])
        """
        if not self.serial_conn or not self.serial_conn.is_open:
            print("[ESP32 UART] 偵測到斷線，正在嘗試自動重新連線...")
            if not self.connect():
                return (False, "UART 未連線且重新連線失敗")
        
        try:
            # 文字型指令格式
            command = f"MOVE:P:{pitch}:Y:{yaw}\n"
            
            # 重設已收到的 DONE 旗標
            self.done_received = False
            
            # 清除輸入緩衝區，避免殘留資料
            self.serial_conn.reset_input_buffer()
            
            # 發送指令
            self.serial_conn.write(command.encode('utf-8'))
            
            # 等待回應 (過濾 Debug 訊息，尋找 ACK 或 ERR)
            start_time = time.time()
            timeout_limit = 5.0
            
            while True:
                if time.time() - start_time > timeout_limit:
                    return (False, "等待回應超時 (5s)")
                
                response = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                if not response:
                    time.sleep(0.01)
                    continue
                
                # 攔截並暫存主動上報事件，避免在此遺失
                if response.startswith("EVENT:"):
                    _shared_pending_events.append(response)
                    continue
                
                # 如果是 Debug 訊號，印出來給使用者看，不當作錯誤並繼續等待
                if "[Debug]" in response:
                    print(f"  [ESP32 Debug] {response}")
                    continue
                
                # 如果在等待 ACK 期間已經收到了 DONE，記錄起來
                if "DONE" in response:
                    self.done_received = True
                    print(f"  [ESP32 Info] {response}")
                    continue
                
                if response.startswith("ACK"):
                    return (True, None)
                elif response.startswith("ERR"):
                    return (False, response)
                else:
                    # 其它非協定行也印出並繼續等待
                    print(f"  [ESP32 Info] {response}")
                    continue
                
        except Exception as e:
            print(f"[ESP32 UART] 發送指令異常，關閉連線以觸發重連: {e}")
            self.disconnect()
            return (False, f"發送指令錯誤: {str(e)}")
    
    def send_reset_command(self) -> Tuple[bool, Optional[str]]:
        """
        發送重置指令 (回歸中立姿態)
        
        對應計畫書:
        
        Returns:
            (success: bool, error_message: Optional[str])
        """
        if not self.serial_conn or not self.serial_conn.is_open:
            print("[ESP32 UART] 偵測到斷線，正在嘗試自動重新連線...")
            if not self.connect():
                return (False, "UART 未連線且重新連線失敗")
        
        try:
            # 發送重置指令
            command = "RESET\n"
            
            # 重設已收到的 DONE 旗標
            self.done_received = False
            
            # 清除輸入緩衝區，避免殘留資料導致同步出錯
            self.serial_conn.reset_input_buffer()
            
            # 發送指令
            self.serial_conn.write(command.encode('utf-8'))
            
            # 等待回應 (過濾 Debug 訊息，尋找 ACK 或 ERR)
            start_time = time.time()
            timeout_limit = 5.0
            
            while True:
                if time.time() - start_time > timeout_limit:
                    return (False, "等待重置回應超時 (5s)")
                
                response = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                if not response:
                    time.sleep(0.01)
                    continue
                
                # 攔截並暫存主動上報事件，避免在此遺失
                if response.startswith("EVENT:"):
                    _shared_pending_events.append(response)
                    continue
                
                # 如果是 Debug 訊號，印出來給使用者看，不當作錯誤並繼續等待
                if "[Debug]" in response:
                    print(f"  [ESP32 Debug] {response}")
                    continue
                
                # 如果在等待 ACK 期間已經收到了 DONE，記錄起來
                if "DONE" in response:
                    self.done_received = True
                    print(f"  [ESP32 Info] {response}")
                    continue
                
                if response.startswith("ACK"):
                    return (True, None)
                elif response.startswith("ERR"):
                    return (False, response)
                else:
                    # 其它非協定行也印出並繼續等待
                    print(f"  [ESP32 Info] {response}")
                    continue
                
        except Exception as e:
            print(f"[ESP32 UART] 發送指令異常，關閉連線以觸發重連: {e}")
            self.disconnect()
            return (False, f"發送指令錯誤: {str(e)}")
    
    def read_response(self, timeout: Optional[float] = None) -> Optional[str]:
        """
        讀取 ESP32 的回應 (會循環讀取，直到獲得協定終點符號如 DONE 或 ERR，或超時)
        
        Args:
            timeout: 讀取超時時間 (秒)，若為 None 則使用預設值
        
        Returns:
            回應字串，若超時則返回 None
        """
        # 如果在 send_*_command 期間已經在序列埠中讀到過 DONE，直接回傳即可，不需重複讀取
        if self.done_received:
            self.done_received = False
            return "DONE"
            
        if not self.serial_conn or not self.serial_conn.is_open:
            return None
        
        old_timeout = self.serial_conn.timeout
        read_timeout = timeout if timeout is not None else self.timeout
        self.serial_conn.timeout = 0.05  # 使用極短的讀取超時以進行高頻輪詢與非阻塞列印
        
        start_time = time.time()
        try:
            while True:
                if time.time() - start_time > read_timeout:
                    return None
                
                line_bytes = self.serial_conn.readline()
                if not line_bytes:
                    time.sleep(0.01)
                    continue
                
                response = line_bytes.decode('utf-8', errors='ignore').strip()
                if not response:
                    continue
                
                # 如果是主動上報事件，在背景自動消耗並過濾，暫存到全域佇列中以防丟失
                if response.startswith("EVENT:"):
                    _shared_pending_events.append(response)
                    continue
                
                # 如果是 Debug 訊號，印出來給使用者看
                if "[Debug]" in response:
                    # 雲台致動過程中的偵錯訊息靜默消耗
                    continue
                
                # 如果是我們期盼的 DONE 或是 ERR
                if "DONE" in response:
                    return "DONE"
                elif response.startswith("ERR"):
                    return response
                else:
                    # 其它非協定行也印出
                    print(f"  [ESP32 Info] {response}")
            
        except Exception as e:
            print(f"[ESP32 UART] read_response 異常: {e}")
            return None
        finally:
            try:
                self.serial_conn.timeout = old_timeout
            except:
                pass

    def check_unsolicited_event(self) -> Optional[str]:
        """
        非阻塞地檢查是否有 ESP32 發送的主動事件 (如 EVENT:INPUT_BLOCKED)
        會循環讀空緩衝區中的所有等待行，以防止殘留資料造成觸發延遲與事件堆積。
        同時會優先讀取被其它 UART 查詢攔截並暫存的全域事件佇列。
        
        Returns:
            事件字串，若無則返回 None
        """
        if not self.serial_conn or not self.serial_conn.is_open:
            return None
        try:
            # 優先處理被其它 UART 查詢攔截並暫存的事件
            if _shared_pending_events:
                return _shared_pending_events.pop(0)
            
            # 循環讀取所有暫存在緩衝區中的資料，避免事件排隊與延遲
            while self.serial_conn.in_waiting > 0:
                line = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                if not line:
                    continue
                if line.startswith("EVENT:"):
                    return line
                else:
                    # 如果不是 EVENT，可能是 debug 訊號或完成訊號，印出來
                    print(f"  [ESP32 Unsolicited] {line}")
            return None
        except Exception as e:
            print(f"[ESP32 UART] 讀取主動事件異常: {e}")
            return None

    def get_ir_status(self) -> Tuple[bool, Optional[str]]:
        """
        發送 GET_IR 指令查詢入口紅外線感測器狀態
        
        Returns:
            (in_blocked: bool, error_msg: Optional[str])
        """
        if not self.serial_conn or not self.serial_conn.is_open:
            return False, "UART 未連線"
        try:
            self.serial_conn.reset_input_buffer()
            self.serial_conn.write(b"GET_IR\n")
            
            start_time = time.time()
            timeout_limit = 2.0
            while True:
                if time.time() - start_time > timeout_limit:
                    return False, "查詢超時"
                response = self.serial_conn.readline().decode('utf-8', errors='ignore').strip()
                if not response:
                    time.sleep(0.01)
                    continue
                # 攔截並暫存主動上報事件，避免在此遺失
                if response.startswith("EVENT:"):
                    _shared_pending_events.append(response)
                    continue
                if response.startswith("IR:IN:"):
                    parts = response.split(":")
                    in_val = parts[2] == "1"
                    return in_val, None
                elif response.startswith("ERR"):
                    return False, response
        except Exception as e:
            return False, str(e)
