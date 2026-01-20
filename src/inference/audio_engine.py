"""
Audio Engine - 音訊頻譜分析引擎
對應計畫書: [cite: 243, 244, 246]

職責:
- 接收音訊片段 (WAV/MP3 或原始音訊資料)
- 提取 MFCC (Mel-Frequency Cepstral Coefficients) 特徵
- 使用 CNN 模型進行分類推論
- 回傳分類結果與信心值 [cite: 127, 200]

硬體限制: 僅在 PC 層執行，Pi 層禁止執行 AI 推論
"""

import numpy as np
import librosa
import tensorflow as tf
from tensorflow import keras
from typing import Dict, Optional, Union
import io
import soundfile as sf

# 垃圾分類類別定義 [cite: 152] (與 vision_engine 一致)
CLASS_CATEGORIES = ["Paper", "Plastic", "General", "Metal"]

class AudioEngine:
    """
    音訊頻譜分析引擎
    
    使用 MFCC 特徵提取 + CNN 模型進行音訊分類
    輸入: 音訊波形 (預設 2 秒，22050 Hz 採樣率)
    輸出: 類別名稱與信心值
    """
    
    def __init__(
        self, 
        model_path: Optional[str] = None,
        sample_rate: int = 22050,
        duration: float = 2.0,
        n_mfcc: int = 13
    ):
        """
        初始化音訊引擎
        
        Args:
            model_path: 預訓練模型路徑 (若為 None 則使用預設架構)
            sample_rate: 音訊採樣率 (Hz)
            duration: 音訊片段長度 (秒)
            n_mfcc: MFCC 特徵數量
        """
        self.sample_rate = sample_rate
        self.duration = duration
        self.n_mfcc = n_mfcc
        self.model = None
        self.model_path = model_path
        
        # 計算預期的音訊長度
        self.expected_length = int(sample_rate * duration)
        
        # 載入或建立模型
        self._load_model()
    
    def _load_model(self):
        """
        載入音訊 CNN 模型
        
        若 model_path 為 None，則建立一個新的模型架構 (用於開發測試)
        實際部署時應載入已訓練的模型權重
        """
        if self.model_path:
            try:
                # 載入已訓練的模型 [cite: 243, 244]
                self.model = keras.models.load_model(self.model_path)
                print(f"[Audio] 已載入模型: {self.model_path}")
            except Exception as e:
                print(f"[Audio] 警告: 無法載入模型 {self.model_path}: {e}")
                print("[Audio] 使用預設架構...")
                self._create_default_model()
        else:
            # 建立預設模型架構 (用於開發階段)
            self._create_default_model()
    
    def _create_default_model(self):
        """
        建立預設的 CNN 模型架構 (用於 MFCC 特徵分類)
        
        注意: 此模型未經訓練，僅用於架構測試
        實際使用時必須載入已訓練的權重
        
        架構設計:
        - 輸入: MFCC 特徵圖 (時間軸 x 頻率軸)
        - 使用 2D CNN 層提取時頻特徵
        - 輸出: 4 類垃圾分類
        """
        # MFCC 特徵圖的典型尺寸: (時間幀數, n_mfcc)
        # 假設 2 秒音訊，hop_length=512，約有 87 個時間幀
        # 實際尺寸會根據音訊長度與 hop_length 調整
        time_frames = int(self.duration * self.sample_rate / 512)  # 估算
        
        # 建立 CNN 模型
        inputs = keras.Input(shape=(time_frames, self.n_mfcc, 1))
        
        # 第一層 CNN: 提取局部時頻特徵
        x = keras.layers.Conv2D(32, (3, 3), activation='relu', padding='same')(inputs)
        x = keras.layers.MaxPooling2D((2, 2))(x)
        
        # 第二層 CNN: 提取更高層特徵
        x = keras.layers.Conv2D(64, (3, 3), activation='relu', padding='same')(x)
        x = keras.layers.MaxPooling2D((2, 2))(x)
        
        # 第三層 CNN
        x = keras.layers.Conv2D(128, (3, 3), activation='relu', padding='same')(x)
        x = keras.layers.GlobalAveragePooling2D()(x)
        
        # 全連接層
        x = keras.layers.Dense(64, activation='relu')(x)
        x = keras.layers.Dropout(0.3)(x)
        
        # 輸出層: 4 個類別 [cite: 152]
        outputs = keras.layers.Dense(len(CLASS_CATEGORIES), activation='softmax')(x)
        
        self.model = keras.Model(inputs, outputs)
        print(f"[Audio] 已建立預設 CNN 架構 (未訓練, 輸入尺寸: {time_frames}x{self.n_mfcc})")
    
    def preprocess_audio(self, audio_input: Union[str, np.ndarray, bytes]) -> np.ndarray:
        """
        音訊預處理
        
        將輸入音訊轉換為模型所需的 MFCC 特徵:
        1. 載入音訊 (支援多種格式)
        2. 重採樣至指定採樣率
        3. 調整長度至固定時長
        4. 提取 MFCC 特徵 [cite: 243]
        
        Args:
            audio_input: 可以是以下格式:
                - 檔案路徑字串 (WAV, MP3 等)
                - numpy array (音訊波形)
                - bytes (原始音訊資料)
        
        Returns:
            MFCC 特徵圖 (time_frames, n_mfcc, 1) - 已擴展維度供模型使用
        """
        try:
            # 處理不同輸入格式
            if isinstance(audio_input, str):
                # 檔案路徑
                y, sr = librosa.load(audio_input, sr=self.sample_rate, duration=self.duration)
            elif isinstance(audio_input, bytes):
                # 原始音訊資料 (bytes)
                y, sr = sf.read(io.BytesIO(audio_input), samplerate=self.sample_rate)
                # 轉換為單聲道
                if len(y.shape) > 1:
                    y = np.mean(y, axis=1)
                # 限制長度
                if len(y) > self.expected_length:
                    y = y[:self.expected_length]
            elif isinstance(audio_input, np.ndarray):
                # numpy array
                y = audio_input
                # 假設已為正確採樣率，若需要可進行重採樣
                if len(y) > self.expected_length:
                    y = y[:self.expected_length]
                elif len(y) < self.expected_length:
                    # 零填充
                    y = np.pad(y, (0, self.expected_length - len(y)), mode='constant')
            else:
                raise ValueError(f"不支援的音訊格式: {type(audio_input)}")
            
            # 確保為單聲道
            if len(y.shape) > 1:
                y = np.mean(y, axis=1)
            
            # 調整長度至固定時長
            if len(y) > self.expected_length:
                y = y[:self.expected_length]
            elif len(y) < self.expected_length:
                y = np.pad(y, (0, self.expected_length - len(y)), mode='constant')
            
            # 提取 MFCC 特徵 [cite: 243]
            # n_mfcc: MFCC 係數數量
            # hop_length: 時間解析度 (較小值 = 更高時間解析度)
            mfccs = librosa.feature.mfcc(
                y=y,
                sr=self.sample_rate,
                n_mfcc=self.n_mfcc,
                hop_length=512
            )
            
            # 轉置: (n_mfcc, time_frames) -> (time_frames, n_mfcc)
            mfccs = mfccs.T
            
            # 擴展維度以符合模型輸入 (batch_size, time_frames, n_mfcc, 1)
            mfccs = np.expand_dims(mfccs, axis=0)  # batch dimension
            mfccs = np.expand_dims(mfccs, axis=-1)  # channel dimension
            
            return mfccs
            
        except Exception as e:
            raise ValueError(f"音訊預處理錯誤: {e}")
    
    def predict(self, audio_input: Union[str, np.ndarray, bytes]) -> Dict[str, any]:
        """
        執行音訊分類推論
        
        對應計畫書中的音訊 CNN 推論流程 [cite: 243, 244, 246]
        
        Args:
            audio_input: 音訊輸入 (支援多種格式，見 preprocess_audio)
        
        Returns:
            {
                "class": "Class A",           # 預測類別
                "confidence": 0.95,           # 信心值 [cite: 127, 200]
                "all_probs": {...},           # 所有類別的機率分佈
                "status": "success"           # 狀態碼
            }
        """
        try:
            # 1. 預處理音訊 (提取 MFCC 特徵)
            mfcc_features = self.preprocess_audio(audio_input)
            
            # 2. 模型推論
            predictions = self.model.predict(mfcc_features, verbose=0)
            
            # 3. 取得最高機率的類別與信心值
            class_idx = np.argmax(predictions[0])
            confidence = float(predictions[0][class_idx])
            predicted_class = CLASS_CATEGORIES[class_idx]
            
            # 4. 建立所有類別的機率分佈字典
            all_probs = {
                CLASS_CATEGORIES[i]: float(predictions[0][i])
                for i in range(len(CLASS_CATEGORIES))
            }
            
            return {
                "class": predicted_class,
                "confidence": confidence,
                "all_probs": all_probs,
                "status": "success"
            }
            
        except Exception as e:
            # 錯誤處理: 回傳錯誤狀態 [cite: 47, 91]
            print(f"[Audio] 推論錯誤: {e}")
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
            "model_type": "CNN (MFCC-based)",
            "sample_rate": self.sample_rate,
            "duration": self.duration,
            "n_mfcc": self.n_mfcc,
            "num_classes": len(CLASS_CATEGORIES),
            "categories": CLASS_CATEGORIES,
            "model_path": self.model_path or "default_architecture"
        }


# 全域實例 (單例模式，避免重複載入模型)
_audio_engine_instance = None

def get_audio_engine(model_path: Optional[str] = None) -> AudioEngine:
    """
    取得 AudioEngine 單例實例
    
    避免重複載入模型，節省記憶體與載入時間
    """
    global _audio_engine_instance
    if _audio_engine_instance is None:
        _audio_engine_instance = AudioEngine(model_path=model_path)
    return _audio_engine_instance
