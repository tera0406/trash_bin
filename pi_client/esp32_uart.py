"""
ESP32 UART - 與 ESP32 通訊模組
對應計畫書: [cite: 114, 137, 138]

職責:
- 透過 UART Serial 與 ESP32 通訊
- 封包化指令 (cmd_id, params, CRC)
- 接收 ACK、完成訊號或錯誤碼 (ERR_CODE) [cite: 112, 117]

硬體限制: 僅在 Raspberry Pi 執行
技術棧: Python, pyserial
"""

import serial
import time
from typing import Optional, Tuple, Dict
import struct

class ESP32UART:
    """
    ESP32 UART 通訊模組
    
    負責與 ESP32 層的 UART Serial 通訊
    對應計畫書: [cite: 114, 137, 138]
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
    
    def connect(self) -> bool:
        """
        建立 UART 連線
        
        Returns:
            是否連線成功
        """
        try:
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout
            )
            print(f"[ESP32 UART] 已連線到 {self.port} (baudrate: {self.baudrate})")
            
            # 清空緩衝區，避免雜訊
            self.serial_conn.reset_input_buffer()
            self.serial_conn.reset_output_buffer()
            print("[ESP32 UART] 緩衝區已清除")
            
            return True
        except Exception as e:
            print(f"[ESP32 UART] 連線錯誤: {e}")
            return False
    
    def disconnect(self):
        """關閉 UART 連線"""
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
            print("[ESP32 UART] 連線已關閉")
    
    def send_move_command(
        self,
        pitch: float,
        yaw: float
    ) -> Tuple[bool, Optional[str]]:
        """
        發送雲台移動指令
        
        對應計畫書: [cite: 146, 148, 149, 150]
        參數範圍: Pitch (-θp 到 +θp), Yaw (-θy 到 +θy) [cite: 153, 154, 155, 156]
        
        格式: 文字型指令 `MOVE:P:{pitch}:Y:{yaw}\n` [cite: 114]
        或二進制封包 (cmd_id, params, CRC) [cite: 137, 138]
        
        Args:
            pitch: Pitch 角度 (度)
            yaw: Yaw 角度 (度)
        
        Returns:
            (success: bool, error_message: Optional[str])
        """
        if not self.serial_conn or not self.serial_conn.is_open:
            return (False, "UART 未連線")
        
        try:
            # 文字型指令格式 [cite: 114]
            command = f"MOVE:P:{pitch}:Y:{yaw}\n"
            
            # 發送指令
            self.serial_conn.write(command.encode('utf-8'))
            
            # 等待回應 (ACK 或錯誤碼) [cite: 112, 117]
            response = self.serial_conn.readline().decode('utf-8').strip()
            
            if response.startswith("ACK"):
                return (True, None)
            elif response.startswith("ERR"):
                return (False, response)
            else:
                return (False, f"未知回應: {response}")
                
        except Exception as e:
            return (False, f"發送指令錯誤: {str(e)}")
    
    def send_reset_command(self) -> Tuple[bool, Optional[str]]:
        """
        發送重置指令 (回歸中立姿態)
        
        對應計畫書: [cite: 111, 151, 323]
        
        Returns:
            (success: bool, error_message: Optional[str])
        """
        return self.send_move_command(pitch=0.0, yaw=0.0)
    
    def read_response(self, timeout: Optional[float] = None) -> Optional[str]:
        """
        讀取 ESP32 的回應
        
        Args:
            timeout: 讀取超時時間 (秒)，若為 None 則使用預設值
        
        Returns:
            回應字串，若超時則返回 None
        """
        if not self.serial_conn or not self.serial_conn.is_open:
            return None
        
        old_timeout = self.serial_conn.timeout
        if timeout is not None:
            self.serial_conn.timeout = timeout
        
        try:
            response = self.serial_conn.readline().decode('utf-8').strip()
            return response if response else None
        except:
            return None
        finally:
            self.serial_conn.timeout = old_timeout
