"""
PC Client - 與 PC 推論伺服器通訊
對應計畫書: [cite: 197]

職責:
- 透過 HTTP/JSON 與 PC 層推論伺服器通訊
- 發送影像與音訊資料
- 接收分類結果與信心值

硬體限制: 僅在 Raspberry Pi 執行
技術棧: Python, requests
"""

import requests
import time
from typing import Dict, Optional, Tuple
import base64

class PCClient:
    """
    PC 推論伺服器客戶端
    
    負責與 PC 層的 HTTP/JSON 通訊
    """
    
    def __init__(self, pc_host: str = "100.85.67.115", pc_port: int = 5000):
        """
        初始化 PC 客戶端
        
        Args:
            pc_host: PC 推論伺服器的 IP 地址
            pc_port: PC 推論伺服器的端口
        """
        self.pc_host = pc_host
        self.pc_port = pc_port
        self.base_url = f"http://{pc_host}:{pc_port}"
        self.timeout = 10.0  # 請求超時時間 (秒)
    
    def send_inference_request(
        self,
        image_data: Optional[bytes] = None,
        audio_data: Optional[bytes] = None,
        event_id: Optional[str] = None
    ) -> Tuple[bool, Optional[Dict]]:
        """
        發送推論請求給 PC 伺服器
        
        Args:
            image_data: 影像資料 (bytes)
            audio_data: 音訊資料 (bytes)
            event_id: 事件 ID (可選)
        
        Returns:
            (success: bool, result: Optional[Dict])
            result 格式: {
                "class": "Paper",
                "confidence": 0.95,
                "is_gemini": false,
                "reasoning": "..." 
            }
        """
        if not event_id:
            event_id = f"event_{int(time.time())}"
        
        # 構建請求包含 image 與 audio (Base64)
        payload = {
            "image": base64.b64encode(image_data).decode('utf-8') if image_data else None,
            "audio": base64.b64encode(audio_data).decode('utf-8') if audio_data else None,
            #"audio": None, # [Debug] Disable audio
            "event_id": event_id,
            "timestamp": time.time()
        }
        
        try:
            # 發送 HTTP POST 請求
            print(f"[PC Client] Sending request to {self.base_url}/predict...")
            response = requests.post(
                f"{self.base_url}/predict",
                json=payload,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                # 簡單驗證回傳格式
                if "class" in result and "confidence" in result:
                    return (True, result)
                else:
                    print(f"[PC Client] 錯誤: 回傳格式不符 {result.keys()}")
                    return (False, None)
            else:
                print(f"[PC Client] 錯誤: HTTP {response.status_code} - {response.text}")
                return (False, None)
                
        except requests.exceptions.Timeout:
            print(f"[PC Client] 錯誤: 請求超時 (>{self.timeout}秒)")
            return (False, None)
        except requests.exceptions.ConnectionError:
            print(f"[PC Client] 錯誤: 無法連線到 {self.base_url}")
            return (False, None)
        except Exception as e:
            print(f"[PC Client] 錯誤: {str(e)}")
            return (False, None)
    
    def check_connection(self) -> bool:
        """
        檢查與 PC 伺服器的連線
        
        Returns:
            是否連線成功
        """
        try:
            response = requests.get(
                f"{self.base_url}/health",
                timeout=5.0
            )
            return response.status_code == 200
        except:
            return False
