# PC Inference Layer - 層級 1: AI 推論主機

## 硬體限制

- **硬體**: 高效能 PC / Laptop [cite: 248]
- **作業系統**: Windows / Linux / macOS
- **記憶體**: 建議 8GB 以上 (用於載入 TensorFlow 模型)
- **GPU**: 可選，但建議使用 (加速推論)

## 軟體職責

### 核心任務

1. **影像辨識** (EfficientNet)
   - 接收來自 Raspberry Pi 的影像資料
   - 使用 EfficientNet-B0 模型進行分類推論
   - 輸出: 類別名稱與信心值 [cite: 127, 200]

2. **音訊分析** (MFCC + CNN)
   - 接收來自 Raspberry Pi 的音訊片段
   - 提取 MFCC (Mel-Frequency Cepstral Coefficients) 特徵
   - 使用 CNN 模型進行分類推論
   - 輸出: 類別名稱與信心值 [cite: 243, 244, 246]

3. **多模態融合**
   - 整合影像與音訊的推論結果
   - 使用加權融合策略計算最終分類 [cite: 178, 246]
   - 提供可調整的權重參數 (實驗變因)

4. **Gemini 雲端備援**
   - 當本地模型信心值低於閾值時，啟動 Gemini Pro Vision API
   - 提供雲端 AI 的輔助判斷 [cite: 51, 130, 209]

### 通訊協議

- **接收**: HTTP POST `/predict` (JSON 格式)
- **傳送**: HTTP JSON 回應給 Raspberry Pi [cite: 197]
- **格式**: `{"class": "A", "confidence": 0.95, "multimodal_status": true}` [cite: 163, 200, 236]

## 技術棧

- **語言**: Python 3.8+
- **框架**: Flask / FastAPI
- **深度學習**: TensorFlow 2.x, Keras
- **音訊處理**: librosa, soundfile
- **影像處理**: PIL (Pillow), numpy
- **雲端 AI**: google-generativeai (Gemini API)

## 專案結構

```
pc_inference/
├── main.py              # Flask/FastAPI Socket Server (主程式入口)
├── models/              # 模型存放目錄
│   └── (模型檔案)
├── utils/               # 影像/音訊前處理工具
│   ├── image_preprocessor.py
│   └── audio_preprocessor.py
└── README.md            # 本檔案
```

## 使用方式

1. **安裝依賴**
   ```bash
   pip install -r requirements.txt
   ```

2. **設定環境變數** (`.env` 檔案)
   ```env
   GOOGLE_API_KEY=your_api_key_here
   VISION_WEIGHT=0.6
   AUDIO_WEIGHT=0.4
   CONFIDENCE_THRESHOLD=0.85
   ```

3. **啟動伺服器**
   ```bash
   python main.py
   ```

4. **測試 API**
   ```bash
   curl -X POST http://localhost:5000/predict \
     -H "Content-Type: application/json" \
     -d '{"image": "base64_encoded_image", "audio": "base64_encoded_audio"}'
   ```

## 注意事項

- **絕對禁止**: 此層級不應包含 FSM 邏輯或硬體控制
- **模型路徑**: 若未提供模型路徑，將使用預設架構 (僅供開發測試)
- **信心值**: 所有推論結果必須提供信心值 (Confidence Score)
- **錯誤處理**: 必須包含完整的錯誤處理與降級策略

## 參考文獻

- 對應計畫書章節: [cite: 187, 199, 244, 246]
- 通訊協議: [cite: 197]
- 信心值要求: [cite: 127, 200]
