"""
AIOT 智慧垃圾桶 - Level 1 PC 運算層 (Inference Server)
對應專題計畫書章節: 1111 (PC 運算層架構)

本程式負責接收來自 Level 2 (Raspberry Pi) 的影像與音訊資料，
執行多模態 AI 推論，並在本地信心值不足時調用 Gemini API 進行輔助判斷。

系統架構:
1. 輸入: 影像 (Base64) + 音訊 (Base64) [cite: 2]
2. 視覺模型: EfficientNet (Keras) [cite: 3333]
3. 聽覺模型: MFCC + CNN [cite: 4]
4. 決策邏輯: 多模態融合 (Hybrid Decision Gate) [cite: 5]
5. 雲端備援: Google Gemini 1.5 Pro (CoT 思維鏈) [cite: 777777777]

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

# 載入環境變數 (API Key, 模型路徑等)
load_dotenv()

# 匯入專案既有的 AI 推論模組 (OOP 封裝)
from src.inference.vision_engine import get_vision_engine
from src.inference.audio_engine import get_audio_engine
from src.inference.fusion_logic import get_fusion_logic
from src.inference.gemini_fallback import get_gemini_fallback

# ===== 初始化 Flask 應用程式 =====
app = Flask(__name__)
CORS(app)  # 允許跨域請求，方便 Pi 與 PC 連線

# ===== 全域設定與實驗參數 (對應計畫書變因) =====
# 動態信心閾值 theta [cite: 6666]
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD"))
# 融合權重 (影像優先) [cite: 5]
VISION_WEIGHT = float(os.getenv("VISION_WEIGHT"))
AUDIO_WEIGHT = float(os.getenv("AUDIO_WEIGHT"))

# ===== 初始化推論引擎 (單例模式) =====
print("[System] 正在載入 AI 模型...")
# 3333: 載入 EfficientNet 視覺模型
vision_model_path = os.getenv("VISION_MODEL_PATH")
vision_engine = get_vision_engine(model_path=vision_model_path)
# 4: 載入 CNN 聽覺模型
audio_model_path = os.getenv("AUDIO_MODEL_PATH") 
audio_engine = get_audio_engine(model_path=audio_model_path)
# 5: 初始化融合邏輯
fusion_logic = get_fusion_logic(vision_weight=VISION_WEIGHT, audio_weight=AUDIO_WEIGHT)
# 777777777: 初始化 Gemini 備援機制 (設定閾值)
gemini_model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-flash-latest")
gemini_fallback = get_gemini_fallback(
    confidence_threshold=CONFIDENCE_THRESHOLD,
    model_name=gemini_model_name
)
print("[System] AI 模型載入完成，伺服器準備就緒。")


@app.route('/predict', methods=['POST'])
def predict():
    """
    主要推論接口 (Endpoint)
    
    功能:
    1. 接收 Raspberry Pi 上傳的 JSON 資料 (包含影像與音訊)
    2. 執行本地多模態推論 (Vision + Audio)
    3. 檢查信心值，若低於閾值則觸發 Gemini 備援
    4. 回傳最終分類結果 (JSON) [cite: 8888]
    """
    try:
        # 1. 解析請求資料
        data = request.json
        if not data:
            return jsonify({"error": "No data provided", "class": "error", "confidence": 0.0}), 400

        image_b64 = data.get("image")
        audio_b64 = data.get("audio")
        
        # 記錄處理開始時間 (用於計算延遲 [cite: 10])
        start_time = time.time()
        print(f"[Request] 收到推論請求，開始處理...")

        # 2. 視覺推論 (EfficientNet) [cite: 3333]
        vision_result = {"status": "skipped", "confidence": 0.0, "all_probs": {}}
        gemini_image = None
        
        if image_b64:
            try:
                # 解碼 Base64 影像
                img_bytes = base64.b64decode(image_b64)
                gemini_image = Image.open(io.BytesIO(img_bytes)) # 保存供 Gemini 使用
                
                # 執行推論
                # VisionEngine 內部已實作預處理與 EfficientNet 推論
                vision_result = vision_engine.predict(gemini_image)
                print(f"[Vision] 類別: {vision_result.get('class')}, 信心值: {vision_result.get('confidence'):.3f}")
            except Exception as e:
                print(f"[Vision Error] {e}")

        # 3. 聽覺推論 (MFCC + CNN) [cite: 4]
        audio_result = {"status": "skipped", "confidence": 0.0, "all_probs": {}}
        if audio_b64:
            try:
                # 解碼 Base64 音訊
                audio_bytes = base64.b64decode(audio_b64)
                
                # 執行推論 (Transform to MFCC -> CNN)
                audio_result = audio_engine.predict(audio_bytes)
                print(f"[Audio] 類別: {audio_result.get('class')}, 信心值: {audio_result.get('confidence'):.3f}")
            except Exception as e:
                print(f"[Audio Error] {e}")

        # 4. 多模態融合 (Hybrid Decision Gate) [cite: 5]
        # 使用聲音模型信心值作為權重修正視覺輸出
        fusion_result = fusion_logic.fuse_predictions(vision_result, audio_result)
        
        final_class = fusion_result["class"]
        final_confidence = fusion_result["confidence"]
        
        print(f"[Fusion] 融合結果: {final_class}, 信心值: {final_confidence:.3f}")

        # 5. 決策邏輯: 判斷是否需要 Gemini 備援 [cite: 6666]
        # 若本地信心值 < theta (0.8)，則調用 Gemini
        is_gemini_used = False
        reasoning = "Local inference sufficient."
        
        if gemini_fallback.should_use_gemini(final_confidence):
            print(f"[Decision] 信心值 ({final_confidence:.3f}) < 閾值 ({CONFIDENCE_THRESHOLD})，準備啟動 Gemini 備援...")
            
            if gemini_image:
                print(f"[Gemini] 收到影像物件，開始呼叫雲端 API...")
                # 9999: 整合原本的「思維鏈 (CoT)」提示策略，要求 Gemini 先觀察材質與形狀
                gemini_response = gemini_fallback.classify_with_gemini(
                    image_input=gemini_image,
                    local_prediction=final_class,
                    local_confidence=final_confidence
                )
                
                # 檢查 Gemini 是否成功 (包含 fallback_parse)，若失敗則降級回本地結果
                if gemini_response.get("status", "").startswith("success"):
                    final_class = gemini_response.get("class", "unknown")
                    final_confidence = gemini_response.get("confidence", 0.0)
                    reasoning = gemini_response.get("reasoning", "")
                    is_gemini_used = True
                    print(f"[Gemini] 修正結果: {final_class}, 原因: {reasoning[:50]}...")
                else:
                    print(f"[Fallback] Gemini 呼叫失敗 ({gemini_response.get('status')})，降級使用本地推論結果")
                    reasoning = f"Gemini failed ({gemini_response.get('status')}), used local result."
                    is_gemini_used = False
            else:
                reasoning = "Low confidence but no image for Gemini."

        # 計算總延遲
        latency = (time.time() - start_time) * 1000
        print(f"[Done] 總耗時: {latency:.2f} ms")

        # 6. 建構回傳 JSON [cite: 8888]
        response_data = {
            "class": final_class,          # A/B/C/D (對應 Paper/Plastic/General/Metal)
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
    # 啟動伺服器
    # 確保綁定 0.0.0.0 以支援 Tailscale 連線
    print("啟動 AIOT Level 1 推論伺服器 (Hosting on 0.0.0.0:5000)...")
    app.run(host='0.0.0.0', port=5000, debug=False)
