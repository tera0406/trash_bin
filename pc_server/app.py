"""
AIOT 智慧垃圾桶 - PC 運算層 Inference Server
架構: 交叉融合 (Cross-Fusion) + Gemini 雲端備援 + 生產資料收集

推論流程:
  1. 接收 Pi 上傳的影像 + 音訊頻譜 (Form-Data)
  2. 雙輸入送入交叉融合 .keras 模型推論
  3. 若信心值 < CONFIDENCE_THRESHOLD → 啟動 Gemini 雲端備援 (CoT)
  4. 回傳最終分類結果 JSON
  5. [可選] 將影像、音訊頻譜及元資料儲存至 data/raw/ 供後續訓練

資料收集開關: .env 中設定 DATA_COLLECTION=true 即可啟用
"""

import os
import io
import json
import time
from datetime import datetime

import cv2
import numpy as np
from flask import Flask, request, jsonify
from PIL import Image
from dotenv import load_dotenv

from gemini_fallback import get_gemini_fallback

# ── 載入 .env ────────────────────────────────────────────────────────
load_dotenv()

# ── TensorFlow 延遲匯入，避免啟動時搶佔 GPU ──────────────────────────
import tensorflow as tf

# ── Flask ────────────────────────────────────────────────────────────
app = Flask(__name__)

# ── 全域設定 ─────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, "models", "best_multimodal_model.keras")
CLASSES = ["general", "plastic", "paper", "metal"]
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.50"))
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash")

# ── 資料收集設定 ───────────────────────────────────────────────────────
# 在 .env 中設定 DATA_COLLECTION=true 以啟用
DATA_COLLECTION = os.getenv("DATA_COLLECTION", "false").lower() == "true"
DATA_RAW_DIR = os.path.join(BASE_DIR, "data", "raw")

# ── 載入交叉融合模型 ─────────────────────────────────────────────────
print("[System] 正在載入交叉融合模型...")
model = tf.keras.models.load_model(MODEL_PATH)
num_inputs = len(model.inputs)
print(f"[System] 模型載入成功，偵測到 {num_inputs} 個輸入端")
if num_inputs < 2:
    print("[System] 警告：模型為單輸入，音訊將被忽略。請確認是否載入正確的交叉融合模型！")

# ── 初始化 Gemini 備援機制 ────────────────────────────────────────────
print("[System] 正在初始化 Gemini 備援機制...")
gemini = get_gemini_fallback(
    confidence_threshold=CONFIDENCE_THRESHOLD,
    model_name=GEMINI_MODEL_NAME,
)
print("[System] 伺服器準備就緒，監聽於 0.0.0.0:5000")


# ── 工具函式 ─────────────────────────────────────────────────────────

