"""
Main Server - PC 撅斗隢撩?
撠?閮??

?瑁痊:
- ?交靘 Raspberry Pi ??璅⊥?鞈? (敶勗? + ?唾?)
- ?瑁? EfficientNet 敶勗?颲刻??閮霅???- ?脰?憭芋???? Gemini ??斗
- ?? HTTP/JSON ???蝯?蝯?Pi

蝖祇??: ? PC 撅文銵?Pi 撅斤?甇Ｗ銵?AI ?刻?
"""

import os
import time
import base64
import io
from flask import Flask, request, jsonify
from flask_cors import CORS
from PIL import Image
import numpy as np
from dotenv import load_dotenv

# 頛 .env 瑼?銝剔??啣?霈
# 撠?閮?? 撖阡???蔭
load_dotenv()

# ?臬?刻?撘?璅∠?
from src.inference.vision_engine import get_vision_engine
from src.inference.audio_engine import get_audio_engine
from src.inference.fusion_logic import get_fusion_logic
from src.inference.gemini_fallback import get_gemini_fallback

app = Flask(__name__)
CORS(app)  # ?迂頝典?隢? (Pi ?航?其???IP)

# ==================== 撖阡???蔭 (?航矽?? ====================
# 撠?閮?訾葉???菔???

# 1. 憭芋??????
VISION_WEIGHT = float(os.getenv("VISION_WEIGHT", "0.6"))
AUDIO_WEIGHT = float(os.getenv("AUDIO_WEIGHT", "0.4"))

# 2. ??靽∪?摨阡??(Confidence Threshold T)
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.85"))

# 3. 璅∪?頝臬? (?舫嚗??None ?蝙?券?閮剜瑽?
VISION_MODEL_PATH = os.getenv("VISION_MODEL_PATH", None)
AUDIO_MODEL_PATH = os.getenv("AUDIO_MODEL_PATH", None)

# ==================== ???隢???====================

print("[Server] 甇????隢???..")

# ????撘? (?桐?璅∪?嚗??銴???
vision_engine = get_vision_engine(model_path=VISION_MODEL_PATH)
audio_engine = get_audio_engine(model_path=AUDIO_MODEL_PATH)
fusion_logic = get_fusion_logic(vision_weight=VISION_WEIGHT, audio_weight=AUDIO_WEIGHT)
gemini_fallback = get_gemini_fallback(confidence_threshold=CONFIDENCE_THRESHOLD)

