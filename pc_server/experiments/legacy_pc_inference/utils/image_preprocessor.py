"""
Image Preprocessor - 影像前處理工具
對應計畫書: [cite: 199, 202]

職責:
- 影像格式轉換 (base64, PIL, numpy)
- 影像尺寸調整與正規化
- 為 EfficientNet 模型準備輸入資料
"""

from PIL import Image
import numpy as np
import base64
import io
from typing import Union

def preprocess_image(image_input, img_size: int = 224) -> np.ndarray:
    """
    影像前處理
    
    Args:
        image_input: 影像輸入 (base64, 檔案路徑, PIL Image, numpy array)
        img_size: 目標尺寸 (預設 224x224)
    
    Returns:
        預處理後的影像陣列 (1, img_size, img_size, 3)
    """
    # 處理不同輸入格式
    if isinstance(image_input, str):
        if image_input.startswith('data:image') or len(image_input) > 100:
            # Base64
            if ',' in image_input:
                image_input = image_input.split(',')[1]
            img = Image.open(io.BytesIO(base64.b64decode(image_input)))
        else:
            # 檔案路徑
            img = Image.open(image_input)
    elif isinstance(image_input, np.ndarray):
        img = Image.fromarray(image_input)
    elif isinstance(image_input, Image.Image):
        img = image_input
    else:
        raise ValueError(f"不支援的影像格式: {type(image_input)}")
    
    # 轉換為 RGB
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    # 調整尺寸
    img = img.resize((img_size, img_size))
    
    # 正規化並擴展維度
    img_array = np.array(img, dtype=np.float32) / 255.0
    img_array = np.expand_dims(img_array, axis=0)
    
    return img_array
