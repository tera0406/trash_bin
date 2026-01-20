"""
Main Server - PC 層推論伺服器
對應計畫書: [cite: 187, 197, 199]

職責:
- 接收來自 Raspberry Pi 的多模態資料 (影像 + 音訊)
- 執行 EfficientNet 影像辨識與音訊頻譜分析
- 進行多模態融合與 Gemini 備援判斷
- 透過 HTTP/JSON 回傳分類結果給 Pi

硬體限制: 僅在 PC 層執行，Pi 層禁止執行 AI 推論
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

# 載入 .env 檔案中的環境變數
# 對應計畫書: 實驗參數配置 [cite: 178, 204, 246, 251]
load_dotenv()

# 匯入推論引擎模組
from src.inference.vision_engine import get_vision_engine
from src.inference.audio_engine import get_audio_engine
from src.inference.fusion_logic import get_fusion_logic
from src.inference.gemini_fallback import get_gemini_fallback

app = Flask(__name__)
CORS(app)  # 允許跨域請求 (Pi 可能在不同 IP)

# ==================== 實驗參數配置 (可調整) ====================
# 對應計畫書中的關鍵變因 [cite: 178, 204, 246, 251]

# 1. 多模態融合權重 [cite: 178, 246]
VISION_WEIGHT = float(os.getenv("VISION_WEIGHT", "0.6"))
AUDIO_WEIGHT = float(os.getenv("AUDIO_WEIGHT", "0.4"))

# 2. 動態信心度閾值 (Confidence Threshold T) [cite: 204, 251]
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.85"))

# 3. 模型路徑 (可選，若為 None 則使用預設架構)
VISION_MODEL_PATH = os.getenv("VISION_MODEL_PATH", None)
AUDIO_MODEL_PATH = os.getenv("AUDIO_MODEL_PATH", None)

# ==================== 初始化推論引擎 ====================

print("[Server] 正在初始化推論引擎...")

# 初始化各引擎 (單例模式，避免重複載入)
vision_engine = get_vision_engine(model_path=VISION_MODEL_PATH)
audio_engine = get_audio_engine(model_path=AUDIO_MODEL_PATH)
fusion_logic = get_fusion_logic(vision_weight=VISION_WEIGHT, audio_weight=AUDIO_WEIGHT)
gemini_fallback = get_gemini_fallback(confidence_threshold=CONFIDENCE_THRESHOLD)

print("[Server] 推論引擎初始化完成")

# ==================== API 端點 ====================

@app.route('/predict', methods=['POST'])
def predict():
    """
    接收來自 Raspberry Pi 的多模態資料並回傳分類結果
    
    對應計畫書中的核心運算層 (Server Layer) [cite: 187]
    通訊協議: JSON [cite: 197]
    
    請求格式:
    {
        "event_id": "event_001",
        "image": "base64_encoded_image_string" 或 "image_path",
        "audio": "base64_encoded_audio_bytes" 或 "audio_path",
        "timestamp": 1234567890.0
    }
    
    回應格式:
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
        # 1. 取得請求資料
        data = request.json
        if not data:
            return jsonify({
                "error": "無請求資料",
                "status": "error"
            }), 400
        
        event_id = data.get("event_id", f"event_{int(time.time())}")
        image_data = data.get("image")
        audio_data = data.get("audio")
        request_timestamp = data.get("timestamp", time.time())
        
        print(f"[Server] 收到事件 {event_id} 的推論請求...")
        
        # 2. 驗證輸入資料
        if not image_data and not audio_data:
            return jsonify({
                "event_id": event_id,
                "error": "缺少影像或音訊資料",
                "status": "error"
            }), 400
        
        # 3. 執行影像推論 (如果有影像資料)
        vision_result = None
        if image_data:
            try:
                print(f"[Server] 執行影像推論...")
                vision_result = vision_engine.predict(image_data)
                print(f"[Server] 影像推論完成: {vision_result['class']} (信心值: {vision_result['confidence']:.2f})")
            except Exception as e:
                print(f"[Server] 影像推論錯誤: {e}")
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
        
        # 4. 執行音訊推論 (如果有音訊資料)
        audio_result = None
        if audio_data:
            try:
                print(f"[Server] 執行音訊推論...")
                audio_result = audio_engine.predict(audio_data)
                print(f"[Server] 音訊推論完成: {audio_result['class']} (信心值: {audio_result['confidence']:.2f})")
            except Exception as e:
                print(f"[Server] 音訊推論錯誤: {e}")
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
        
        # 5. 多模態融合 [cite: 178, 246]
        print(f"[Server] 執行多模態融合...")
        fusion_result = fusion_logic.fuse_predictions(vision_result, audio_result)
        print(f"[Server] 融合完成: {fusion_result['class']} (信心值: {fusion_result['confidence']:.2f})")
        
        # 6. 判斷是否需要 Gemini 備援 [cite: 51, 130, 209]
        final_class = fusion_result["class"]
        final_confidence = fusion_result["confidence"]
        use_gemini = False
        gemini_reasoning = ""
        
        if gemini_fallback.should_use_gemini(final_confidence):
            print(f"[Server] 本地信心值 ({final_confidence:.2f}) 低於閾值，啟動 Gemini 備援...")
            use_gemini = True
            
            # 準備影像輸入 (用於 Gemini)
            try:
                if image_data:
                    # 轉換為 PIL Image
                    if isinstance(image_data, str):
                        if image_data.startswith('data:image') or len(image_data) > 100:
                            # Base64
                            if ',' in image_data:
                                image_data = image_data.split(',')[1]
                            img_bytes = base64.b64decode(image_data)
                            gemini_image = Image.open(io.BytesIO(img_bytes))
                        else:
                            # 檔案路徑
                            gemini_image = Image.open(image_data)
                    else:
                        gemini_image = Image.fromarray(np.array(image_data))
                    
                    # 呼叫 Gemini API (傳遞本地預測結果與信心值，供 Gemini 參考)
                    gemini_result = gemini_fallback.classify_with_gemini(
                        image_input=gemini_image,
                        local_prediction=final_class,
                        local_confidence=final_confidence
                    )
                    
                    # 如果 Gemini 成功，使用其結果
                    if gemini_result["status"] == "success":
                        final_class = gemini_result["class"]
                        final_confidence = gemini_result["confidence"]
                        gemini_reasoning = gemini_result["reasoning"]
                        print(f"[Server] Gemini 備援完成: {final_class} (信心值: {final_confidence:.2f})")
                    else:
                        gemini_reasoning = gemini_result["reasoning"]
                        print(f"[Server] Gemini 備援失敗: {gemini_reasoning}")
                else:
                    gemini_reasoning = "無影像資料，無法使用 Gemini Vision"
                    print(f"[Server] {gemini_reasoning}")
            except Exception as e:
                gemini_reasoning = f"Gemini API 錯誤: {str(e)}"
                print(f"[Server] {gemini_reasoning}")
        
        # 7. 封裝回傳結果
        # 對應計畫書中的 JSON 格式 [cite: 163, 200, 236]
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
            "reasoning": gemini_reasoning if use_gemini else "本地模型推論成功",
            "timestamp": time.time()
        }
        
        print(f"[Server] 回傳結果: {final_class} (信心值: {final_confidence:.2f})")
        return jsonify(response)
        
    except Exception as e:
        # 錯誤處理 [cite: 47, 91]
        print(f"[Server] 伺服器錯誤: {e}")
        return jsonify({
            "error": str(e),
            "status": "error"
        }), 500


