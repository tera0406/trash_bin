"""
Vision Engine - EfficientNet 影像辨識引擎
對應計畫書: [cite: 199, 202, 221]

職責:
- 接收影像資料 (base64 或檔案路徑)
- 使用 EfficientNet 模型進行分類推論
- 回傳分類結果與信心值 (Confidence Score) [cite: 127, 200]

硬體限制: 僅在 PC 層執行，Pi 層禁止執行 AI 推論
"""

import numpy as np
import tensorflow as tf
from tensorflow import keras
from PIL import Image
import io
import base64
from typing import Dict, Tuple, Optional

# 垃圾分類類別定義 (訓練時的正確順序，共 10 類)
CLASS_CATEGORIES = [
    "battery", "biological", "cardboard", "clothes", "glass", 
    "metal", "paper", "plastic", "shoes", "trash"
]

# 類別映射表: 將 10 個細項類別 映射回 4 大類 (Pi 只認這 4 類)
CATEGORY_MAPPING = {
    "battery": "Metal",
    "biological": "General",
    "cardboard": "Paper",
    "clothes": "General",
    "glass": "General",
    "metal": "Metal",
    "paper": "Paper",
    "plastic": "Plastic",
    "shoes": "General",
    "trash": "General"
}

class VisionEngine:
    """
    EfficientNet 影像辨識引擎
    
    使用 EfficientNet-B0 作為基礎架構
    輸入: 224x224 RGB 影像
    輸出: 類別名稱與信心值 (映射後)
    """
    
    def __init__(self, model_path: Optional[str] = None, img_size: int = 224):
        """
        初始化視覺引擎
        
        Args:
            model_path: 預訓練模型路徑 (若為 None 則使用預設架構)
            img_size: 輸入影像尺寸 (EfficientNet 標準為 224x224)
        """
        self.img_size = img_size
        self.model = None
        self.model_path = model_path
        
        # 載入或建立模型
        self._load_model()
    
    def _load_model(self):
        """
        載入 EfficientNet 模型
        
        若 model_path 為 None，則建立一個新的模型架構 (用於開發測試)
        實際部署時應載入已訓練的模型權重
        """
        if self.model_path:
            try:
                # 載入已訓練的模型 [cite: 199]
                self.model = keras.models.load_model(self.model_path)
                print(f"[Vision] 已載入模型: {self.model_path}")
            except Exception as e:
                print(f"[Vision] 警告: 無法載入模型 {self.model_path}: {e}")
                print("[Vision] 使用預設架構...")
                self._create_default_model()
        else:
            # 建立預設模型架構 (用於開發階段)
            self._create_default_model()
    
    def _create_default_model(self):
        """
        建立預設的 EfficientNet-B0 模型架構
        
        注意: 此模型未經訓練，僅用於架構測試
        實際使用時必須載入已訓練的權重
        """
        # 使用 EfficientNet-B0 作為特徵提取器 [cite: 199]
        base_model = keras.applications.EfficientNetB0(
            weights='imagenet',  # 使用 ImageNet 預訓練權重
            include_top=False,   # 不包含頂層分類器
            input_shape=(self.img_size, self.img_size, 3)
        )
        
        # 凍結基礎模型 (可選，微調時可解凍)
        base_model.trainable = False
        
        # 建立完整模型
        inputs = keras.Input(shape=(self.img_size, self.img_size, 3))
        x = base_model(inputs, training=False)
        x = keras.layers.GlobalAveragePooling2D()(x)
        x = keras.layers.Dropout(0.2)(x)
        # 輸出層: 對應我們的類別數量
        outputs = keras.layers.Dense(len(CLASS_CATEGORIES), activation='softmax')(x)
        
        self.model = keras.Model(inputs, outputs)
        print("[Vision] 已建立預設 EfficientNet-B0 架構 (未訓練)")
    
    def preprocess_image(self, image_input) -> np.ndarray:
        """
        影像預處理
        
        將輸入影像轉換為模型所需的格式:
        - 調整尺寸至 224x224
        - 正規化像素值至 [0, 1]
        - 轉換為 RGB 格式
        
        Args:
            image_input: 可以是以下格式:
                - PIL Image 物件
                - numpy array
                - base64 字串
                - 檔案路徑字串
        
        Returns:
            預處理後的影像陣列 (224, 224, 3)
        """
        # 處理不同輸入格式
        if isinstance(image_input, str):
            # 判斷是 base64 還是檔案路徑
            if image_input.startswith('data:image') or len(image_input) > 100:
                # Base64 編碼
                try:
                    # 移除 data:image/xxx;base64, 前綴
                    if ',' in image_input:
                        image_input = image_input.split(',')[1]
                    image_data = base64.b64decode(image_input)
                    img = Image.open(io.BytesIO(image_data))
                except Exception as e:
                    raise ValueError(f"無法解碼 base64 影像: {e}")
            else:
                # 檔案路徑
                img = Image.open(image_input)
        elif isinstance(image_input, np.ndarray):
            img = Image.fromarray(image_input)
        elif isinstance(image_input, Image.Image):
            img = image_input
        else:
            raise ValueError(f"不支援的影像格式: {type(image_input)}")
        
        # 確保為 RGB 格式
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # 調整尺寸
        img = img.resize((self.img_size, self.img_size))
        
        # 轉換為 numpy array 並正規化
        img_array = np.array(img, dtype=np.float32) / 255.0
        
        # 擴展維度以符合模型輸入 (batch_size, height, width, channels)
        img_array = np.expand_dims(img_array, axis=0)
        
        return img_array
    
    def predict(self, image_input) -> Dict[str, any]:
        """
        執行影像分類推論
        
        Args:
            image_input: 影像輸入 (支援多種格式，見 preprocess_image)
        
        Returns:
            {
                "class": "Paper",             # 映射後的預測類別
                "confidence": 0.95,           # 信心值
                "all_probs": {...},           # 所有類別的機率分佈 (原始類別)
                "status": "success"           # 狀態碼
            }
        """
        try:
            # 1. 預處理影像
            processed_img = self.preprocess_image(image_input)
            
            # 2. 模型推論
            predictions = self.model.predict(processed_img, verbose=0)
            
            # [Debug] 印出 Top 3 預測索引
            top_3_indices = np.argsort(predictions[0])[-3:][::-1]
            print(f"[Vision Debug] Top 3 Predictions:")
            for idx in top_3_indices:
                p_val = predictions[0][idx]
                c_name = CLASS_CATEGORIES[idx] if idx < len(CLASS_CATEGORIES) else "Unknown"
                print(f"  - {c_name} (Index {idx}): {p_val:.4f}")

            # 3. 取得最高機率的類別與信心值
            class_idx = np.argmax(predictions[0])
            confidence = float(predictions[0][class_idx])
            
            # [Logic] 類別對應與映射
            if class_idx < len(CLASS_CATEGORIES):
                raw_class = CLASS_CATEGORIES[class_idx]
                # [Map] 將細項類別轉換為 4 大類
                predicted_class = CATEGORY_MAPPING.get(raw_class, "General")
                print(f"[VisionResult] 原始: {raw_class} ({confidence:.3f}) -> 映射: {predicted_class}")
            else:
                print(f"[Vision] 警告: 預測索引 {class_idx} 超出範圍")
                predicted_class = "unknown"
                confidence = 0.0

            # 4. 建立所有類別的機率分佈字典 (原始類別)
            all_probs = {}
            for i in range(min(len(CLASS_CATEGORIES), len(predictions[0]))):
                all_probs[CLASS_CATEGORIES[i]] = float(predictions[0][i])
            
            return {
                "class": predicted_class, # 回傳轉換後的 4 大類
                "confidence": confidence,
                "all_probs": all_probs,
                "status": "success"
            }
            
        except Exception as e:
            # 錯誤處理: 回傳錯誤狀態 [cite: 47, 91]
            print(f"[Vision] 推論錯誤: {e}")
            return {
                "class": "unknown",
                "confidence": 0.0,
                "all_probs": {},
                "status": f"error: {str(e)}"
            }
    
    def get_model_info(self) -> Dict[str, any]:
        """
        取得模型資訊 (用於除錯與監控)
        """
        if self.model is None:
            return {"status": "model_not_loaded"}
        
        return {
            "model_type": "EfficientNet-B0",
            "input_size": (self.img_size, self.img_size, 3),
            "num_classes": len(CLASS_CATEGORIES),
            "categories": CLASS_CATEGORIES,
            "model_path": self.model_path or "default_architecture"
        }


# 全域實例 (單例模式，避免重複載入模型)
_vision_engine_instance = None

def get_vision_engine(model_path: Optional[str] = None) -> VisionEngine:
    """
    取得 VisionEngine 單例實例
    
    避免重複載入模型，節省記憶體與載入時間
    """
    global _vision_engine_instance
    if _vision_engine_instance is None:
        _vision_engine_instance = VisionEngine(model_path=model_path)
    return _vision_engine_instance
