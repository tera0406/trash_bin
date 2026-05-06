"""
Main Server - PC 層推論伺服器
對應計畫書: [cite: 187, 197, 199]

職責:
- 接收來自 Raspberry Pi 的多模態資料 (影像 + 音訊)
- 執行 EfficientNet 影像辨識與音訊頻譜分析
- 進行多模態融合與 Gemini 備援判斷
- 透過 HTTP/JSON 回傳分類結果給 Pi

硬體限制: 僅在 PC 層執行，Pi 層禁止執行 AI 推論
技術棧: Python, TensorFlow/Keras, Flask/FastAPI
"""

import os
import sys
from pathlib import Path

# 將專案根目錄加入 Python 路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 匯入現有的推論引擎 (從 src/inference/)
from src.inference.vision_engine import get_vision_engine
from src.inference.audio_engine import get_audio_engine
from src.inference.fusion_logic import get_fusion_logic
from src.inference.gemini_fallback import get_gemini_fallback

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

app = Flask(__name__)
CORS(app)

# 實驗參數配置
VISION_WEIGHT = float(os.getenv("VISION_WEIGHT", "0.6"))
AUDIO_WEIGHT = float(os.getenv("AUDIO_WEIGHT", "0.4"))
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.85"))
VISION_MODEL_PATH = os.getenv("VISION_MODEL_PATH", None)
AUDIO_MODEL_PATH = os.getenv("AUDIO_MODEL_PATH", None)

# 初始化推論引擎
print("[PC Inference] 正在初始化推論引擎...")
vision_engine = get_vision_engine(model_path=VISION_MODEL_PATH)
audio_engine = get_audio_engine(model_path=AUDIO_MODEL_PATH)
fusion_logic = get_fusion_logic(vision_weight=VISION_WEIGHT, audio_weight=AUDIO_WEIGHT)
gemini_fallback = get_gemini_fallback(confidence_threshold=CONFIDENCE_THRESHOLD)
print("[PC Inference] 推論引擎初始化完成")

@app.route('/predict', methods=['POST'])
def predict():
    """
    接收來自 Raspberry Pi 的多模態資料並回傳分類結果
    對應計畫書: [cite: 187, 197]
    """
    # 此處應整合 src/main_server.py 的邏輯
    # 為簡化架構，實際實作請參考 src/main_server.py
    return jsonify({"message": "請參考 src/main_server.py 的完整實作"})

@app.route('/health', methods=['GET'])
def health():
    """健康檢查端點"""
    return jsonify({
        "status": "healthy",
        "layer": "pc_inference",
        "vision_model": vision_engine.get_model_info(),
        "audio_model": audio_engine.get_model_info()
    })

if __name__ == '__main__':
    print("[PC Inference] 啟動伺服器...")
    app.run(host='0.0.0.0', port=5000, debug=True)
