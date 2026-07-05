"""
AIOT ?箸?獢?- Level 1 PC ??撅?(Inference Server)
撠?撠?閮?貊?蝭: 1111 (PC ??撅斗瑽?

?祉?撘?鞎祆?嗡???Level 2 (Raspberry Pi) ?蔣???唾?鞈?嚗?
?瑁?憭芋??AI ?刻?嚗蒂?冽?唬縑敹潔?頞單?隤輻 Gemini API ?脰?頛?斗??

蝟餌絞?嗆?:
1. 頛詨: 敶勗? (Base64) + ?唾? (Base64)
2. 閬死璅∪?: EfficientNet (Keras)
3. ?質死璅∪?: MFCC + CNN
4. 瘙箇??摩: 憭芋????(Hybrid Decision Gate)
5. ?脩垢?: Google Gemini 1.5 Pro (CoT ?雁??

Author: Professional Backend Engineer
Date: 2026-01-08
"""

import os
import time
import base64
import io
import json
from typing import Dict, Any, Optional

from flask import Flask, request, jsonify
from flask_cors import CORS
from PIL import Image
import numpy as np
from dotenv import load_dotenv

# 頛?啣?霈 (API Key, 璅∪?頝臬?蝑?
load_dotenv()

# ?臬撠??Ｘ???AI ?刻?璅∠? (OOP 撠?)
from src.inference.vision_engine import get_vision_engine
from src.inference.audio_engine import get_audio_engine
from src.inference.fusion_logic import get_fusion_logic
from src.inference.gemini_fallback import get_gemini_fallback

# ===== ????Flask ?蝔? =====
app = Flask(__name__)
CORS(app)  # ?迂頝典?隢?嚗靘?Pi ??PC ???

# ===== ?典?閮剖??祕撽???(撠?閮?貉??? =====
# ??靽∪??曉?theta
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD"))
# ??甈? (敶勗??芸?)
VISION_WEIGHT = float(os.getenv("VISION_WEIGHT"))
AUDIO_WEIGHT = float(os.getenv("AUDIO_WEIGHT"))

