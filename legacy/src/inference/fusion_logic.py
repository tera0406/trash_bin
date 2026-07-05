"""
Fusion Logic - 憭芋????頛?
撠?閮??

?瑁痊:
- ?游?敶勗? (Vision) ?閮?(Audio) ?隢???
- 雿輻????蝑閮??蝯?憿?靽∪???
- ???航矽?渡?甈?? (撖阡?霈?)

蝖祇??: ? PC 撅文銵?
"""

from typing import Dict, Tuple, Optional
import numpy as np

# ?身??甈? (?航矽?渡?撖阡??)
# vision_weight + audio_weight ????1.0
DEFAULT_VISION_WEIGHT = 0.6  # 敶勗?甈?
DEFAULT_AUDIO_WEIGHT = 0.4   # ?唾?甈?

class FusionLogic:
    """
    憭芋????頛?
    
    ?游? EfficientNet 敶勗?颲刻??閮?CNN ????
    雿輻??撟喳?蝑閮??蝯?憿?靽∪??潦?
    """
    
    def __init__(
        self, 
        vision_weight: float = DEFAULT_VISION_WEIGHT,
        audio_weight: float = DEFAULT_AUDIO_WEIGHT
    ):
        """
        ??????頛?
        
        Args:
            vision_weight: 敶勗?甈? (0.0 ~ 1.0)
            audio_weight: ?唾?甈? (0.0 ~ 1.0)
        
        瘜冽?: vision_weight + audio_weight ?餈?1.0
        """
        # 甇??????蝣箔?蝮賢???1.0
        total_weight = vision_weight + audio_weight
        if total_weight > 0:
            self.vision_weight = vision_weight / total_weight
            self.audio_weight = audio_weight / total_weight
        else:
            # ?身??
            self.vision_weight = DEFAULT_VISION_WEIGHT
            self.audio_weight = DEFAULT_AUDIO_WEIGHT
        
        print(f"[Fusion] ??????頛?- Vision: {self.vision_weight:.2f}, Audio: {self.audio_weight:.2f}")
    
    def fuse_predictions(
        self, 
        vision_result: Dict[str, any],
        audio_result: Dict[str, any]
    ) -> Dict[str, any]:
        """
        ??敶勗??閮??刻?蝯?
        
        蝑:
        1. 瑼Ｘ?拙??????(status)
        2. ?乩遙銝蝯?憭望?嚗蝙?冽???蝯? (??蝑)
        3. ?亙???嚗蝙?典?甈???蝞?蝯???雿?
        4. ?詨??擃???憿雿?蝯?憿?
        
        撠?閮?訾葉??璅⊥???瘚?
        
        Args:
            vision_result: VisionEngine ?隢???
            audio_result: AudioEngine ?隢???
        
        Returns:
            {
                "class": "Class A",           # ??敺??葫憿
                "confidence": 0.95,           # ??敺?靽∪???
                "vision_class": "Class A",    # 敶勗??桃?葫
                "vision_confidence": 0.92,    # 敶勗?靽∪???
                "audio_class": "Class A",     # ?唾??桃?葫
                "audio_confidence": 0.88,     # ?唾?靽∪???
                "fusion_probs": {...},        # ??敺?璈???
                "multimodal_status": true,     # ?臬???? (?抵??)
                "status": "success"           # ?湧????
            }
        """
        # 瑼Ｘ???
        vision_ok = vision_result.get("status") == "success"
        audio_ok = audio_result.get("status") == "success"
        
        # ?? 1: ?抵憭望?
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
        
        # ?? 2: ?芣?敶勗??? (??蝑)
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
        
        # ?? 3: ?芣??唾??? (??蝑)
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
        
        # ?? 4: ?抵?? (摰??)
        vision_probs = vision_result.get("all_probs", {})
        audio_probs = audio_result.get("all_probs", {})
        
        # 蝣箔??拙???雿??怎??憿
        all_classes = set(vision_probs.keys()) | set(audio_probs.keys())
        
        # 閮?????敺?璈???
        fusion_probs = {}
        for cls in all_classes:
            vision_prob = vision_probs.get(cls, 0.0)
            audio_prob = audio_probs.get(cls, 0.0)
            # ??撟喳?
            fusion_probs[cls] = (
                self.vision_weight * vision_prob + 
                self.audio_weight * audio_prob
            )
        
        # ?詨??擃???憿
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
            "multimodal_status": True,  # ?抵??
            "status": "success"
        }
    
    def update_weights(self, vision_weight: float, audio_weight: float):
        """
        ???湔??甈? (?冽撖阡?隤踵)
        
        Args:
            vision_weight: ?啁?敶勗?甈?
            audio_weight: ?啁??唾?甈?
        """
        total_weight = vision_weight + audio_weight
        if total_weight > 0:
            self.vision_weight = vision_weight / total_weight
            self.audio_weight = audio_weight / total_weight
            print(f"[Fusion] 甈?撌脫??- Vision: {self.vision_weight:.2f}, Audio: {self.audio_weight:.2f}")
        else:
            print("[Fusion] 霅血?: 甈?蝮賢???0嚗?????)
    
    def get_weights(self) -> Tuple[float, float]:
        """
        ???嗅???甈?
        """
        return (self.vision_weight, self.audio_weight)


# ?典?撖虫? (?桐?璅∪?)
_fusion_logic_instance = None

def get_fusion_logic(
    vision_weight: Optional[float] = None,
    audio_weight: Optional[float] = None
) -> FusionLogic:
    """
    ?? FusionLogic ?桐?撖虫?
    """
    global _fusion_logic_instance
    if _fusion_logic_instance is None:
        if vision_weight is not None and audio_weight is not None:
            _fusion_logic_instance = FusionLogic(vision_weight, audio_weight)
        else:
            _fusion_logic_instance = FusionLogic()
    return _fusion_logic_instance

