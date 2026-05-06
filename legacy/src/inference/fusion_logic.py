"""
Fusion Logic - 多模態融合邏輯
對應計畫書: [cite: 178, 246]

職責:
- 整合影像 (Vision) 與音訊 (Audio) 的推論結果
- 使用加權融合策略計算最終分類與信心值
- 提供可調整的權重參數 (實驗變因) [cite: 178, 246]

硬體限制: 僅在 PC 層執行
"""

from typing import Dict, Tuple, Optional
import numpy as np

# 預設融合權重 (可調整的實驗參數) [cite: 178, 246]
# vision_weight + audio_weight 應等於 1.0
DEFAULT_VISION_WEIGHT = 0.6  # 影像權重
DEFAULT_AUDIO_WEIGHT = 0.4   # 音訊權重

class FusionLogic:
    """
    多模態融合邏輯
    
    整合 EfficientNet 影像辨識與音訊 CNN 的結果，
    使用加權平均策略計算最終分類與信心值。
    """
    
    def __init__(
        self, 
        vision_weight: float = DEFAULT_VISION_WEIGHT,
        audio_weight: float = DEFAULT_AUDIO_WEIGHT
    ):
        """
        初始化融合邏輯
        
        Args:
            vision_weight: 影像權重 (0.0 ~ 1.0)
            audio_weight: 音訊權重 (0.0 ~ 1.0)
        
        注意: vision_weight + audio_weight 應接近 1.0
        """
        # 正規化權重，確保總和為 1.0
        total_weight = vision_weight + audio_weight
        if total_weight > 0:
            self.vision_weight = vision_weight / total_weight
            self.audio_weight = audio_weight / total_weight
        else:
            # 預設值
            self.vision_weight = DEFAULT_VISION_WEIGHT
            self.audio_weight = DEFAULT_AUDIO_WEIGHT
        
        print(f"[Fusion] 初始化融合邏輯 - Vision: {self.vision_weight:.2f}, Audio: {self.audio_weight:.2f}")
    
    def fuse_predictions(
        self, 
        vision_result: Dict[str, any],
        audio_result: Dict[str, any]
    ) -> Dict[str, any]:
        """
        融合影像與音訊的推論結果
        
        策略:
        1. 檢查兩個結果的狀態 (status)
        2. 若任一結果失敗，使用成功的結果 (降級策略)
        3. 若兩者都成功，使用加權融合計算最終機率分佈
        4. 選取最高機率的類別作為最終分類
        
        對應計畫書中的多模態融合流程 [cite: 178, 246]
        
        Args:
            vision_result: VisionEngine 的推論結果
            audio_result: AudioEngine 的推論結果
        
        Returns:
            {
                "class": "Class A",           # 融合後的預測類別
                "confidence": 0.95,           # 融合後的信心值 [cite: 127, 200]
                "vision_class": "Class A",    # 影像單獨預測
                "vision_confidence": 0.92,    # 影像信心值
                "audio_class": "Class A",     # 音訊單獨預測
                "audio_confidence": 0.88,     # 音訊信心值
                "fusion_probs": {...},        # 融合後的機率分佈
                "multimodal_status": true,     # 是否成功融合 (兩者都成功)
                "status": "success"           # 整體狀態
            }
        """
        # 檢查狀態
        vision_ok = vision_result.get("status") == "success"
        audio_ok = audio_result.get("status") == "success"
        
        # 情況 1: 兩者都失敗
        if not vision_ok and not audio_ok:
            return {
                "class": "unknown",
                "confidence": 0.0,
                "vision_class": vision_result.get("class", "unknown"),
                "vision_confidence": vision_result.get("confidence", 0.0),
                "audio_class": audio_result.get("class", "unknown"),
                "audio_confidence": audio_result.get("confidence", 0.0),
                "fusion_probs": {},
                "multimodal_status": False,
                "status": "error: both_modalities_failed"
            }
        
        # 情況 2: 只有影像成功 (降級策略)
        if vision_ok and not audio_ok:
            return {
                "class": vision_result["class"],
                "confidence": vision_result["confidence"],
                "vision_class": vision_result["class"],
                "vision_confidence": vision_result["confidence"],
                "audio_class": audio_result.get("class", "unknown"),
                "audio_confidence": 0.0,
                "fusion_probs": vision_result.get("all_probs", {}),
                "multimodal_status": False,
                "status": "partial: vision_only"
            }
        
        # 情況 3: 只有音訊成功 (降級策略)
        if audio_ok and not vision_ok:
            return {
                "class": audio_result["class"],
                "confidence": audio_result["confidence"],
                "vision_class": vision_result.get("class", "unknown"),
                "vision_confidence": 0.0,
                "audio_class": audio_result["class"],
                "audio_confidence": audio_result["confidence"],
                "fusion_probs": audio_result.get("all_probs", {}),
                "multimodal_status": False,
                "status": "partial: audio_only"
            }
        
        # 情況 4: 兩者都成功 (完整融合) [cite: 178, 246]
        vision_probs = vision_result.get("all_probs", {})
        audio_probs = audio_result.get("all_probs", {})
        
        # 確保兩個機率分佈包含相同的類別
        all_classes = set(vision_probs.keys()) | set(audio_probs.keys())
        
        # 計算加權融合後的機率分佈
        fusion_probs = {}
        for cls in all_classes:
            vision_prob = vision_probs.get(cls, 0.0)
            audio_prob = audio_probs.get(cls, 0.0)
            # 加權平均 [cite: 178, 246]
            fusion_probs[cls] = (
                self.vision_weight * vision_prob + 
                self.audio_weight * audio_prob
            )
        
        # 選取最高機率的類別
        final_class = max(fusion_probs, key=fusion_probs.get)
        final_confidence = fusion_probs[final_class]
        
        return {
            "class": final_class,
            "confidence": final_confidence,
            "vision_class": vision_result["class"],
            "vision_confidence": vision_result["confidence"],
            "audio_class": audio_result["class"],
            "audio_confidence": audio_result["confidence"],
            "fusion_probs": fusion_probs,
            "multimodal_status": True,  # 兩者都成功 [cite: 163, 236]
            "status": "success"
        }
    
    def update_weights(self, vision_weight: float, audio_weight: float):
        """
        動態更新融合權重 (用於實驗調整) [cite: 178, 246]
        
        Args:
            vision_weight: 新的影像權重
            audio_weight: 新的音訊權重
        """
        total_weight = vision_weight + audio_weight
        if total_weight > 0:
            self.vision_weight = vision_weight / total_weight
            self.audio_weight = audio_weight / total_weight
            print(f"[Fusion] 權重已更新 - Vision: {self.vision_weight:.2f}, Audio: {self.audio_weight:.2f}")
        else:
            print("[Fusion] 警告: 權重總和為 0，保持原值")
    
    def get_weights(self) -> Tuple[float, float]:
        """
        取得當前融合權重
        """
        return (self.vision_weight, self.audio_weight)


# 全域實例 (單例模式)
_fusion_logic_instance = None

def get_fusion_logic(
    vision_weight: Optional[float] = None,
    audio_weight: Optional[float] = None
) -> FusionLogic:
    """
    取得 FusionLogic 單例實例
    """
    global _fusion_logic_instance
    if _fusion_logic_instance is None:
        if vision_weight is not None and audio_weight is not None:
            _fusion_logic_instance = FusionLogic(vision_weight, audio_weight)
        else:
            _fusion_logic_instance = FusionLogic()
    return _fusion_logic_instance
