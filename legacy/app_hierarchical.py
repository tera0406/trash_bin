"""
AIOT 智慧垃圾桶 - PC 運算層 Inference Server
架構: 交叉融合 (Cross-Fusion) + Gemini 雲端備援

推論流程:
  1. 接收 Pi 上傳的影像 + 音訊頻譜 (Form-Data)
  2. 雙輸入送入交叉融合 .keras 模型推論
  3. 若信心值 < CONFIDENCE_THRESHOLD → 啟動 Gemini 雲端備援 (CoT)
  4. 回傳最終分類結果 JSON
"""

import os
import io
import json
import time
import sys
from datetime import datetime

# 強制 sys.stdout 與 sys.stderr 採用 UTF-8 編碼，避免 Windows 終端機 (cp950) 列印 Emoji 崩潰
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

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
MODEL_PATH = os.getenv("MODEL_PATH", os.path.join(BASE_DIR, "models", "best_hierarchical_model.keras"))
if not os.path.isabs(MODEL_PATH):
    MODEL_PATH = os.path.join(BASE_DIR, MODEL_PATH)

CLASSES_ENV = os.getenv("CLASSES")
if CLASSES_ENV:
    CLASSES = [c.strip() for c in CLASSES_ENV.split(",")]
else:
    CLASSES = ["general", "plastic", "paper", "metal"]

CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.85"))
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash")

# 1. 神經網路實際輸出的 10 個細項分類
CLASSES_10 = [
    'battery', 'biological', 'cardboard', 'clothes', 'glass', 
    'metal', 'paper', 'plastic', 'shoes', 'trash'
]

# 2. 我們新訓練的 4 大類分類
CLASSES_4 = ['general', 'metal', 'paper', 'plastic']

# 3. 將 10 種細項強制對應到 4 個實體桶子的規則字典
CATEGORY_MAPPING = {
    'battery': 'metal',
    'biological': 'general',
    'cardboard': 'paper',
    'clothes': 'general',
    'glass': 'general',
    'metal': 'metal',
    'paper': 'paper',
    'plastic': 'plastic',
    'shoes': 'general',
    'trash': 'general'
}

# ── 載入交叉融合模型 ─────────────────────────────────────────────────
print("[System] 正在載入交叉融合模型...")
model = tf.keras.models.load_model(MODEL_PATH, compile=False)
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
print(f"[System] 系統準備就緒！本地推論模型: {os.path.basename(MODEL_PATH)} | 雲端備援模型: {GEMINI_MODEL_NAME}")
print(f"[System] 信心值備援門檻設定為: {CONFIDENCE_THRESHOLD*100:.1f}%")
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



