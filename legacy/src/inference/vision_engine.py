"""
Vision Engine - EfficientNet 敶勗?颲刻?撘?
撠?閮??

?瑁痊:
- ?交敶勗?鞈? (base64 ??獢楝敺?
- 雿輻 EfficientNet 璅∪??脰????刻?
- ???蝯??縑敹?(Confidence Score)

蝖祇??: ? PC 撅文銵?Pi 撅斤?甇Ｗ銵?AI ?刻?
"""

import numpy as np
import tensorflow as tf
from tensorflow import keras
from PIL import Image
import io
import base64
from typing import Dict, Tuple, Optional

# ???憿摰儔 (閮毀??甇?Ⅱ??嚗 10 憿?
CLASS_CATEGORIES = [
    "battery", "biological", "cardboard", "clothes", "glass", 
    "metal", "paper", "plastic", "shoes", "trash"
]

# 憿??銵? 撠?10 ?敦????????4 憭折? (Pi ?芾???4 憿?
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
    EfficientNet 敶勗?颲刻?撘?
    
    雿輻 EfficientNet-B0 雿?箇??嗆?
    頛詨: 224x224 RGB 敶勗?
    頛詨: 憿?迂?縑敹?(??敺?
    """
    
    def __init__(self, model_path: Optional[str] = None, img_size: int = 224):
        """
        ????閬箏???
        
        Args:
            model_path: ??蝺湔芋?楝敺?(?亦 None ?蝙?券?閮剜瑽?
            img_size: 頛詨敶勗?撠箏站 (EfficientNet 璅???224x224)
        """
        self.img_size = img_size
        self.model = None
        self.model_path = model_path
        
        # 頛?遣蝡芋??
        self._load_model()
    
    def _load_model(self):
        """
        頛 EfficientNet 璅∪?
        
        ??model_path ??None嚗?撱箇?銝??芋?瑽?(?冽?皜祈岫)
        撖阡??函蔡??頛撌脰?蝺渡?璅∪?甈?
        """
        if self.model_path:
            try:
                # 頛撌脰?蝺渡?璅∪?
                self.model = keras.models.load_model(self.model_path)
                print(f"[Vision] 撌脰??交芋?? {self.model_path}")
            except Exception as e:
                print(f"[Vision] 霅血?: ?⊥?頛璅∪? {self.model_path}: {e}")
                print("[Vision] 雿輻?身?嗆?...")
                self._create_default_model()
        else:
            # 撱箇??身璅∪??嗆? (?冽??挾)
            self._create_default_model()
    
    def _create_default_model(self):
        """
        撱箇??身??EfficientNet-B0 璅∪??嗆?
        
        瘜冽?: 甇斗芋?蝬?蝺湛???潭瑽葫閰?
        撖阡?雿輻?????亙歇閮毀????
        """
        # 雿輻 EfficientNet-B0 雿?孵噩????
        base_model = keras.applications.EfficientNetB0(
            weights='imagenet',  # 雿輻 ImageNet ??蝺湔???
            include_top=False,   # 銝??恍?撅文?憿
            input_shape=(self.img_size, self.img_size, 3)
        )
        
        # ???箇?璅∪? (?舫嚗凝隤踵??航圾??
        base_model.trainable = False
        
        # 撱箇?摰璅∪?
        inputs = keras.Input(shape=(self.img_size, self.img_size, 3))
        x = base_model(inputs, training=False)
        x = keras.layers.GlobalAveragePooling2D()(x)
        x = keras.layers.Dropout(0.2)(x)
        # 頛詨撅? 撠???憿?賊?
        outputs = keras.layers.Dense(len(CLASS_CATEGORIES), activation='softmax')(x)
        
        self.model = keras.Model(inputs, outputs)
        print("[Vision] 撌脣遣蝡?閮?EfficientNet-B0 ?嗆? (?芾?蝺?")
    
    def preprocess_image(self, image_input) -> np.ndarray:
        """
        敶勗?????
        
        撠撓?亙蔣???璅∪????撘?
        - 隤踵撠箏站??224x224
        - 甇????蝝潸 [0, 1]
        - 頧???RGB ?澆?
        
        Args:
            image_input: ?臭誑?臭誑銝撘?
                - PIL Image ?拐辣
                - numpy array
                - base64 摮葡
                - 瑼?頝臬?摮葡
        
        Returns:
            ?????蔣???(224, 224, 3)
        """
        # ??銝?頛詨?澆?
        if isinstance(image_input, str):
            # ?斗??base64 ?瑼?頝臬?
            if image_input.startswith('data:image') or len(image_input) > 100:
                # Base64 蝺函Ⅳ
                try:
                    # 蝘駁 data:image/xxx;base64, ?韌
                    if ',' in image_input:
                        image_input = image_input.split(',')[1]
                    image_data = base64.b64decode(image_input)
                    img = Image.open(io.BytesIO(image_data))
                except Exception as e:
                    raise ValueError(f"?⊥?閫?Ⅳ base64 敶勗?: {e}")
            else:
                # 瑼?頝臬?
                img = Image.open(image_input)
        elif isinstance(image_input, np.ndarray):
            img = Image.fromarray(image_input)
        elif isinstance(image_input, Image.Image):
            img = image_input
        else:
            raise ValueError(f"銝?渡?敶勗??澆?: {type(image_input)}")
        
        # 蝣箔???RGB ?澆?
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # 隤踵撠箏站
        img = img.resize((self.img_size, self.img_size))
        
        # 頧???numpy array 銝行迤閬?
        img_array = np.array(img, dtype=np.float32) / 255.0
        
        # ?游?蝬剖漲隞亦泵?芋?撓??(batch_size, height, width, channels)
        img_array = np.expand_dims(img_array, axis=0)
        
        return img_array
    
    def predict(self, image_input) -> Dict[str, any]:
        """
        ?瑁?敶勗????刻?
        
        Args:
            image_input: 敶勗?頛詨 (?舀憭車?澆?嚗? preprocess_image)
        
        Returns:
            {
                "class": "Paper",             # ??敺??葫憿
                "confidence": 0.95,           # 靽∪???
                "all_probs": {...},           # ????亦?璈??? (??憿)
                "status": "success"           # ??Ⅳ
            }
        """
        try:
            # 1. ???蔣??
            processed_img = self.preprocess_image(image_input)
            
            # 2. 璅∪??刻?
            predictions = self.model.predict(processed_img, verbose=0)
            
            # [Debug] ?啣 Top 3 ?葫蝝Ｗ?
            top_3_indices = np.argsort(predictions[0])[-3:][::-1]
            print(f"[Vision Debug] Top 3 Predictions:")
            for idx in top_3_indices:
                p_val = predictions[0][idx]
                c_name = CLASS_CATEGORIES[idx] if idx < len(CLASS_CATEGORIES) else "Unknown"
                print(f"  - {c_name} (Index {idx}): {p_val:.4f}")

            # 3. ???擃???憿?縑敹?
            class_idx = np.argmax(predictions[0])
            confidence = float(predictions[0][class_idx])
            
            # [Logic] 憿撠???撠?
            if class_idx < len(CLASS_CATEGORIES):
                raw_class = CLASS_CATEGORIES[class_idx]
                # [Map] 撠敦???亥?? 4 憭折?
                predicted_class = CATEGORY_MAPPING.get(raw_class, "General")
                print(f"[VisionResult] ??: {raw_class} ({confidence:.3f}) -> ??: {predicted_class}")
            else:
                print(f"[Vision] 霅血?: ?葫蝝Ｗ? {class_idx} 頞蝭?")
                predicted_class = "unknown"
                confidence = 0.0

            # 4. 撱箇?????亦?璈???摮 (??憿)
            all_probs = {}
            for i in range(min(len(CLASS_CATEGORIES), len(predictions[0]))):
                all_probs[CLASS_CATEGORIES[i]] = float(predictions[0][i])
            
            return {
                "class": predicted_class, # ?頧?敺? 4 憭折?
                "confidence": confidence,
                "all_probs": all_probs,
                "status": "success"
            }
            
        except Exception as e:
            # ?航炊??: ??航炊???
            print(f"[Vision] ?刻??航炊: {e}")
            return {
                "class": "unknown",
                "confidence": 0.0,
                "all_probs": {},
                "status": f"error: {str(e)}"
            }
    
    def get_model_info(self) -> Dict[str, any]:
        """
        ??璅∪?鞈? (?冽?日???
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


# ?典?撖虫? (?桐?璅∪?嚗??銴??交芋??
_vision_engine_instance = None

def get_vision_engine(model_path: Optional[str] = None) -> VisionEngine:
    """
    ?? VisionEngine ?桐?撖虫?
    
    ?踹???頛璅∪?嚗????園????交???
    """
    global _vision_engine_instance
    if _vision_engine_instance is None:
        _vision_engine_instance = VisionEngine(model_path=model_path)
    return _vision_engine_instance

