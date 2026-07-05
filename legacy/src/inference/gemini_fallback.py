"""
Gemini Fallback - Gemini ?脩垢??斗璈 (?游???
撠?閮??

?瑁痊:
- ?嗆?唳芋?縑敹潔??潮?潭?嚗??Gemini Pro Vision API
- ???脩垢 AI ???拙?瘀???蝟餌絞?舫???
- 蝞∠? API ??隤方???
- ?折雿輻 gemini_consultant.py 璅∠? (CoT + JSON 頛詨)

蝖祇??: ? PC 撅文銵?
"""

import os
from typing import Dict, Optional
from PIL import Image

# ?臬?寥脩???Gemini 頛隢株岷璅∠?
from src.inference.gemini_consultant import get_gemini_consultant, GeminiConsultant

# ?身靽∪?摨阡??(?航矽?渡?撖阡??)
DEFAULT_CONFIDENCE_THRESHOLD = 0.85

class GeminiFallback:
    """
    Gemini ?脩垢?璈 (?游???
    
    ?嗆?唳芋?縑敹潔??潮?潭?嚗蝙??Gemini Pro Vision ?脰?頛?斗??
    ?折雿輻 gemini_consultant.py 璅∠?嚗?靘?CoT 蝑??JSON 蝯??撓?箝?
    ?舀敶勗???摮?餈啁?憭芋?撓?乓?
    """
    
    def __init__(
        self, 
        api_key: Optional[str] = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        model_name: str = "gemini-1.5-flash"  # ?身雿輻 Flash (頛翰)
    ):
        """
        ????Gemini ?璈
        
        Args:
            api_key: Google Generative AI API ?
                    ?亦 None嚗?敺憓???GOOGLE_API_KEY 霈??
            confidence_threshold: 閫貊 Gemini ??縑敹潮??
            model_name: Gemini 璅∪??迂
                       - "gemini-1.5-flash": 敹恍???(?身)
                       - "gemini-1.5-pro": ?湧?皞Ⅱ摨?
        """
        self.confidence_threshold = confidence_threshold
        self.model_name = model_name
        
        # 雿輻?寥脩???GeminiConsultant 璅∠?
        self.consultant = get_gemini_consultant(
            api_key=api_key,
            model_name=model_name
        )
        
        if self.consultant.is_available():
            print(f"[Gemini] 撌脣?憪? Gemini ?璈 (璅∪?: {model_name}, ?曉? {confidence_threshold:.2f})")
        else:
            print("[Gemini] 霅血?: Gemini ??撠瘜蝙??(API ?芷?蝵?")
    
    def should_use_gemini(self, local_confidence: float) -> bool:
        """
        ?斗?臬?府雿輻 Gemini ?
        
        Args:
            local_confidence: ?砍璅∪??縑敹?
        
        Returns:
            True 憒?靽∪??潔??潮?潘??閬?Gemini 頛
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
        雿輻 Gemini Pro Vision ?脰????斗 (?游???
        
        撠?閮?訾葉??Gemini ?瘚?
        ?折雿輻 gemini_consultant.py 璅∠?嚗?靘?CoT 蝑??JSON 蝯??撓?箝?
        
        Args:
            image_input: 敶勗?頛詨 (PIL Image, numpy array, ??獢楝敺?
            audio_description: ?唾??孵噩??摮?餈?(?舫嚗?雿輻雿?????
            local_prediction: ?砍璅∪???皜祉???(?舫嚗? Gemini ??
            local_confidence: ?砍璅∪??縑敹?(?舫嚗? Gemini ??
        
        Returns:
            {
                "class": "Class A",           # Gemini ?葫????
                "confidence": 0.95,           # 靽∪???(0.0-1.0)
                "reasoning": "...",           # Gemini ???蝔?
                "status": "success"           # ??Ⅳ
            }
            
            ?亦?隤歹?status ???恍隤日???(憒?"error: timeout", "error: network_error")
        """
        # 雿輻?寥脩???GeminiConsultant 璅∠?
        result = self.consultant.consult(
            image_input=image_input,
            local_prediction=local_prediction,
            local_confidence=local_confidence
        )
        
        # 頧??箄???隞銝?渡??澆? (category -> class)
        return {
            "class": result.get("category", "unknown"),
            "confidence": result.get("confidence", 0.0),
            "reasoning": result.get("reasoning", ""),
            "status": result.get("status", "error: unknown"),
            # 靽?憿?鞈?靘?臭蝙??
            "model_used": result.get("model_used", self.model_name),
            "response_time": result.get("response_time", 0.0),
            "fallback": result.get("fallback", False)
        }
    
    def update_threshold(self, new_threshold: float):
        """
        ???湔靽∪?摨阡??(?冽撖阡?隤踵)
        
        Args:
            new_threshold: ?啁?靽∪?摨阡??(0.0 ~ 1.0)
        """
        if 0.0 <= new_threshold <= 1.0:
            self.confidence_threshold = new_threshold
            print(f"[Gemini] 靽∪?摨阡?澆歇?湔: {new_threshold:.2f}")
        else:
            print("[Gemini] 霅血?: ?曉澆?? 0.0 ~ 1.0 銋?")
    
    def get_threshold(self) -> float:
        """
        ???嗅?靽∪?摨阡??
        """
        return self.confidence_threshold


# ?典?撖虫? (?桐?璅∪?)
_gemini_fallback_instance = None

def get_gemini_fallback(
    api_key: Optional[str] = None,
    confidence_threshold: Optional[float] = None,
    model_name: Optional[str] = None
) -> GeminiFallback:
    """
    ?? GeminiFallback ?桐?撖虫?
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

