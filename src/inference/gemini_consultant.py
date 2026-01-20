"""
Gemini Consultant - Gemini 輔助諮詢模組 (改進版)
對應計畫書: [cite: 51, 130, 209, 213, 230]

職責:
- 當本地 EfficientNet 模型信心值低於閾值時，啟動此「輔助諮詢系統」
- 透過 Gemini 的視覺推理能力，處理模糊、重疊或複合材質的困難樣本
- 使用 Chain-of-Thought (CoT) 策略進行結構化推理
- 強制輸出 JSON 格式，包含 category, confidence, reasoning

硬體限制: 僅在 PC 層執行
"""

import os
import json
import time
from typing import Dict, Optional, Union, Any
from PIL import Image

# 新版 SDK 匯入
from google import genai
from google.genai import types

# 垃圾分類類別定義 (與本地模型一致) [cite: 152]
CLASS_CATEGORIES = ["Paper", "Plastic", "General", "Metal"]

# 預設 API 逾時時間 (秒)
DEFAULT_TIMEOUT = 10.0

# 預設模型名稱 (Gemini 1.5 Flash 較快，Pro 較準確)
DEFAULT_MODEL_NAME = "gemini-1.5-flash"


class GeminiConsultant:
    """
    Gemini 輔助諮詢模組
    
    核心功能:
    1. 使用 Chain-of-Thought (CoT) 策略引導模型推理
    2. 強制輸出 JSON 格式，便於後續處理
    3. 處理 API 逾時與網路錯誤，提供降級策略
    4. 最小化 Token 輸出以縮短回應延遲
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = DEFAULT_MODEL_NAME,
        timeout: float = DEFAULT_TIMEOUT,
        temperature: float = 0.3  # 較低溫度以獲得穩定輸出
    ):
        """
        初始化 Gemini 輔助諮詢模組
        
        Args:
            api_key: Google Generative AI API 金鑰
                    若為 None，則從環境變數 GOOGLE_API_KEY 讀取
            model_name: Gemini 模型名稱
                       - "gemini-1.5-flash": 快速回應，適合即時應用
                       - "gemini-1.5-pro": 更高準確度，但較慢
            timeout: API 呼叫逾時時間 (秒)
            temperature: 模型溫度 (0.0-1.0)，較低值產生更確定性輸出
        """
        # 取得 API 金鑰
        if api_key is None:
            api_key = os.getenv("GOOGLE_API_KEY")
        
        self.client = None
        if not api_key:
            print("[GeminiConsultant] 警告: 未設定 API 金鑰，Gemini 輔助功能將無法使用")
            print("[GeminiConsultant] 請設定環境變數 GOOGLE_API_KEY 或在 .env 檔案中設定")
        else:
            self.api_key = api_key
            try:
                # 初始化 Client (新版 SDK)
                self.client = genai.Client(api_key=api_key)
                print(f"[GeminiConsultant] 已初始化 Gemini Client")
            except Exception as e:
                print(f"[GeminiConsultant] 初始化錯誤: {e}")
                self.client = None
        
        self.model_name = model_name
        self.timeout = timeout
        self.temperature = temperature
        
        # 設定並預先建立 Config (新版 SDK)
        self.generation_config = types.GenerateContentConfig(
            temperature=self.temperature,
            max_output_tokens=1024,
            safety_settings=[
                types.SafetySetting(
                    category="HARM_CATEGORY_HATE_SPEECH",
                    threshold="BLOCK_NONE",
                ),
                types.SafetySetting(
                    category="HARM_CATEGORY_HARASSMENT",
                    threshold="BLOCK_NONE",
                ),
                types.SafetySetting(
                    category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    threshold="BLOCK_NONE",
                ),
                types.SafetySetting(
                    category="HARM_CATEGORY_DANGEROUS_CONTENT",
                    threshold="BLOCK_NONE",
                ),
            ]
        )
    
    def _build_cot_prompt(
        self,
        local_prediction: Optional[str] = None,
        local_confidence: Optional[float] = None
    ) -> str:
        """
        構建 Chain-of-Thought (CoT) 提示詞
        
        策略:
        1. 引導模型先觀察材質特徵（反光、透明度、質地）
        2. 觀察形狀與結構特徵
        3. 結合觀察結果進行分類推理
        4. 強制輸出 JSON 格式
        
        Args:
            local_prediction: 本地模型的預測結果 (可選，供參考)
            local_confidence: 本地模型的信心值 (可選)
        
        Returns:
            完整的 CoT 提示詞字串
        """
        # 基礎任務說明
        prompt_parts = [
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
            f"- Paper: 紙類 (如: 紙張、紙盒、信封、紙杯)",
            f"- Plastic: 塑膠 (如: 寶特瓶、塑膠盒、塑膠袋)",
            f"- General: 一般垃圾 (如: 廚餘、衛生紙、髒污塑膠、複合材質)",
            f"- Metal: 金屬 (如: 鐵鋁罐、金屬蓋)",
            "",
        ]
        
        # 如果有本地預測結果，加入參考資訊
        if local_prediction:
            conf_info = f" (信心值: {local_confidence:.2f})" if local_confidence else ""
            prompt_parts.append(
                f"【參考資訊】本地模型預測為: {local_prediction}{conf_info}，"
                "但信心值較低，請協助確認或修正。"
            )
            prompt_parts.append("")
        
        # JSON 輸出格式要求 (最小化 Token，只要求必要欄位)
        prompt_parts.extend([
            "【輸出格式】",
            "請以 JSON 格式回覆，僅包含以下三個欄位：",
            "{",
            '  "category": "Paper/Plastic/General/Metal",',
            '  "confidence": 0.0-1.0,',
            '  "reasoning": "簡短推理依據 (50字以內)"',
            "}",
            "",
            "注意:",
            "- category 必須是 Paper/Plastic/General/Metal 其中之一",
            "- confidence 為 0.0-1.0 的浮點數，表示你對分類的確信程度",
            "- reasoning 請簡短說明判斷依據 (基於步驟 1-3 的觀察)",
            "- 不要包含任何其他文字，只輸出 JSON 物件"
        ])
        
        return "\n".join(prompt_parts)
    
    def consult(
        self,
        image_input: Union[Image.Image, str, bytes],
        local_prediction: Optional[str] = None,
        local_confidence: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        執行 Gemini 輔助諮詢
        
        對應計畫書中的 Gemini 備援流程 [cite: 213, 230]
        
        Args:
            image_input: 影像輸入
                        - PIL Image 物件
                        - 檔案路徑字串
                        - bytes (影像資料)
            local_prediction: 本地模型的預測結果 (可選)
            local_confidence: 本地模型的信心值 (可選)
        
        Returns:
            {
                "category": "Class A",           # 建議類別
                "confidence": 0.95,              # 信心值 (0.0-1.0)
                "reasoning": "...",              # 簡短推理依據
                "status": "success",             # 狀態碼
                "model_used": "gemini-1.5-flash", # 使用的模型
                "response_time": 1.23            # API 回應時間 (秒)
            }
            
            若發生錯誤:
            {
                "category": "unknown",
                "confidence": 0.0,
                "reasoning": "錯誤訊息",
                "status": "error: timeout" 或 "error: network_error" 等,
                "fallback": true                # 標記為降級狀態
            }
        """
        if self.client is None:
            return {
                "category": "unknown",
                "confidence": 0.0,
                "reasoning": "Gemini API 未初始化 (缺少 API 金鑰)",
                "status": "error: api_not_configured",
                "fallback": True
            }
        
        start_time = time.time()
        
        try:
            # 1. 準備影像
            if isinstance(image_input, str):
                # 檔案路徑
                img = Image.open(image_input)
            elif isinstance(image_input, Image.Image):
                img = image_input
            elif isinstance(image_input, bytes):
                # bytes 資料
                from io import BytesIO
                img = Image.open(BytesIO(image_input))
            else:
                raise ValueError(f"不支援的影像格式: {type(image_input)}")
            
            # 確保為 RGB 格式
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # 2. 構建 CoT 提示詞
            prompt = self._build_cot_prompt(
                local_prediction=local_prediction,
                local_confidence=local_confidence
            )
            
            # 3. 呼叫 Gemini API (帶逾時處理與重試機制)
            try:
                max_retries = 3
                response = None
                
                for attempt in range(max_retries):
                    try:
                        # 實際 API 呼叫 (新版 SDK)
                        response = self.client.models.generate_content(
                            model=self.model_name,
                            contents=[prompt, img],
                            config=self.generation_config
                        )
                        break # 成功則跳出重試迴圈
                        
                    except Exception as e:
                        error_str = str(e)
                        # 檢查是否為 429 Resource Exhausted
                        if ("429" in error_str or "RESOURCE_EXHAUSTED" in error_str) and attempt < max_retries - 1:
                            wait_time = 10 * (attempt + 1) # 10s, 20s...
                            print(f"[GeminiConsultant] 警告: API 配額耗盡 (429). {wait_time} 秒後重試 ({attempt+1}/{max_retries})...")
                            time.sleep(wait_time)
                            continue
                        else:
                            # 其他錯誤或達最大重試次數，直接拋出
                            raise e

                response_time = time.time() - start_time
                
                # 4. 解析回應文字
                if response.text:
                    response_text = response.text.strip()
                else:
                    # 無法取得文字回應，深入檢查原因
                    finish_reason = "UNKNOWN"
                    safety_ratings = []
                    
                    try:
                        if response.candidates and len(response.candidates) > 0:
                            candidate = response.candidates[0]
                            finish_reason = getattr(candidate, 'finish_reason', 'UNKNOWN')
                            safety_ratings = getattr(candidate, 'safety_ratings', [])
                    except Exception as e:
                        print(f"[GeminiConsultant] 無法讀取 candidate 資訊: {e}")

                    print(f"[GeminiConsultant] 回應無文字內容。Finish Reason: {finish_reason}")
                    print(f"[GeminiConsultant] Safety Ratings: {safety_ratings}")
                    
                    return {
                        "category": "unknown",
                        "confidence": 0.0,
                        "reasoning": f"Model returned no text. Reason: {finish_reason}",
                        "status": "error: no_text_content",
                        "fallback": True,
                        "response_time": round(response_time, 3)
                    }
                
                # 5. 嘗試提取 JSON (可能被 ```json 包裹或直接是 JSON)
                json_text = response_text
                
                # 移除可能的 markdown 程式碼區塊標記
                if "```json" in json_text:
                    json_text = json_text.split("```json")[1].split("```")[0].strip()
                elif "```" in json_text:
                    json_text = json_text.split("```")[1].split("```")[0].strip()
                
                # 6. 解析 JSON
                try:
                    result_dict = json.loads(json_text)
                except json.JSONDecodeError as e:
                    # JSON 解析失敗，嘗試從文字中提取關鍵資訊
                    print(f"[GeminiConsultant] JSON 解析失敗: {e}")
                    print(f"[GeminiConsultant] 原始回應: {response_text[:200]}...")
                    return self._fallback_parse(response_text, response_time)
                
                # 7. 驗證與標準化輸出
                category = result_dict.get("category", "unknown")
                confidence = float(result_dict.get("confidence", 0.0))
                reasoning = result_dict.get("reasoning", "")
                
                # 驗證 category 是否為有效類別
                if category not in CLASS_CATEGORIES:
                    # 嘗試從 reasoning 或 category 中提取類別名稱
                    for cls in CLASS_CATEGORIES:
                        if cls.lower() in category.lower() or cls.lower() in reasoning.lower():
                            category = cls
                            break
                    else:
                        category = "unknown"
                
                # 確保 confidence 在有效範圍內
                confidence = max(0.0, min(1.0, confidence))
                
                return {
                    "category": category,
                    "confidence": confidence,
                    "reasoning": reasoning,
                    "status": "success",
                    "model_used": self.model_name,
                    "response_time": round(response_time, 3)
                }
                
            except Exception as api_error:
                # API 呼叫錯誤 (可能是逾時、網路錯誤等)
                response_time = time.time() - start_time
                error_msg = str(api_error)
                
                # 判斷錯誤類型
                if "timeout" in error_msg.lower() or response_time >= self.timeout:
                    status = "error: timeout"
                elif "network" in error_msg.lower() or "connection" in error_msg.lower():
                    status = "error: network_error"
                elif "quota" in error_msg.lower() or "rate limit" in error_msg.lower():
                    status = "error: quota_exceeded"
                else:
                    status = f"error: {type(api_error).__name__}"
                
                print(f"[GeminiConsultant] API 錯誤: {error_msg}")
                
                return {
                    "category": "unknown",
                    "confidence": 0.0,
                    "reasoning": f"Gemini API 錯誤: {error_msg}",
                    "status": status,
                    "fallback": True,
                    "response_time": round(response_time, 3)
                }
        
        except Exception as e:
            # 其他錯誤 (影像處理、格式錯誤等)
            response_time = time.time() - start_time
            print(f"[GeminiConsultant] 處理錯誤: {e}")
            
            return {
                "category": "unknown",
                "confidence": 0.0,
                "reasoning": f"處理錯誤: {str(e)}",
                "status": f"error: {type(e).__name__}",
                "fallback": True,
                "response_time": round(response_time, 3)
            }
    
    def _fallback_parse(self, response_text: str, response_time: float) -> Dict[str, Any]:
        """
        當 JSON 解析失敗時的降級解析策略
        
        嘗試從文字回應中提取類別與信心度資訊
        """
        category = "unknown"
        confidence = 0.5  # 預設中等信心度
        
        # 嘗試提取類別名稱
        response_lower = response_text.lower()
        for cls in CLASS_CATEGORIES:
            if cls.lower() in response_lower:
                category = cls
                # 根據關鍵字調整信心度
                if "確定" in response_text or "明顯" in response_text or "清楚" in response_text:
                    confidence = 0.9
                elif "可能" in response_text or "似乎" in response_text or "推測" in response_text:
                    confidence = 0.7
                break
        
        return {
            "category": category,
            "confidence": confidence,
            "reasoning": f"降級解析: {response_text[:100]}",
            "status": "success: fallback_parse",
            "model_used": self.model_name,
            "response_time": round(response_time, 3)
        }
    
    def is_available(self) -> bool:
        """
        檢查 Gemini API 是否可用
        
        Returns:
            True 如果 API 已正確初始化且可用
        """
        return self.client is not None


# 全域實例 (單例模式，避免重複初始化)
_gemini_consultant_instance = None

def get_gemini_consultant(
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
    timeout: Optional[float] = None
) -> GeminiConsultant:
    """
    取得 GeminiConsultant 單例實例
    
    避免重複初始化模型，節省資源與時間
    
    Args:
        api_key: API 金鑰 (僅首次呼叫時有效)
        model_name: 模型名稱 (僅首次呼叫時有效)
        timeout: 逾時時間 (僅首次呼叫時有效)
    
    Returns:
        GeminiConsultant 實例
    """
    global _gemini_consultant_instance
    if _gemini_consultant_instance is None:
        kwargs = {}
        if api_key is not None:
            kwargs["api_key"] = api_key
        if model_name is not None:
            kwargs["model_name"] = model_name
        if timeout is not None:
            kwargs["timeout"] = timeout
        
        _gemini_consultant_instance = GeminiConsultant(**kwargs)
    return _gemini_consultant_instance