def preprocess_bytes(image_bytes: bytes) -> np.ndarray:
    """
    將二進位影像/頻譜 bytes 解碼並轉為模型輸入張量。
    輸出形狀: (1, 224, 224, 3), float32, 值域 [0, 1]
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("影像解碼失敗，請確認上傳的檔案格式。")
    img = cv2.resize(img, (224, 224))
    return np.expand_dims(img.astype("float32") / 255.0, axis=0)


def save_sample(
    img_bytes: bytes,
    aud_bytes: bytes,
    label: str,
    confidence: float,
    is_gemini: bool,
    has_audio: bool,
) -> None:
    """
    將本次推論的原始資料儲存至 data/raw/{label}/ 供後續訓練。

    檔案結構:
        data/raw/{label}/
            {timestamp}_img.jpg          ← 原始影像
            {timestamp}_aud.bin          ← 音訊頻譜 (有提供時)
            {timestamp}_meta.json        ← 元資料

    元資料欄位:
        label       : 最終分類標籤
        confidence  : 信心值
        is_gemini   : 是否由 Gemini 備援修正
        has_audio   : 是否有真實音訊頻譜
        timestamp   : ISO 8601 時間戳記

    說明:
        - is_gemini=True 的樣本標籤品質較高，適合優先用於訓練。
        - has_audio=False 代表音訊欄位以影像替代，訓練時應注意。
    """
    try:
        label_dir = os.path.join(DATA_RAW_DIR, label)
        os.makedirs(label_dir, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        # 影像
        img_path = os.path.join(label_dir, f"{ts}_img.jpg")
        with open(img_path, "wb") as f:
            f.write(img_bytes)

        # 音訊頻譜 (只在有真實音訊時儲存)
        if has_audio:
            aud_path = os.path.join(label_dir, f"{ts}_aud.bin")
            with open(aud_path, "wb") as f:
                f.write(aud_bytes)

        # 元資料
        meta = {
            "label": label,
            "confidence": round(confidence, 4),
            "is_gemini": is_gemini,
            "has_audio": has_audio,
            "timestamp": datetime.now().isoformat(),
        }
        meta_path = os.path.join(label_dir, f"{ts}_meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        print(f"[DataCollection] 已儲存樣本 → {label_dir}/{ts}_*")

    except Exception as e:
        # 儲存失敗不影響正常推論回應
        print(f"[DataCollection] 儲存失敗 (不影響推論): {e}")


# ── 推論端點 ─────────────────────────────────────────────────────────

@app.route("/predict", methods=["POST"])
def predict():
    """
    POST /predict  (multipart/form-data)

    Fields:
        image      : 影像二進位檔案 (必填)
        audio_spec : 音訊頻譜二進位檔案 (選填；缺少時以影像替代)

    Response JSON:
        {
          "label"      : "paper",
          "confidence" : 0.95,
          "is_gemini"  : false,
          "reasoning"  : "Local cross-fusion inference sufficient.",
          "latency_ms" : 42.5,
          "status"     : "success"
        }
    """
    start = time.time()

    try:
        # ── 1. 接收資料 ───────────────────────────────────────────────
        if "image" not in request.files:
            return jsonify({"status": "error", "message": "缺少 image 欄位"}), 400

        file_img = request.files["image"].read()

        # audio_spec 選填；若未提供則以影像資料替代（維持雙輸入介面）
        has_audio = "audio_spec" in request.files
        if has_audio:
            file_aud = request.files["audio_spec"].read()
        else:
            print("[Predict] 未收到 audio_spec，以影像替代音訊輸入")
            file_aud = file_img

        # ── 2. 前處理 ─────────────────────────────────────────────────
        img_batch = preprocess_bytes(file_img)
        aud_batch = preprocess_bytes(file_aud)

        # ── 3. 交叉融合推論 ───────────────────────────────────────────
        if num_inputs >= 2:
            preds = model.predict([img_batch, aud_batch], verbose=0)
        else:
            preds = model.predict(img_batch, verbose=0)

        res_idx = int(np.argmax(preds[0]))
        confidence = float(preds[0][res_idx])
        label = CLASSES[res_idx] if res_idx < len(CLASSES) else f"unknown({res_idx})"

        print(f"[CrossFusion] label={label}, confidence={confidence:.3f}")

        # ── 4. 決策: 是否啟動 Gemini 備援 ────────────────────────────
        is_gemini = False
        reasoning = "Local cross-fusion inference sufficient."

        if gemini.should_fallback(confidence):
            print(
                f"[Decision] 信心值 {confidence:.3f} < 閾值 {CONFIDENCE_THRESHOLD}，"
                "啟動 Gemini 備援..."
            )
            # 將原始影像 bytes 轉為 PIL Image 供 Gemini 使用
            pil_img = Image.open(io.BytesIO(file_img)).convert("RGB")

            gemini_result = gemini.classify(
                image_input=pil_img,
                local_label=label,
                local_confidence=confidence,
            )

            # 無論 Gemini 成功或降級，都更新最終結果
            label = gemini_result["label"]
            confidence = gemini_result["confidence"]
            reasoning = gemini_result.get("reasoning", "")
            is_gemini = gemini_result.get("is_gemini", False)

        # ── 5. [可選] 儲存資料 ────────────────────────────────────────
        if DATA_COLLECTION:
            save_sample(
                img_bytes=file_img,
                aud_bytes=file_aud,
                label=label,
                confidence=confidence,
                is_gemini=is_gemini,
                has_audio=has_audio,
            )

        # ── 6. 回傳結果 ───────────────────────────────────────────────
        latency_ms = round((time.time() - start) * 1000, 1)
        print(f"[Done] label={label}, confidence={confidence:.3f}, "
              f"is_gemini={is_gemini}, latency={latency_ms}ms")

        return jsonify({
            "label": label,
            "confidence": round(confidence, 4),
            "is_gemini": is_gemini,
            "reasoning": reasoning,
            "latency_ms": latency_ms,
            "status": "success",
        })

    except Exception as e:
        latency_ms = round((time.time() - start) * 1000, 1)
        print(f"[Server Error] {e}")
        return jsonify({
            "status": "error",
            "message": str(e),
            "latency_ms": latency_ms,
        }), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)