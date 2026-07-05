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

import os
import requests
import time
from typing import Dict, Optional, Tuple
import base64
try:
    from env_loader import load_env
except ImportError:
    import sys
    import os
    parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    from env_loader import load_env

# 載入環境變數設定
load_env()

class PCClient:
    """
    PC 推論伺服器客戶端
    
    負責與 PC 層的 HTTP/JSON 通訊
    """
    
    def __init__(self, pc_host: str = None, pc_port: int = None):
        """
        初始化 PC 客戶端 (優先從環境變數讀取)
        
        Args:
            pc_host: PC 推論伺服器的 IP 地址
            pc_port: PC 推論伺服器的端口
        """
        self.pc_host = pc_host or os.getenv("PC_SERVER_IP", "100.85.67.115")
        
        env_port = os.getenv("PC_SERVER_PORT")
        if pc_port is not None:
            self.pc_port = pc_port
        elif env_port:
            self.pc_port = int(env_port)
        else:
            self.pc_port = 5000
            
        self.base_url = f"http://{self.pc_host}:{self.pc_port}"
        self.timeout = 10.0  # 請求超時時間 (秒)
    
    def send_inference_request(
        self,
        image_data: Optional[bytes] = None,
        audio_data: Optional[bytes] = None,
        event_id: Optional[str] = None
    ) -> Tuple[bool, Optional[Dict]]:
        """
        發送推論請求給 PC 伺服器 (使用 multipart/form-data 傳送影像與音訊頻譜圖)
        
        Args:
            image_data: 影像二進位資料 (bytes)
            audio_data: 音訊頻譜圖二進位資料 (bytes, 即 Mel-spectrogram 影像)
            event_id: 事件 ID (可選)
        
        Returns:
            (success: bool, result: Optional[Dict])
            result 格式: {
                "label": "paper",
                "class": "paper",       # 向後相容欄位
                "confidence": 0.95,
                "is_gemini": false,
                "reasoning": "..." 
            }
        """
        if not event_id:
            event_id = f"event_{int(time.time())}"
        
        # 構建 multipart/form-data 請求檔案字典
        files = {}
        if image_data:
            files["image"] = ("image.jpg", image_data, "image/jpeg")
        if audio_data:
            files["audio_spec"] = ("audio_spec.jpg", audio_data, "image/jpeg")
            
        try:
            # 發送 HTTP POST 請求 (使用 files 參數發送 multipart/form-data)
            print(f"[PC Client] Sending request to {self.base_url}/predict...")
            response = requests.post(
                f"{self.base_url}/predict",
                files=files,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                # 簡單驗證回傳格式 (同時相容 label 與 class)
                if ("label" in result or "class" in result) and "confidence" in result:
                    # 雙向相容處理
                    if "label" in result and "class" not in result:
                        result["class"] = result["label"]
                    elif "class" in result and "label" not in result:
                        result["label"] = result["class"]
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
