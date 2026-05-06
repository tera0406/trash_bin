"""
Gemini Fallback - Gemini 雲端備援判斷機制
移植自 legacy/src/inference/gemini_consultant.py，適配交叉融合架構。

職責:
- 當交叉融合模型信心值低於閾值時，呼叫 Gemini Pro Vision API
- 使用 Chain-of-Thought (CoT) 策略進行結構化推理
- 強制輸出 JSON 格式，包含 label, confidence, reasoning
- 處理 API 逾時、配額耗盡等錯誤，並優雅降級

硬體限制: 僅在 PC 層執行
"""

import os
import json
import time
from io import BytesIO
from typing import Dict, Optional, Union, Any

from PIL import Image
from google import genai
from google.genai import types

# 垃圾分類類別定義 (與本地模型一致)
CLASS_LABELS = ["general", "plastic", "paper", "metal"]

# 預設參數
DEFAULT_CONFIDENCE_THRESHOLD = 0.50
DEFAULT_MODEL_NAME = "gemini-2.0-flash"
DEFAULT_TIMEOUT = 15.0


class GeminiFallback:
    """
    Gemini 雲端備援機制

    當交叉融合模型的信心值低於閾值時，使用 Gemini Pro Vision
    進行思維鏈 (CoT) 輔助判斷。若 Gemini 呼叫失敗，
    則優雅降級，保留本地模型的原始結果。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        model_name: str = DEFAULT_MODEL_NAME,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.confidence_threshold = confidence_threshold
        self.model_name = model_name
        self.timeout = timeout
        self.client = None

        # 讀取 API 金鑰
        resolved_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not resolved_key:
            print("[GeminiFallback] 警告: 未設定 GOOGLE_API_KEY，Gemini 備援功能將無法使用")
        else:
            try:
                self.client = genai.Client(api_key=resolved_key)
                print(
                    f"[GeminiFallback] 已初始化 (模型: {model_name}, "
                    f"信心值閾值: {confidence_threshold:.2f})"
                )
            except Exception as e:
                print(f"[GeminiFallback] 初始化失敗: {e}")

        # 建立 GenerateContentConfig (與 legacy 版一致)
        self._config = types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=512,
            safety_settings=[
                types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
            ],
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """檢查 Gemini API 是否已初始化可用"""
        return self.client is not None

    def should_fallback(self, confidence: float) -> bool:
        """判斷信心值是否低於閾值，需要啟用 Gemini 備援"""
        return confidence < self.confidence_threshold

    def classify(
        self,
        image_input: Union[Image.Image, bytes],
        local_label: Optional[str] = None,
        local_confidence: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        執行 Gemini 輔助分類

        Args:
            image_input : PIL Image 或 raw bytes
            local_label : 本地模型的預測標籤 (供 Gemini 參考)
            local_confidence: 本地模型的信心值 (供 Gemini 參考)

        Returns:
            {
              "label"      : "paper",   # 最終標籤
              "confidence" : 0.92,
              "reasoning"  : "...",
              "is_gemini"  : True,
              "status"     : "success"
            }
            失敗時 is_gemini=False，回傳本地結果。
        """
        if self.client is None:
            return self._local_fallback(local_label, local_confidence, "api_not_configured")

        start = time.time()

        try:
            # 準備 PIL Image
            if isinstance(image_input, bytes):
                img = Image.open(BytesIO(image_input))
            else:
                img = image_input

            if img.mode != "RGB":
                img = img.convert("RGB")

            prompt = self._build_cot_prompt(local_label, local_confidence)

            # 呼叫 API，最多重試 3 次 (處理 429 配額耗盡)
            response = None
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = self.client.models.generate_content(
                        model=self.model_name,
                        contents=[prompt, img],
                        config=self._config,
                    )
                    break
                except Exception as e:
                    err = str(e)
                    if ("429" in err or "RESOURCE_EXHAUSTED" in err) and attempt < max_retries - 1:
                        wait = 10 * (attempt + 1)
                        print(f"[GeminiFallback] 配額耗盡 (429)，{wait}s 後重試 ({attempt+1}/{max_retries})...")
                        time.sleep(wait)
                    else:
                        raise

            elapsed = time.time() - start

            # 解析回應
            if not response or not response.text:
                return self._local_fallback(local_label, local_confidence, "no_text_response")

            return self._parse_response(response.text, elapsed)

        except Exception as e:
            elapsed = time.time() - start
            err = str(e)
            if "timeout" in err.lower() or elapsed >= self.timeout:
                status = "timeout"
            elif "network" in err.lower() or "connection" in err.lower():
                status = "network_error"
            else:
                status = type(e).__name__
            print(f"[GeminiFallback] API 錯誤 ({status}): {err}")
            return self._local_fallback(local_label, local_confidence, status)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_cot_prompt(
        self,
        local_label: Optional[str],
        local_confidence: Optional[float],
    ) -> str:
        """構建 Chain-of-Thought 提示詞 (移植自 legacy gemini_consultant.py)"""
        lines = [
            "你是一個智慧垃圾分類系統的 AI 顧問。",
            "請使用「思維鏈 (Chain-of-Thought)」策略分析這張影像。",
            "",
            "【步驟 1: 材質特徵觀察】",
            "請先觀察以下材質特徵：",
            "- 反光性: 是否反光？(如: 金屬、玻璃、塑膠光面)",
            "- 透明度: 是否透明或半透明？(如: 玻璃瓶、透明塑膠)",
            "- 質地: 表面質感 (光滑/粗糙/柔軟/堅硬)",
            "- 顏色與紋理: 主要顏色與是否有特殊紋理",
            "",
            "【步驟 2: 形狀與結構觀察】",
            "請觀察：",
            "- 整體形狀 (圓形/方形/不規則)",
            "- 結構特徵 (是否有開口、標籤、特殊設計)",
            "- 尺寸比例",
            "",
            "【步驟 3: 分類推理】",
            "根據上述觀察，判斷應歸類為以下哪一類：",
            "- paper  : 紙類 (如: 紙張、紙盒、信封、紙杯)",
            "- plastic: 塑膠 (如: 寶特瓶、塑膠盒、塑膠袋)",
            "- general: 一般垃圾 (如: 廚餘、衛生紙、髒污塑膠、複合材質)",
            "- metal  : 金屬 (如: 鐵鋁罐、金屬蓋)",
            "",
        ]

        if local_label:
            conf_str = f" (信心值: {local_confidence:.2f})" if local_confidence is not None else ""
            lines.append(
                f"【參考資訊】本地交叉融合模型預測為: {local_label}{conf_str}，"
                "但信心值較低，請協助確認或修正。"
            )
            lines.append("")

        lines.extend([
            "【輸出格式】",
            "請以 JSON 格式回覆，僅包含以下三個欄位：",
            "{",
            '  "label": "paper/plastic/general/metal",',
            '  "confidence": 0.0-1.0,',
            '  "reasoning": "簡短推理依據 (50字以內)"',
            "}",
            "",
            "注意:",
            "- label 必須是 paper/plastic/general/metal 其中之一 (全小寫)",
            "- confidence 為 0.0~1.0 的浮點數",
            "- 不要包含任何其他文字，只輸出 JSON 物件",
        ])

        return "\n".join(lines)

    def _parse_response(self, text: str, response_time: float) -> Dict[str, Any]:
        """解析 Gemini 回應文字，轉為標準格式"""
        json_text = text.strip()

        # 移除可能的 markdown 程式碼區塊
        if "```json" in json_text:
            json_text = json_text.split("```json")[1].split("```")[0].strip()
        elif "```" in json_text:
            json_text = json_text.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(json_text)
        except json.JSONDecodeError:
            print(f"[GeminiFallback] JSON 解析失敗，嘗試降級解析。原始: {text[:150]}")
            return self._fallback_parse(text, response_time)

        label = str(data.get("label", "unknown")).lower()
        confidence = float(data.get("confidence", 0.0))
        reasoning = data.get("reasoning", "")

        # 驗證 label
        if label not in CLASS_LABELS:
            # 嘗試從文字中比對
            for cls in CLASS_LABELS:
                if cls in label or cls in reasoning.lower():
                    label = cls
                    break
            else:
                label = "general"  # 無法辨識時預設一般垃圾

        confidence = max(0.0, min(1.0, confidence))

        print(f"[GeminiFallback] 成功 | label={label}, confidence={confidence:.3f}, 耗時={response_time:.2f}s")

        return {
            "label": label,
            "confidence": confidence,
            "reasoning": reasoning,
            "is_gemini": True,
            "status": "success",
            "model_used": self.model_name,
            "response_time_ms": round(response_time * 1000, 1),
        }

    def _fallback_parse(self, text: str, response_time: float) -> Dict[str, Any]:
        """JSON 解析失敗時的降級文字解析策略"""
        label = "general"
        confidence = 0.6
        text_lower = text.lower()

        for cls in CLASS_LABELS:
            if cls in text_lower:
                label = cls
                if any(kw in text for kw in ["確定", "明顯", "清楚"]):
                    confidence = 0.85
                elif any(kw in text for kw in ["可能", "似乎", "推測"]):
                    confidence = 0.65
                break

        return {
            "label": label,
            "confidence": confidence,
            "reasoning": f"降級解析: {text[:80]}",
            "is_gemini": True,
            "status": "success: fallback_parse",
            "model_used": self.model_name,
            "response_time_ms": round(response_time * 1000, 1),
        }

    def _local_fallback(
        self,
        local_label: Optional[str],
        local_confidence: Optional[float],
        reason: str,
    ) -> Dict[str, Any]:
        """Gemini 不可用時，降級保留本地推論結果"""
        print(f"[GeminiFallback] 降級至本地結果 (原因: {reason})")
        return {
            "label": local_label or "general",
            "confidence": local_confidence or 0.0,
            "reasoning": f"Gemini unavailable ({reason}), using local result.",
            "is_gemini": False,
            "status": f"fallback: {reason}",
        }


# ------------------------------------------------------------------
# 單例工廠
# ------------------------------------------------------------------
_instance: Optional[GeminiFallback] = None


def get_gemini_fallback(
    confidence_threshold: Optional[float] = None,
    model_name: Optional[str] = None,
) -> GeminiFallback:
    """取得 GeminiFallback 單例（首次呼叫時初始化）"""
    global _instance
    if _instance is None:
        kwargs: Dict[str, Any] = {}
        if confidence_threshold is not None:
            kwargs["confidence_threshold"] = confidence_threshold
        if model_name is not None:
            kwargs["model_name"] = model_name
        _instance = GeminiFallback(**kwargs)
    return _instance
