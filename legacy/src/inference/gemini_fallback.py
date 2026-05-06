"""
Gemini Fallback - Gemini 雲端備援判斷機制 (整合版)
對應計畫書: [cite: 51, 130, 209, 213, 230]

職責:
- 當本地模型信心值低於閾值時，呼叫 Gemini Pro Vision API
- 提供雲端 AI 的輔助判斷，提升系統可靠性
- 管理 API 金鑰與錯誤處理
- 內部使用 gemini_consultant.py 模組 (CoT + JSON 輸出)

硬體限制: 僅在 PC 層執行
"""

import os
from typing import Dict, Optional
from PIL import Image

# 匯入改進版的 Gemini 輔助諮詢模組
from src.inference.gemini_consultant import get_gemini_consultant, GeminiConsultant

# 預設信心度閾值 (可調整的實驗參數) [cite: 204, 251]
DEFAULT_CONFIDENCE_THRESHOLD = 0.85

class GeminiFallback:
    """
    Gemini 雲端備援機制 (整合版)
    
    當本地模型信心值低於閾值時，使用 Gemini Pro Vision 進行輔助判斷。
    內部使用 gemini_consultant.py 模組，提供 CoT 策略與 JSON 結構化輸出。
    支援影像與文字描述的多模態輸入。
    """
    
    def __init__(
        self, 
        api_key: Optional[str] = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        model_name: str = "gemini-1.5-flash"  # 預設使用 Flash (較快)
    ):
        """
        初始化 Gemini 備援機制
        
        Args:
            api_key: Google Generative AI API 金鑰
                    若為 None，則從環境變數 GOOGLE_API_KEY 讀取
            confidence_threshold: 觸發 Gemini 備援的信心值閾值 [cite: 204, 251]
            model_name: Gemini 模型名稱
                       - "gemini-1.5-flash": 快速回應 (預設)
                       - "gemini-1.5-pro": 更高準確度
        """
        self.confidence_threshold = confidence_threshold
        self.model_name = model_name
        
        # 使用改進版的 GeminiConsultant 模組
        self.consultant = get_gemini_consultant(
            api_key=api_key,
            model_name=model_name
        )
        
        if self.consultant.is_available():
            print(f"[Gemini] 已初始化 Gemini 備援機制 (模型: {model_name}, 閾值: {confidence_threshold:.2f})")
        else:
            print("[Gemini] 警告: Gemini 備援功能將無法使用 (API 未配置)")
    
    def should_use_gemini(self, local_confidence: float) -> bool:
        """
        判斷是否應該使用 Gemini 備援 [cite: 51, 130, 209]
        
        Args:
            local_confidence: 本地模型的信心值
        
        Returns:
            True 如果信心值低於閾值，需要 Gemini 輔助
        """
        return local_confidence < self.confidence_threshold
    
    def classify_with_gemini(
        self, 
        image_input,
        audio_description: Optional[str] = None,
        local_prediction: Optional[str] = None,
        local_confidence: Optional[float] = None
    ) -> Dict[str, any]:
        """
        使用 Gemini Pro Vision 進行分類判斷 (整合版)
        
        對應計畫書中的 Gemini 備援流程 [cite: 213, 230]
        內部使用 gemini_consultant.py 模組，提供 CoT 策略與 JSON 結構化輸出。
        
        Args:
            image_input: 影像輸入 (PIL Image, numpy array, 或檔案路徑)
            audio_description: 音訊特徵的文字描述 (可選，目前未使用但保留介面)
            local_prediction: 本地模型的預測結果 (可選，供 Gemini 參考)
            local_confidence: 本地模型的信心值 (可選，供 Gemini 參考)
        
        Returns:
            {
                "class": "Class A",           # Gemini 預測的類別
                "confidence": 0.95,           # 信心值 (0.0-1.0)
                "reasoning": "...",           # Gemini 的推理過程
                "status": "success"           # 狀態碼
            }
            
            若發生錯誤，status 會包含錯誤類型 (如 "error: timeout", "error: network_error")
        """
        # 使用改進版的 GeminiConsultant 模組
        result = self.consultant.consult(
            image_input=image_input,
            local_prediction=local_prediction,
            local_confidence=local_confidence
        )
        
        # 轉換為與原有介面一致的格式 (category -> class)
        return {
            "class": result.get("category", "unknown"),
            "confidence": result.get("confidence", 0.0),
            "reasoning": result.get("reasoning", ""),
            "status": result.get("status", "error: unknown"),
            # 保留額外資訊供除錯使用
            "model_used": result.get("model_used", self.model_name),
            "response_time": result.get("response_time", 0.0),
            "fallback": result.get("fallback", False)
        }
    
    def update_threshold(self, new_threshold: float):
        """
        動態更新信心度閾值 (用於實驗調整) [cite: 204, 251]
        
        Args:
            new_threshold: 新的信心度閾值 (0.0 ~ 1.0)
        """
        if 0.0 <= new_threshold <= 1.0:
            self.confidence_threshold = new_threshold
            print(f"[Gemini] 信心度閾值已更新: {new_threshold:.2f}")
        else:
            print("[Gemini] 警告: 閾值必須在 0.0 ~ 1.0 之間")
    
    def get_threshold(self) -> float:
        """
        取得當前信心度閾值
        """
        return self.confidence_threshold


# 全域實例 (單例模式)
_gemini_fallback_instance = None

def get_gemini_fallback(
    api_key: Optional[str] = None,
    confidence_threshold: Optional[float] = None,
    model_name: Optional[str] = None
) -> GeminiFallback:
    """
    取得 GeminiFallback 單例實例
    """
    global _gemini_fallback_instance
    if _gemini_fallback_instance is None:
        kwargs = {}
        if api_key is not None:
            kwargs["api_key"] = api_key
        if confidence_threshold is not None:
            kwargs["confidence_threshold"] = confidence_threshold
        if model_name is not None:
            kwargs["model_name"] = model_name
        
        _gemini_fallback_instance = GeminiFallback(**kwargs)
    return _gemini_fallback_instance