print("[Server] ?刻?撘???????)

# ==================== API 蝡舫? ====================

@app.route('/predict', methods=['POST'])
def predict():
    """
    ?交靘 Raspberry Pi ??璅⊥?鞈?銝血??喳?憿???    
    撠?閮?訾葉?敹?蝞惜 (Server Layer)
    ???降: JSON
    
    隢??澆?:
    {
        "event_id": "event_001",
        "image": "base64_encoded_image_string" ??"image_path",
        "audio": "base64_encoded_audio_bytes" ??"audio_path",
        "timestamp": 1234567890.0
    }
    
    ???澆?:
    {
        "event_id": "event_001",
        "class": "Class A",
        "confidence": 0.95,
        "multimodal_status": true,
        "is_gemini": false,
        "vision_class": "Class A",
        "vision_confidence": 0.92,
        "audio_class": "Class A",
        "audio_confidence": 0.88,
        "reasoning": "...",
        "timestamp": 1234567890.0
    }
    """
    try:
        # 1. ??隢?鞈?
        data = request.json
        if not data:
            return jsonify({
                "error": "?∟?瘙???,
                "status": "error"
            }), 400
        
        event_id = data.get("event_id", f"event_{int(time.time())}")
        image_data = data.get("image")
        audio_data = data.get("audio")
        request_timestamp = data.get("timestamp", time.time())
        
        print(f"[Server] ?嗅鈭辣 {event_id} ?隢?瘙?..")
        
        # 2. 撽?頛詨鞈?
        if not image_data and not audio_data:
            return jsonify({
                "event_id": event_id,
                "error": "蝻箏?敶勗??閮???,
                "status": "error"
            }), 400
        
        # 3. ?瑁?敶勗??刻? (憒??蔣????
        vision_result = None
        if image_data:
            try:
                print(f"[Server] ?瑁?敶勗??刻?...")
                vision_result = vision_engine.predict(image_data)
                print(f"[Server] 敶勗??刻?摰?: {vision_result['class']} (靽∪??? {vision_result['confidence']:.2f})")
            except Exception as e:
                print(f"[Server] 敶勗??刻??航炊: {e}")
                vision_result = {
                    "class": "unknown",
                    "confidence": 0.0,
                    "all_probs": {},
                    "status": f"error: {str(e)}"
                }
        else:
            vision_result = {
                "class": "unknown",
                "confidence": 0.0,
                "all_probs": {},
                "status": "skipped: no_image"
            }
        
        # 4. ?瑁??唾??刻? (憒??閮???
        audio_result = None
        if audio_data:
            try:
                print(f"[Server] ?瑁??唾??刻?...")
                audio_result = audio_engine.predict(audio_data)
                print(f"[Server] ?唾??刻?摰?: {audio_result['class']} (靽∪??? {audio_result['confidence']:.2f})")
            except Exception as e:
                print(f"[Server] ?唾??刻??航炊: {e}")
                audio_result = {
                    "class": "unknown",
                    "confidence": 0.0,
                    "all_probs": {},
                    "status": f"error: {str(e)}"
                }
        else:
            audio_result = {
                "class": "unknown",
                "confidence": 0.0,
                "all_probs": {},
                "status": "skipped: no_audio"
            }
        
        # 5. 憭芋????
        print(f"[Server] ?瑁?憭芋????..")
        fusion_result = fusion_logic.fuse_predictions(vision_result, audio_result)
        print(f"[Server] ??摰?: {fusion_result['class']} (靽∪??? {fusion_result['confidence']:.2f})")
        
        # 6. ?斗?臬?閬?Gemini ?
        final_class = fusion_result["class"]
        final_confidence = fusion_result["confidence"]
        use_gemini = False
        gemini_reasoning = ""
        
        if gemini_fallback.should_use_gemini(final_confidence):
            print(f"[Server] ?砍靽∪???({final_confidence:.2f}) 雿?曉潘??? Gemini ?...")
            use_gemini = True
            
            # 皞?敶勗?頛詨 (?冽 Gemini)
            try:
                if image_data:
                    # 頧???PIL Image
                    if isinstance(image_data, str):
                        if image_data.startswith('data:image') or len(image_data) > 100:
                            # Base64
                            if ',' in image_data:
                                image_data = image_data.split(',')[1]
                            img_bytes = base64.b64decode(image_data)
                            gemini_image = Image.open(io.BytesIO(img_bytes))
                        else:
                            # 瑼?頝臬?
                            gemini_image = Image.open(image_data)
                    else:
                        gemini_image = Image.fromarray(np.array(image_data))
                    
                    # ?澆 Gemini API (?喲??砍?葫蝯??縑敹潘?靘?Gemini ??
                    gemini_result = gemini_fallback.classify_with_gemini(
                        image_input=gemini_image,
                        local_prediction=final_class,
                        local_confidence=final_confidence
                    )
                    
                    # 憒? Gemini ??嚗蝙?典蝯?
                    if gemini_result["status"] == "success":
                        final_class = gemini_result["class"]
                        final_confidence = gemini_result["confidence"]
                        gemini_reasoning = gemini_result["reasoning"]
                        print(f"[Server] Gemini ?摰?: {final_class} (靽∪??? {final_confidence:.2f})")
                    else:
                        gemini_reasoning = gemini_result["reasoning"]
                        print(f"[Server] Gemini ?憭望?: {gemini_reasoning}")
                else:
                    gemini_reasoning = "?∪蔣?????⊥?雿輻 Gemini Vision"
                    print(f"[Server] {gemini_reasoning}")
            except Exception as e:
                gemini_reasoning = f"Gemini API ?航炊: {str(e)}"
                print(f"[Server] {gemini_reasoning}")
        
        # 7. 撠??蝯?
        # 撠?閮?訾葉??JSON ?澆?
        response = {
            "event_id": event_id,
            "class": final_class,
            "confidence": round(final_confidence, 3),
            "multimodal_status": fusion_result.get("multimodal_status", False),
            "is_gemini": use_gemini,
            "vision_class": fusion_result.get("vision_class", "unknown"),
            "vision_confidence": round(fusion_result.get("vision_confidence", 0.0), 3),
            "audio_class": fusion_result.get("audio_class", "unknown"),
            "audio_confidence": round(fusion_result.get("audio_confidence", 0.0), 3),
            "reasoning": gemini_reasoning if use_gemini else "?砍璅∪??刻???",
            "timestamp": time.time()
        }
        
        print(f"[Server] ?蝯?: {final_class} (靽∪??? {final_confidence:.2f})")
        return jsonify(response)
        
    except Exception as e:
        # ?航炊??
        print(f"[Server] 隡箸??券隤? {e}")
        return jsonify({
            "error": str(e),
            "status": "error"
        }), 500


@app.route('/health', methods=['GET'])
def health():
    """
    ?亙熒瑼Ｘ蝡舫? (?冽?????
    """
    return jsonify({
        "status": "healthy",
        "vision_model": vision_engine.get_model_info(),
        "audio_model": audio_engine.get_model_info(),
        "fusion_weights": {
            "vision": fusion_logic.vision_weight,
            "audio": fusion_logic.audio_weight
        },
        "confidence_threshold": gemini_fallback.get_threshold(),
        "gemini_configured": gemini_fallback.client is not None
    })


@app.route('/config', methods=['POST'])
def update_config():
    """
    ???湔撖阡?? (?冽撖阡?隤踵)
    
    隢??澆?:
    {
        "vision_weight": 0.7,
        "audio_weight": 0.3,
        "confidence_threshold": 0.9
    }
    """
    try:
        data = request.json
        if not data:
            return jsonify({"error": "?∟?瘙???}), 400
        
        # ?湔??甈?
        if "vision_weight" in data and "audio_weight" in data:
            fusion_logic.update_weights(
                data["vision_weight"],
                data["audio_weight"]
            )
        
        # ?湔靽∪?摨阡??        if "confidence_threshold" in data:
            gemini_fallback.update_threshold(data["confidence_threshold"])
        
        return jsonify({
            "status": "success",
            "message": "?蔭撌脫??,
            "current_weights": {
                "vision": fusion_logic.vision_weight,
                "audio": fusion_logic.audio_weight
            },
            "current_threshold": gemini_fallback.get_threshold()
        })
        
    except Exception as e:
        return jsonify({
            "error": str(e),
            "status": "error"
        }), 500


if __name__ == '__main__':
    # ??隡箸??剁??????IP ??5000 蝡臬
    # 隢Ⅱ靽?PC ??Raspberry Pi ?典?銝???雯頝?(LAN)
    print("[Server] ?? PC 撅斗隢撩?...")
    print(f"[Server] ???啣?: http://0.0.0.0:5000")
    print(f"[Server] ??甈? - Vision: {VISION_WEIGHT}, Audio: {AUDIO_WEIGHT}")
    print(f"[Server] 靽∪?摨阡?? {CONFIDENCE_THRESHOLD}")
    app.run(host='0.0.0.0', port=5000, debug=True)