@app.route('/health', methods=['GET'])
def health():
    """
    健康檢查端點 (用於監控與除錯)
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
    動態更新實驗參數 (用於實驗調整)
    
    請求格式:
    {
        "vision_weight": 0.7,
        "audio_weight": 0.3,
        "confidence_threshold": 0.9
    }
    """
    try:
        data = request.json
        if not data:
            return jsonify({"error": "無請求資料"}), 400
        
        # 更新融合權重
        if "vision_weight" in data and "audio_weight" in data:
            fusion_logic.update_weights(
                data["vision_weight"],
                data["audio_weight"]
            )
        
        # 更新信心度閾值
        if "confidence_threshold" in data:
            gemini_fallback.update_threshold(data["confidence_threshold"])
        
        return jsonify({
            "status": "success",
            "message": "配置已更新",
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
    # 啟動伺服器，監聽所有 IP 的 5000 端口
    # 請確保 PC 與 Raspberry Pi 在同一個區域網路 (LAN) [cite: 197]
    print("[Server] 啟動 PC 層推論伺服器...")
    print(f"[Server] 監聽地址: http://0.0.0.0:5000")
    print(f"[Server] 融合權重 - Vision: {VISION_WEIGHT}, Audio: {AUDIO_WEIGHT}")
    print(f"[Server] 信心度閾值: {CONFIDENCE_THRESHOLD}")
    app.run(host='0.0.0.0', port=5000, debug=True)
