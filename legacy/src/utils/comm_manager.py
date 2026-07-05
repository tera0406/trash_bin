"""
Communication Manager - ??蝞∠?璅∠?
撠?閮??

?瑁痊:
- 蝞∠? PC 撅方? Raspberry Pi 銋???
- ?舀 HTTP/JSON ??Socket ???降
- ??????航炊??????

蝖祇??: PC 撅支蝙??
"""

import requests
import socket
import json
import time
from typing import Dict, Optional, Tuple
from urllib.parse import urljoin

class CommManager:
    """
    ??蝞∠?璅∠?
    
    ??蝯曹????Ｚ? Raspberry Pi ?脰???
    ?舀 HTTP/JSON ??Socket ?拍車?降
    """
    
    def __init__(
        self,
        pi_host: str = "192.168.1.100",  # Raspberry Pi ??IP ?啣?
        pi_port: int = 5000,              # Pi ???垢??
        protocol: str = "http",           # ???降: "http" ??"socket"
        timeout: float = 5.0              # 頞??? (蝘?
    ):
        """
        ????蝞∠?璅∠?
        
        Args:
            pi_host: Raspberry Pi ??IP ?啣??蜓璈?蝔?
            pi_port: Raspberry Pi ???垢??
            protocol: ???降 ("http" ??"socket")
            timeout: 隢?頞??? (蝘?
        """
        self.pi_host = pi_host
        self.pi_port = pi_port
        self.protocol = protocol.lower()
        self.timeout = timeout
        
        # HTTP ?降?蝷?URL
        if self.protocol == "http":
            self.base_url = f"http://{pi_host}:{pi_port}"
        
        print(f"[Comm] ????蝞∠?璅∠? - ?降: {protocol}, ?格?: {pi_host}:{pi_port}")
    
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
        ?潮?憿??策 Raspberry Pi
        
        撠?閮?訾葉??PC -> Pi ???降
        ?澆?: JSON
        
        Args:
            event_id: 鈭辣 ID
            class_name: ??蝯? (Class A/B/C/D)
            confidence: 靽∪???
            multimodal_status: ?臬????憭芋??
            is_gemini: ?臬雿輻 Gemini ?
            **kwargs: ?嗡?憿??
        
        Returns:
            (success: bool, error_message: Optional[str])
        """
        # 瑽遣 JSON 鞈?
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
            return (False, f"銝?渡????降: {self.protocol}")
    
    def _send_http(self, data: Dict) -> Tuple[bool, Optional[str]]:
        """
        ?? HTTP POST ?潮???
        
        Args:
            data: 閬?? JSON 鞈?
        
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
            return (False, f"隢?頞? (>{self.timeout}蝘?")
        except requests.exceptions.ConnectionError:
            return (False, f"?⊥??????{self.pi_host}:{self.pi_port}")
        except Exception as e:
            return (False, f"HTTP 隢??航炊: {str(e)}")
    
    def _send_socket(self, data: Dict) -> Tuple[bool, Optional[str]]:
        """
        ?? Socket ?潮???
        
        Args:
            data: 閬?? JSON 鞈?
        
        Returns:
            (success: bool, error_message: Optional[str])
        """
        try:
            # 撱箇? Socket ???
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.pi_host, self.pi_port))
            
            # ?潮?JSON 鞈?
            json_data = json.dumps(data) + "\n"  # 瘛餃???蝚虫??箇???閮?
            sock.sendall(json_data.encode('utf-8'))
            
            # ?交?? (?舫)
            # response = sock.recv(1024).decode('utf-8')
            
            sock.close()
            return (True, None)
            
        except socket.timeout:
            return (False, f"Socket ???頞? (>{self.timeout}蝘?")
        except socket.error as e:
            return (False, f"Socket ?航炊: {str(e)}")
        except Exception as e:
            return (False, f"Socket 隢??航炊: {str(e)}")
    
    def test_connection(self) -> Tuple[bool, Optional[str]]:
        """
        皜祈岫??Raspberry Pi ???
        
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
                    return (False, f"?⊥???? (?航炊蝣? {result})")
            except Exception as e:
                return (False, str(e))
        else:
            return (False, f"銝?渡????降: {self.protocol}")


# ?典?撖虫? (?桐?璅∪?)
_comm_manager_instance = None

def get_comm_manager(
    pi_host: Optional[str] = None,
    pi_port: Optional[int] = None,
    protocol: Optional[str] = None
) -> CommManager:
    """
    ?? CommManager ?桐?撖虫?
    """
    global _comm_manager_instance
    if _comm_manager_instance is None:
        _comm_manager_instance = CommManager(
            pi_host=pi_host or "192.168.1.100",
            pi_port=pi_port or 5000,
            protocol=protocol or "http"
        )
    return _comm_manager_instance