@app.route("/health", methods=["GET"])
def health():
    """
    健康診斷端點，供客戶端檢查連線狀態。
    """
    return jsonify({"status": "healthy"}), 200


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
        specific_label = None
        specific_confidence = None
        top2_label = None
        top2_confidence = None

        # ── 1. 接收資料 ───────────────────────────────────────────────
        if "image" not in request.files:
            return jsonify({"status": "error", "message": "缺少 image 欄位"}), 400

        file_img = request.files["image"].read()
        print(f"\n[Predict] 收到影像請求，大小 = {len(file_img)} bytes")

        # audio_spec 選填；若未提供則以影像資料替代（維持雙輸入介面）
        has_audio = "audio_spec" in request.files
        if has_audio:
            file_aud = request.files["audio_spec"].read()
            print(f"[Predict] 收到音訊頻譜，大小 = {len(file_aud)} bytes")
        else:
            print("[Predict] 未收到 audio_spec，以影像替代音訊輸入")
            file_aud = file_img

        # ── 2. 前處理 ─────────────────────────────────────────────────
        print("[Predict] 正在進行前處理...")
        img_batch = preprocess_bytes(file_img)
        aud_batch = preprocess_bytes(file_aud)
        print("[Predict] 前處理完成，準備進行推論...")

        # ── 3. 交叉融合推論 ───────────────────────────────────────────
        print("[Predict] 正在進行交叉融合模型推論...")
        if num_inputs >= 2:
            preds = model.predict([img_batch, aud_batch], verbose=0)
        else:
            preds = model.predict(img_batch, verbose=0)
        print("[Predict] 推論完成，開始解析預測輸出...")

        # 支援多輸出模型 (例如: best_hierarchical_model.keras 有 10-class 與 4-class 雙輸出)
        is_hierarchical = False
        if isinstance(preds, (list, tuple)) and len(preds) == 2:
            if preds[0].shape[-1] == 10 and preds[1].shape[-1] == 4:
                is_hierarchical = True

        if is_hierarchical:
            pred_10 = preds[0][0] # 10 類的預測機率陣列
            pred_4 = preds[1][0]  # 4 類的預測機率陣列
            
            # ---------------- 處理 4 大類結果 (硬體致動用) ----------------
            bin_idx = np.argmax(pred_4)
            final_bin = CLASSES_4[bin_idx]
            bin_confidence = float(pred_4[bin_idx])
            
            # ---------------- 處理 10 細項結果 (雲端參考用) ----------------
            specific_idx = np.argmax(pred_10)
            specific_class = CLASSES_10[specific_idx]
            specific_confidence = float(pred_10[specific_idx])
            mapped_bin = CATEGORY_MAPPING.get(specific_class, 'unknown')
            
            # 取出第二可能的細項分類 (Top-2)
            top2_indices = np.argsort(pred_10)[-2:][::-1]
            top2_class = CLASSES_10[top2_indices[1]]
            top2_conf = float(pred_10[top2_indices[1]])
            
            # 設定初始本地預測結果（後續可能被 Gemini 覆寫）
            label = final_bin
            confidence = bin_confidence
            
            # 用於上傳給 Gemini 的參考標籤
            gemini_local_label = specific_class
            gemini_local_confidence = specific_confidence

            # 用於 JSON 輸出的細項結果
            specific_label = specific_class
            specific_confidence = round(specific_confidence, 4)
            top2_label = top2_class
            top2_confidence = round(top2_conf, 4)

            # ==========================================
            # 輸出決策面板到 PC 主機終端機
            # ==========================================
            print("\n" + "="*40)
            print("🤖 系統辨識結果報告 (Hierarchical Mode)")
            print("="*40)
            print(f"📦 [硬體指令] 目標垃圾桶: {final_bin.upper()} (信心度: {bin_confidence*100:.1f}%)")
            print("-" * 40)
            print("🔍 [認知細節] 視覺細項判斷:")
            print(f"   - Top 1: {specific_class} (信心度: {specific_confidence*100:.1f}%, 映射分類: {mapped_bin})")
            print(f"   - Top 2: {top2_class} (信心度: {top2_conf*100:.1f}%)")
            print("-" * 40)
            if bin_confidence < CONFIDENCE_THRESHOLD:
                print("☁️ [備援觸發] 信心度過低，暫停硬體動作。")
                print(f"   準備將 Top-1 ({specific_class}) 與影像上傳至 Gemini API 進行二次判斷...")
            else:
                print("✅ [動作執行] 信心度達標，傳送 UART 指令至 ESP32。")
            print("="*40 + "\n")

        else:
            # ── 單輸出或降級相容模式 ─────────────────────────────────
            final_preds = None
            if isinstance(preds, (list, tuple)):
                for p in preds:
                    if p.shape[-1] == 4:
                        final_preds = p
                        break
                if final_preds is None:
                    final_preds = preds[-1]
            else:
                final_preds = preds

            # 確保為 1D 陣列以安全進行 indexing
            final_preds_1d = np.squeeze(final_preds)
            if final_preds_1d.ndim == 0:
                final_preds_1d = np.array([final_preds_1d])

            res_idx = int(np.argmax(final_preds_1d))
            confidence = float(final_preds_1d[res_idx])
            label = CLASSES[res_idx] if res_idx < len(CLASSES) else f"unknown({res_idx})"
            
            gemini_local_label = label
            gemini_local_confidence = confidence
            print(f"[CrossFusion Compatibility] label={label}, confidence={confidence:.3f}")

        # ── 4. 決策: 是否啟動 Gemini 備援 ────────────────────────────
        is_gemini = False
        reasoning = "Local cross-fusion inference sufficient."
        model_used = os.path.basename(MODEL_PATH)

        if gemini.should_fallback(confidence):
            print(
                f"[Decision] 信心值 {confidence:.3f} < 閾值 {CONFIDENCE_THRESHOLD}，"
                "啟動 Gemini 備援..."
            )
            # 將原始影像 bytes 轉為 PIL Image 供 Gemini 使用
            pil_img = Image.open(io.BytesIO(file_img)).convert("RGB")

            gemini_result = gemini.classify(
                image_input=pil_img,
                local_label=gemini_local_label,
                local_confidence=gemini_local_confidence,
            )

            # 無論 Gemini 成功或降級，都更新最終結果
            label = gemini_result["label"]
            confidence = gemini_result["confidence"]
            reasoning = gemini_result.get("reasoning", "")
            is_gemini = gemini_result.get("is_gemini", False)
            if is_gemini:
                model_used = gemini_result.get("model_used", GEMINI_MODEL_NAME)
            else:
                # 降級至本地，在雙輸出模式下，必須是 final_bin (4類結果) 確保舵機正常動作
                if is_hierarchical:
                    label = final_bin
                    confidence = bin_confidence
                model_used = f"{os.path.basename(MODEL_PATH)} (Local Fallback)"



        # ── 6. 回傳結果 ───────────────────────────────────────────────
        latency_ms = round((time.time() - start) * 1000, 1)
        print(f"[Done] label={label}, confidence={confidence:.3f}, "
              f"is_gemini={is_gemini}, model_used={model_used}, latency={latency_ms}ms")

        return jsonify({
            "label": label,
            "confidence": round(confidence, 4),
            "is_gemini": is_gemini,
            "reasoning": reasoning,
            "latency_ms": latency_ms,
            "model_used": model_used,
            "specific_label": specific_label,
            "specific_confidence": specific_confidence,
            "top2_label": top2_label,
            "top2_confidence": top2_confidence,
            "status": "success",
        })

    except Exception as e:
        import traceback
        latency_ms = round((time.time() - start) * 1000, 1)
        print(f"[Server Error] {e}")
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "message": str(e),
            "latency_ms": latency_ms,
        }), 500


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    app.run(host=host, port=port, debug=False)
