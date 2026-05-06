"""
Communication Manager - 通訊管理模組
對應計畫書: [cite: 197]

職責:
- 管理 PC 層與 Raspberry Pi 之間的通訊
- 支援 HTTP/JSON 與 Socket 通訊協議
- 處理連線錯誤與超時機制 [cite: 47, 91]

硬體限制: PC 層使用
"""

import requests
import socket
import json
import time
from typing import Dict, Optional, Tuple
from urllib.parse import urljoin

class CommManager:
    """
    通訊管理模組
    
    提供統一的介面與 Raspberry Pi 進行通訊
    支援 HTTP/JSON 與 Socket 兩種協議
    """
    
    def __init__(
        self,
        pi_host: str = "192.168.1.100",  # Raspberry Pi 的 IP 地址
        pi_port: int = 5000,              # Pi 的服務端口
        protocol: str = "http",           # 通訊協議: "http" 或 "socket"
        timeout: float = 5.0              # 超時時間 (秒) [cite: 47, 91]
    ):
        """
        初始化通訊管理模組
        
        Args:
            pi_host: Raspberry Pi 的 IP 地址或主機名稱
            pi_port: Raspberry Pi 的服務端口
            protocol: 通訊協議 ("http" 或 "socket")
            timeout: 請求超時時間 (秒)
        """
        self.pi_host = pi_host
        self.pi_port = pi_port
        self.protocol = protocol.lower()
        self.timeout = timeout
        
        # HTTP 協議的基礎 URL
        if self.protocol == "http":
            self.base_url = f"http://{pi_host}:{pi_port}"
        
        print(f"[Comm] 初始化通訊管理模組 - 協議: {protocol}, 目標: {pi_host}:{pi_port}")
    
    def send_prediction_result(
        self,
        event_id: str,
        class_name: str,
        confidence: float,
        multimodal_status: bool,
        is_gemini: bool = False,
        **kwargs
    ) -> Tuple[bool, Optional[str]]:
        """
        發送分類結果給 Raspberry Pi
        
        對應計畫書中的 PC -> Pi 通訊協議 [cite: 197]
        格式: JSON [cite: 163, 200, 236]
        
        Args:
            event_id: 事件 ID
            class_name: 分類結果 (Class A/B/C/D)
            confidence: 信心值
            multimodal_status: 是否成功融合多模態
            is_gemini: 是否使用 Gemini 備援
            **kwargs: 其他額外參數
        
        Returns:
            (success: bool, error_message: Optional[str])
        """
        # 構建 JSON 資料
        data = {
            "event_id": event_id,
            "class": class_name,
            "confidence": confidence,
            "multimodal_status": multimodal_status,
            "is_gemini": is_gemini,
            "timestamp": time.time(),
            **kwargs
        }
        
        if self.protocol == "http":
            return self._send_http(data)
        elif self.protocol == "socket":
            return self._send_socket(data)
        else:
            return (False, f"不支援的通訊協議: {self.protocol}")
    
    def _send_http(self, data: Dict) -> Tuple[bool, Optional[str]]:
        """
        透過 HTTP POST 發送資料
        
        Args:
            data: 要發送的 JSON 資料
        
        Returns:
            (success: bool, error_message: Optional[str])
        """
        try:
            url = urljoin(self.base_url, "/receive_prediction")
            response = requests.post(
                url,
                json=data,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                return (True, None)
            else:
                return (False, f"HTTP {response.status_code}: {response.text}")
                
        except requests.exceptions.Timeout:
            return (False, f"請求超時 (>{self.timeout}秒)")
        except requests.exceptions.ConnectionError:
            return (False, f"無法連線到 {self.pi_host}:{self.pi_port}")
        except Exception as e:
            return (False, f"HTTP 請求錯誤: {str(e)}")
    
    def _send_socket(self, data: Dict) -> Tuple[bool, Optional[str]]:
        """
        透過 Socket 發送資料
        
        Args:
            data: 要發送的 JSON 資料
        
        Returns:
            (success: bool, error_message: Optional[str])
        """
        try:
            # 建立 Socket 連線
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.pi_host, self.pi_port))
            
            # 發送 JSON 資料
            json_data = json.dumps(data) + "\n"  # 添加換行符作為結束標記
            sock.sendall(json_data.encode('utf-8'))
            
            # 接收回應 (可選)
            # response = sock.recv(1024).decode('utf-8')
            
            sock.close()
            return (True, None)
            
        except socket.timeout:
            return (False, f"Socket 連線超時 (>{self.timeout}秒)")
        except socket.error as e:
            return (False, f"Socket 錯誤: {str(e)}")
        except Exception as e:
            return (False, f"Socket 請求錯誤: {str(e)}")
    
    def test_connection(self) -> Tuple[bool, Optional[str]]:
        """
        測試與 Raspberry Pi 的連線
        
        Returns:
            (success: bool, error_message: Optional[str])
        """
        if self.protocol == "http":
            try:
                url = urljoin(self.base_url, "/health")
                response = requests.get(url, timeout=self.timeout)
                if response.status_code == 200:
                    return (True, None)
                else:
                    return (False, f"HTTP {response.status_code}")
            except Exception as e:
                return (False, str(e))
        elif self.protocol == "socket":
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self.timeout)
                result = sock.connect_ex((self.pi_host, self.pi_port))
                sock.close()
                if result == 0:
                    return (True, None)
                else:
                    return (False, f"無法連線 (錯誤碼: {result})")
            except Exception as e:
                return (False, str(e))
        else:
            return (False, f"不支援的通訊協議: {self.protocol}")


# 全域實例 (單例模式)
_comm_manager_instance = None

def get_comm_manager(
    pi_host: Optional[str] = None,
    pi_port: Optional[int] = None,
    protocol: Optional[str] = None
) -> CommManager:
    """
    取得 CommManager 單例實例
    """
    global _comm_manager_instance
    if _comm_manager_instance is None:
        _comm_manager_instance = CommManager(
            pi_host=pi_host or "192.168.1.100",
            pi_port=pi_port or 5000,
            protocol=protocol or "http"
        )
    return _comm_manager_instance