# ===== ???隢???(?桐?璅∪?) =====
print("[System] 甇?頛 AI 璅∪?...")
# 3333: 頛 EfficientNet 閬死璅∪?
vision_model_path = os.getenv("VISION_MODEL_PATH")
vision_engine = get_vision_engine(model_path=vision_model_path)
# 4: 頛 CNN ?質死璅∪?
audio_model_path = os.getenv("AUDIO_MODEL_PATH") 
audio_engine = get_audio_engine(model_path=audio_model_path)
# 5: ??????頛?
fusion_logic = get_fusion_logic(vision_weight=VISION_WEIGHT, audio_weight=AUDIO_WEIGHT)
# 777777777: ????Gemini ?璈 (閮剖??曉?
gemini_model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-flash-latest")
gemini_fallback = get_gemini_fallback(
    confidence_threshold=CONFIDENCE_THRESHOLD,
    model_name=gemini_model_name
)
print("[System] AI 璅∪?頛摰?嚗撩?皞?撠梁???)


@app.route('/predict', methods=['POST'])
def predict():
    """
    銝餉??刻??亙 (Endpoint)
    
    ?:
    1. ?交 Raspberry Pi 銝??JSON 鞈? (?敶勗??閮?
    2. ?瑁??砍憭芋?隢?(Vision + Audio)
    3. 瑼Ｘ靽∪??潘??乩??潮?澆?閫貊 Gemini ?
    4. ??蝯?憿???(JSON)
    """
    try:
        # 1. 閫??隢?鞈?
        data = request.json
        if not data:
            return jsonify({"error": "No data provided", "class": "error", "confidence": 0.0}), 400

        image_b64 = data.get("image")
        audio_b64 = data.get("audio")
        
        # 閮??????? (?冽閮?撱園)
        start_time = time.time()
        print(f"[Request] ?嗅?刻?隢?嚗?憪???..")

        # 2. 閬死?刻? (EfficientNet)
        vision_result = {"status": "skipped", "confidence": 0.0, "all_probs": {}}
        gemini_image = None
        
        if image_b64:
            try:
                # 閫?Ⅳ Base64 敶勗?
                img_bytes = base64.b64decode(image_b64)
                gemini_image = Image.open(io.BytesIO(img_bytes)) # 靽?靘?Gemini 雿輻
                
                # ?瑁??刻?
                # VisionEngine ?折撌脣祕雿?????EfficientNet ?刻?
                vision_result = vision_engine.predict(gemini_image)
                print(f"[Vision] 憿: {vision_result.get('class')}, 靽∪??? {vision_result.get('confidence'):.3f}")
            except Exception as e:
                print(f"[Vision Error] {e}")

        # 3. ?質死?刻? (MFCC + CNN)
        audio_result = {"status": "skipped", "confidence": 0.0, "all_probs": {}}
        if audio_b64:
            try:
                # 閫?Ⅳ Base64 ?唾?
                audio_bytes = base64.b64decode(audio_b64)
                
                # ?瑁??刻? (Transform to MFCC -> CNN)
                audio_result = audio_engine.predict(audio_bytes)
                print(f"[Audio] 憿: {audio_result.get('class')}, 靽∪??? {audio_result.get('confidence'):.3f}")
            except Exception as e:
                print(f"[Audio Error] {e}")

        # 4. 憭芋????(Hybrid Decision Gate)
        # 雿輻?脤璅∪?靽∪??潔??箸??耨甇??閬箄撓??
        fusion_result = fusion_logic.fuse_predictions(vision_result, audio_result)
        
        final_class = fusion_result["class"]
        final_confidence = fusion_result["confidence"]
        
        print(f"[Fusion] ??蝯?: {final_class}, 靽∪??? {final_confidence:.3f}")

        # 5. 瘙箇??摩: ?斗?臬?閬?Gemini ?
        # ?交?唬縑敹?< theta (0.8)嚗?隤輻 Gemini
        is_gemini_used = False
        reasoning = "Local inference sufficient."
        
        if gemini_fallback.should_use_gemini(final_confidence):
            print(f"[Decision] 靽∪???({final_confidence:.3f}) < ?曉?({CONFIDENCE_THRESHOLD})嚗?????Gemini ?...")
            
            if gemini_image:
                print(f"[Gemini] ?嗅敶勗??拐辣嚗?憪?恍蝡?API...")
                # 9999: ?游???雁??(CoT)??蝷箇??伐?閬? Gemini ??撖?鞈芾?敶Ｙ?
                gemini_response = gemini_fallback.classify_with_gemini(
                    image_input=gemini_image,
                    local_prediction=final_class,
                    local_confidence=final_confidence
                )
                
                # 瑼Ｘ Gemini ?臬?? (? fallback_parse)嚗憭望???蝝??砍蝯?
                if gemini_response.get("status", "").startswith("success"):
                    final_class = gemini_response.get("class", "unknown")
                    final_confidence = gemini_response.get("confidence", 0.0)
                    reasoning = gemini_response.get("reasoning", "")
                    is_gemini_used = True
                    print(f"[Gemini] 靽格迤蝯?: {final_class}, ??: {reasoning[:50]}...")
                else:
                    print(f"[Fallback] Gemini ?澆憭望? ({gemini_response.get('status')})嚗?蝝蝙?冽?唳隢???)
                    reasoning = f"Gemini failed ({gemini_response.get('status')}), used local result."
                    is_gemini_used = False
            else:
                reasoning = "Low confidence but no image for Gemini."

        # 閮?蝮賢辣??
        latency = (time.time() - start_time) * 1000
        print(f"[Done] 蝮質?: {latency:.2f} ms")

        # 6. 撱箸?? JSON
        response_data = {
            "class": final_class,          # A/B/C/D (撠? Paper/Plastic/General/Metal)
            "confidence": round(final_confidence, 3),
            "is_gemini": is_gemini_used,
            "reasoning": reasoning,
            "latency_ms": round(latency, 2)
        }
        
        return jsonify(response_data)

    except Exception as e:
        print(f"[Server Error] {e}")
        return jsonify({"error": str(e), "class": "error", "confidence": 0.0}), 500

if __name__ == '__main__':
    # ??隡箸???
    # 蝣箔?蝬? 0.0.0.0 隞交??Tailscale ???
    print("?? AIOT Level 1 ?刻?隡箸???(Hosting on 0.0.0.0:5000)...")
    app.run(host='0.0.0.0', port=5000, debug=False)

