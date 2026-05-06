"""
Audio Preprocessor - 音訊前處理工具
對應計畫書: [cite: 243, 244]

職責:
- 音訊格式轉換與載入
- 重採樣與長度標準化
- MFCC 特徵提取
"""

import librosa
import numpy as np
import soundfile as sf
import io
from typing import Union

def preprocess_audio(
    audio_input: Union[str, np.ndarray, bytes],
    sample_rate: int = 22050,
    duration: float = 2.0,
    n_mfcc: int = 13
) -> np.ndarray:
    """
    音訊前處理與 MFCC 特徵提取
    
    Args:
        audio_input: 音訊輸入 (檔案路徑, numpy array, bytes)
        sample_rate: 目標採樣率
        duration: 目標時長 (秒)
        n_mfcc: MFCC 係數數量
    
    Returns:
        MFCC 特徵圖 (1, time_frames, n_mfcc, 1)
    """
    # 載入音訊
    if isinstance(audio_input, str):
        y, sr = librosa.load(audio_input, sr=sample_rate, duration=duration)
    elif isinstance(audio_input, bytes):
        y, sr = sf.read(io.BytesIO(audio_input), samplerate=sample_rate)
        if len(y.shape) > 1:
            y = np.mean(y, axis=1)
    elif isinstance(audio_input, np.ndarray):
        y = audio_input
    else:
        raise ValueError(f"不支援的音訊格式: {type(audio_input)}")
    
    # 確保單聲道
    if len(y.shape) > 1:
        y = np.mean(y, axis=1)
    
    # 調整長度
    expected_length = int(sample_rate * duration)
    if len(y) > expected_length:
        y = y[:expected_length]
    elif len(y) < expected_length:
        y = np.pad(y, (0, expected_length - len(y)), mode='constant')
    
    # 提取 MFCC 特徵
    mfccs = librosa.feature.mfcc(
        y=y,
        sr=sample_rate,
        n_mfcc=n_mfcc,
        hop_length=512
    )
    
    # 轉置並擴展維度
    mfccs = mfccs.T
    mfccs = np.expand_dims(mfccs, axis=0)  # batch
    mfccs = np.expand_dims(mfccs, axis=-1)  # channel
    
    return mfccs
