"""
Gemini Consultant - Gemini 頛隢株岷璅∠? (?寥脩?)
撠?閮??

?瑁痊:
- ?嗆??EfficientNet 璅∪?靽∪??潔??潮?潭?嚗??迨???抵垣閰Ｙ頂蝯晞?
- ?? Gemini ??閬箸?????璅∠?????銴??釭???見??
- 雿輻 Chain-of-Thought (CoT) 蝑?脰?蝯????
- 撘瑕頛詨 JSON ?澆?嚗???category, confidence, reasoning

蝖祇??: ? PC 撅文銵?
"""

import os
import json
import time
from typing import Dict, Optional, Union, Any
from PIL import Image

# ?啁? SDK ?臬
from google import genai
from google.genai import types

# ???憿摰儔 (??唳芋????
CLASS_CATEGORIES = ["Paper", "Plastic", "General", "Metal"]

# ?身 API ?暹??? (蝘?
DEFAULT_TIMEOUT = 10.0

# ?身璅∪??迂 (Gemini 1.5 Flash 頛翰嚗ro 頛?蝣?
DEFAULT_MODEL_NAME = "gemini-1.5-flash"


class GeminiConsultant:
    """
    Gemini 頛隢株岷璅∠?
    
    ?詨??:
    1. 雿輻 Chain-of-Thought (CoT) 蝑撘?璅∪??函?
    2. 撘瑕頛詨 JSON ?澆?嚗噶?澆?蝥???
    3. ?? API ?暹??雯頝舫隤歹?????蝑
    4. ?撠? Token 頛詨隞亦葬?剖??辣??
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = DEFAULT_MODEL_NAME,
        timeout: float = DEFAULT_TIMEOUT,
        temperature: float = 0.3  # 頛?皞怠漲隞亦敺帘摰撓??
    ):
        """
        ????Gemini 頛隢株岷璅∠?
        
        Args:
            api_key: Google Generative AI API ?
                    ?亦 None嚗?敺憓???GOOGLE_API_KEY 霈??
            model_name: Gemini 璅∪??迂
                       - "gemini-1.5-flash": 敹恍????拙??單??
                       - "gemini-1.5-pro": ?湧?皞Ⅱ摨佗?雿???
            timeout: API ?澆?暹??? (蝘?
            temperature: 璅∪?皞怠漲 (0.0-1.0)嚗?雿潛?蝣箏??扯撓??
        """
        # ?? API ?
        if api_key is None:
            api_key = os.getenv("GOOGLE_API_KEY")
        
        self.client = None
        if not api_key:
            print("[GeminiConsultant] 霅血?: ?芾身摰?API ?嚗emini 頛?撠瘜蝙??)
            print("[GeminiConsultant] 隢身摰憓???GOOGLE_API_KEY ? .env 瑼?銝剛身摰?)
        else:
            self.api_key = api_key
            try:
                # ????Client (?啁? SDK)
                self.client = genai.Client(api_key=api_key)
                print(f"[GeminiConsultant] 撌脣?憪? Gemini Client")
            except Exception as e:
                print(f"[GeminiConsultant] ???隤? {e}")
                self.client = None
        
        self.model_name = model_name
        self.timeout = timeout
        self.temperature = temperature
        
        # 閮剖?銝阡??遣蝡?Config (?啁? SDK)
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
        瑽遣 Chain-of-Thought (CoT) ?內閰?
        
        蝑:
        1. 撘?璅∪???撖?鞈芰敺蛛?????摨艾釭?堆?
        2. 閫撖耦???瑽敺?
        3. 蝯?閫撖??脰????函?
        4. 撘瑕頛詨 JSON ?澆?
        
        Args:
            local_prediction: ?砍璅∪???皜祉???(?舫嚗???
            local_confidence: ?砍璅∪??縑敹?(?舫)
        
        Returns:
            摰??CoT ?內閰?銝?
        """
        # ?箇?隞餃?隤芣?
        prompt_parts = [
            "雿銝??批??曉?憿頂蝯梁? AI 憿批???,
            "隢蝙?具雁??(Chain-of-Thought)???亙??撐敶勗???,
            "",
            "?郊撽?1: ?釭?孵噩閫撖?,
            "隢?閫撖誑銝?鞈芰敺蛛?",
            "- ???? ?臬??嚗?憒? ?惇???????",
            "- ??摨? ?臬??????嚗?憒? ?餌??嗚?憛?)",
            "- 鞈芸: 銵券鞈芣? (??/蝎?/??/?′)",
            "- 憿???? 銝餉?憿??行??寞?蝝?",
            "",
            "?郊撽?2: 敶Ｙ???瑽?撖?,
            "隢?撖?",
            "- ?湧?敶Ｙ? (?耦/?孵耦/銝???",
            "- 蝯??孵噩 (?臬?????蝐扎畾身閮?",
            "- 撠箏站瘥?",
            "",
            "?郊撽?3: ???函???,
            "?寞?銝膩閫撖??斗?飛憿隞乩??芯?憿?",
            f"- Paper: 蝝? (憒? 蝝撐???縑撠???",
            f"- Plastic: 憛? (憒? 撖嗥?嗚???????)",
            f"- General: 銝?砍???(憒? 撱???????瘙∪?????鞈?",
            f"- Metal: ?惇 (憒? ?菟?蝵?撅祈?)",
            "",
        ]
        
        # 憒???圈?皜祉??????閮?
        if local_prediction:
            conf_info = f" (靽∪??? {local_confidence:.2f})" if local_confidence else ""
            prompt_parts.append(
                f"????閮?唳芋??皜祉: {local_prediction}{conf_info}嚗?
                "雿縑敹潸?雿?隢??拍Ⅱ隤?靽格迤??
            )
            prompt_parts.append("")
        
        # JSON 頛詨?澆?閬? (?撠? Token嚗閬?敹?甈?)
        prompt_parts.extend([
            "?撓?箸撘?,
            "隢誑 JSON ?澆???嚗??隞乩?銝?雿?",
            "{",
            '  "category": "Paper/Plastic/General/Metal",',
            '  "confidence": 0.0-1.0,',
            '  "reasoning": "蝪∠?函?靘? (50摮誑??"',
            "}",
            "",
            "瘜冽?:",
            "- category 敹???Paper/Plastic/General/Metal ?嗡葉銋?",
            "- confidence ??0.0-1.0 ?筑暺嚗”蝷箔?撠?憿?蝣箔縑蝔漲",
            "- reasoning 隢陛?剛牧??瑚???(?箸甇仿? 1-3 ??撖?",
            "- 銝??隞颱??嗡???嚗頛詨 JSON ?拐辣"
        ])
        
        return "\n".join(prompt_parts)
    
    def consult(
        self,
        image_input: Union[Image.Image, str, bytes],
        local_prediction: Optional[str] = None,
        local_confidence: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        ?瑁? Gemini 頛隢株岷
        
        撠?閮?訾葉??Gemini ?瘚?
        
        Args:
            image_input: 敶勗?頛詨
                        - PIL Image ?拐辣
                        - 瑼?頝臬?摮葡
                        - bytes (敶勗?鞈?)
            local_prediction: ?砍璅∪???皜祉???(?舫)
            local_confidence: ?砍璅∪??縑敹?(?舫)
        
        Returns:
            {
                "category": "Class A",           # 撱箄降憿
                "confidence": 0.95,              # 靽∪???(0.0-1.0)
                "reasoning": "...",              # 蝪∠?函?靘?
                "status": "success",             # ??Ⅳ
                "model_used": "gemini-1.5-flash", # 雿輻?芋??
                "response_time": 1.23            # API ???? (蝘?
            }
            
            ?亦?隤?
            {
                "category": "unknown",
                "confidence": 0.0,
                "reasoning": "?航炊閮",
                "status": "error: timeout" ??"error: network_error" 蝑?
                "fallback": true                # 璅??粹?蝝???
            }
        """
        if self.client is None:
            return {
                "category": "unknown",
                "confidence": 0.0,
                "reasoning": "Gemini API ?芸?憪? (蝻箏? API ?)",
                "status": "error: api_not_configured",
                "fallback": True
            }
        
        start_time = time.time()
        
        try:
            # 1. 皞?敶勗?
            if isinstance(image_input, str):
                # 瑼?頝臬?
                img = Image.open(image_input)
            elif isinstance(image_input, Image.Image):
                img = image_input
            elif isinstance(image_input, bytes):
                # bytes 鞈?
                from io import BytesIO
                img = Image.open(BytesIO(image_input))
            else:
                raise ValueError(f"銝?渡?敶勗??澆?: {type(image_input)}")
            
            # 蝣箔???RGB ?澆?
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # 2. 瑽遣 CoT ?內閰?
            prompt = self._build_cot_prompt(
                local_prediction=local_prediction,
                local_confidence=local_confidence
            )
            
            # 3. ?澆 Gemini API (撣園暹?????閰行???
            try:
                max_retries = 3
                response = None
                
                for attempt in range(max_retries):
                    try:
                        # 撖阡? API ?澆 (?啁? SDK)
                        response = self.client.models.generate_content(
                            model=self.model_name,
                            contents=[prompt, img],
                            config=self.generation_config
                        )
                        break # ???歲?粹?閰西艘??
                        
                    except Exception as e:
                        error_str = str(e)
                        # 瑼Ｘ?臬??429 Resource Exhausted
                        if ("429" in error_str or "RESOURCE_EXHAUSTED" in error_str) and attempt < max_retries - 1:
                            wait_time = 10 * (attempt + 1) # 10s, 20s...
                            print(f"[GeminiConsultant] 霅血?: API ??? (429). {wait_time} 蝘??岫 ({attempt+1}/{max_retries})...")
                            time.sleep(wait_time)
                            continue
                        else:
                            # ?嗡??航炊???憭折?閰行活?賂??湔?
                            raise e

                response_time = time.time() - start_time
                
                # 4. 閫??????
                if response.text:
                    response_text = response.text.strip()
                else:
                    # ?⊥???????嚗楛?交炎?亙???
                    finish_reason = "UNKNOWN"
                    safety_ratings = []
                    
                    try:
                        if response.candidates and len(response.candidates) > 0:
                            candidate = response.candidates[0]
                            finish_reason = getattr(candidate, 'finish_reason', 'UNKNOWN')
                            safety_ratings = getattr(candidate, 'safety_ratings', [])
                    except Exception as e:
                        print(f"[GeminiConsultant] ?⊥?霈??candidate 鞈?: {e}")

                    print(f"[GeminiConsultant] ???⊥?摮摰嫘inish Reason: {finish_reason}")
                    print(f"[GeminiConsultant] Safety Ratings: {safety_ratings}")
                    
                    return {
                        "category": "unknown",
                        "confidence": 0.0,
                        "reasoning": f"Model returned no text. Reason: {finish_reason}",
                        "status": "error: no_text_content",
                        "fallback": True,
                        "response_time": round(response_time, 3)
                    }
                
                # 5. ?岫?? JSON (?航鋡?```json ?ㄨ??交 JSON)
                json_text = response_text
                
                # 蝘駁?航??markdown 蝔?蝣澆?憛?閮?
                if "```json" in json_text:
                    json_text = json_text.split("```json")[1].split("```")[0].strip()
                elif "```" in json_text:
                    json_text = json_text.split("```")[1].split("```")[0].strip()
                
                # 6. 閫?? JSON
                try:
                    result_dict = json.loads(json_text)
                except json.JSONDecodeError as e:
                    # JSON 閫??憭望?嚗?閰血???銝剜????菔?閮?
                    print(f"[GeminiConsultant] JSON 閫??憭望?: {e}")
                    print(f"[GeminiConsultant] ????: {response_text[:200]}...")
                    return self._fallback_parse(response_text, response_time)
                
                # 7. 撽???皞?頛詨
                category = result_dict.get("category", "unknown")
                confidence = float(result_dict.get("confidence", 0.0))
                reasoning = result_dict.get("reasoning", "")
                
                # 撽? category ?臬?箸?????
                if category not in CLASS_CATEGORIES:
                    # ?岫敺?reasoning ??category 銝剜????亙?蝔?
                    for cls in CLASS_CATEGORIES:
                        if cls.lower() in category.lower() or cls.lower() in reasoning.lower():
                            category = cls
                            break
                    else:
                        category = "unknown"
                
                # 蝣箔? confidence ?冽????
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
                # API ?澆?航炊 (?航?舫暹??雯頝舫隤斤?)
                response_time = time.time() - start_time
                error_msg = str(api_error)
                
                # ?斗?航炊憿?
                if "timeout" in error_msg.lower() or response_time >= self.timeout:
                    status = "error: timeout"
                elif "network" in error_msg.lower() or "connection" in error_msg.lower():
                    status = "error: network_error"
                elif "quota" in error_msg.lower() or "rate limit" in error_msg.lower():
                    status = "error: quota_exceeded"
                else:
                    status = f"error: {type(api_error).__name__}"
                
                print(f"[GeminiConsultant] API ?航炊: {error_msg}")
                
                return {
                    "category": "unknown",
                    "confidence": 0.0,
                    "reasoning": f"Gemini API ?航炊: {error_msg}",
                    "status": status,
                    "fallback": True,
                    "response_time": round(response_time, 3)
                }
        
        except Exception as e:
            # ?嗡??航炊 (敶勗????撘隤斤?)
            response_time = time.time() - start_time
            print(f"[GeminiConsultant] ???航炊: {e}")
            
            return {
                "category": "unknown",
                "confidence": 0.0,
                "reasoning": f"???航炊: {str(e)}",
                "status": f"error: {type(e).__name__}",
                "fallback": True,
                "response_time": round(response_time, 3)
            }
    
    def _fallback_parse(self, response_text: str, response_time: float) -> Dict[str, Any]:
        """
        ??JSON 閫??憭望?????閫??蝑
        
        ?岫敺?摮??葉??憿?縑敹漲鞈?
        """
        category = "unknown"
        confidence = 0.5  # ?身銝剔?靽∪?摨?
        
        # ?岫??憿?迂
        response_lower = response_text.lower()
        for cls in CLASS_CATEGORIES:
            if cls.lower() in response_lower:
                category = cls
                # ?寞??摮矽?港縑敹漲
                if "蝣箏?" in response_text or "?＊" in response_text or "皜?" in response_text:
                    confidence = 0.9
                elif "?航" in response_text or "隡潔?" in response_text or "?冽葫" in response_text:
                    confidence = 0.7
                break
        
        return {
            "category": category,
            "confidence": confidence,
            "reasoning": f"??閫??: {response_text[:100]}",
            "status": "success: fallback_parse",
            "model_used": self.model_name,
            "response_time": round(response_time, 3)
        }
    
    def is_available(self) -> bool:
        """
        瑼Ｘ Gemini API ?臬?舐
        
        Returns:
            True 憒? API 撌脫迤蝣箏?憪?銝??
        """
        return self.client is not None


# ?典?撖虫? (?桐?璅∪?嚗??銴?憪?)
_gemini_consultant_instance = None

def get_gemini_consultant(
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
    timeout: Optional[float] = None
) -> GeminiConsultant:
    """
    ?? GeminiConsultant ?桐?撖虫?
    
    ?踹??????芋??蝭??皞???
    
    Args:
        api_key: API ? (??甈∪?急???)
        model_name: 璅∪??迂 (??甈∪?急???)
        timeout: ?暹??? (??甈∪?急???)
    
    Returns:
        GeminiConsultant 撖虫?
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

