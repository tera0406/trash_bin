"""
Audio Engine - ?唾??餉???撘?
撠?閮??

?瑁痊:
- ?交?唾??挾 (WAV/MP3 ??憪閮???
- ?? MFCC (Mel-Frequency Cepstral Coefficients) ?孵噩
- 雿輻 CNN 璅∪??脰????刻?
- ???蝯??縑敹?

蝖祇??: ? PC 撅文銵?Pi 撅斤?甇Ｗ銵?AI ?刻?
"""

import numpy as np
import librosa
import tensorflow as tf
from tensorflow import keras
from typing import Dict, Optional, Union
import io
import soundfile as sf

# ???憿摰儔 (??vision_engine 銝??
CLASS_CATEGORIES = ["Paper", "Plastic", "General", "Metal"]

class AudioEngine:
    """
    ?唾??餉???撘?
    
    雿輻 MFCC ?孵噩?? + CNN 璅∪??脰??唾???
    頛詨: ?唾?瘜Ｗ耦 (?身 2 蝘?22050 Hz ?⊥見??
    頛詨: 憿?迂?縑敹?
    """
    
    def __init__(
        self, 
        model_path: Optional[str] = None,
        sample_rate: int = 22050,
        duration: float = 2.0,
        n_mfcc: int = 13
    ):
        """
        ???閮???
        
        Args:
            model_path: ??蝺湔芋?楝敺?(?亦 None ?蝙?券?閮剜瑽?
            sample_rate: ?唾??⊥見??(Hz)
            duration: ?唾??挾?瑕漲 (蝘?
            n_mfcc: MFCC ?孵噩?賊?
        """
        self.sample_rate = sample_rate
        self.duration = duration
        self.n_mfcc = n_mfcc
        self.model = None
        self.model_path = model_path
        
        # 閮????閮摨?
        self.expected_length = int(sample_rate * duration)
        
        # 頛?遣蝡芋??
        self._load_model()
    
    def _load_model(self):
        """
        頛?唾? CNN 璅∪?
        
        ??model_path ??None嚗?撱箇?銝??芋?瑽?(?冽?皜祈岫)
        撖阡??函蔡??頛撌脰?蝺渡?璅∪?甈?
        """
        if self.model_path:
            try:
                # 頛撌脰?蝺渡?璅∪?
                self.model = keras.models.load_model(self.model_path)
                print(f"[Audio] 撌脰??交芋?? {self.model_path}")
            except Exception as e:
                print(f"[Audio] 霅血?: ?⊥?頛璅∪? {self.model_path}: {e}")
                print("[Audio] 雿輻?身?嗆?...")
                self._create_default_model()
        else:
            # 撱箇??身璅∪??嗆? (?冽??挾)
            self._create_default_model()
    
    def _create_default_model(self):
        """
        撱箇??身??CNN 璅∪??嗆? (?冽 MFCC ?孵噩??)
        
        瘜冽?: 甇斗芋?蝬?蝺湛???潭瑽葫閰?
        撖阡?雿輻?????亙歇閮毀????
        
        ?嗆?閮剛?:
        - 頛詨: MFCC ?孵噩??(??頠?x ?餌?頠?
        - 雿輻 2D CNN 撅斗????餌敺?
        - 頛詨: 4 憿??曉?憿?
        """
        # MFCC ?孵噩???詨?撠箏站: (??撟?? n_mfcc)
        # ?身 2 蝘閮?hop_length=512嚗???87 ????
        # 撖阡?撠箏站??閮摨西? hop_length 隤踵
        time_frames = int(self.duration * self.sample_rate / 512)  # 隡啁?
        
        # 撱箇? CNN 璅∪?
        inputs = keras.Input(shape=(time_frames, self.n_mfcc, 1))
        
        # 蝚砌?撅?CNN: ??撅?冽??餌敺?
        x = keras.layers.Conv2D(32, (3, 3), activation='relu', padding='same')(inputs)
        x = keras.layers.MaxPooling2D((2, 2))(x)
        
        # 蝚砌?撅?CNN: ???湧?撅斤敺?
        x = keras.layers.Conv2D(64, (3, 3), activation='relu', padding='same')(x)
        x = keras.layers.MaxPooling2D((2, 2))(x)
        
        # 蝚砌?撅?CNN
        x = keras.layers.Conv2D(128, (3, 3), activation='relu', padding='same')(x)
        x = keras.layers.GlobalAveragePooling2D()(x)
        
        # ?券?撅?
        x = keras.layers.Dense(64, activation='relu')(x)
        x = keras.layers.Dropout(0.3)(x)
        
        # 頛詨撅? 4 ????
        outputs = keras.layers.Dense(len(CLASS_CATEGORIES), activation='softmax')(x)
        
        self.model = keras.Model(inputs, outputs)
        print(f"[Audio] 撌脣遣蝡?閮?CNN ?嗆? (?芾?蝺? 頛詨撠箏站: {time_frames}x{self.n_mfcc})")
    
    def preprocess_audio(self, audio_input: Union[str, np.ndarray, bytes]) -> np.ndarray:
        """
        ?唾?????
        
        撠撓?仿閮??璅∪?????MFCC ?孵噩:
        1. 頛?唾? (?舀憭車?澆?)
        2. ?璅????⊥見??
        3. 隤踵?瑕漲?喳摰???
        4. ?? MFCC ?孵噩
        
        Args:
            audio_input: ?臭誑?臭誑銝撘?
                - 瑼?頝臬?摮葡 (WAV, MP3 蝑?
                - numpy array (?唾?瘜Ｗ耦)
                - bytes (???唾?鞈?)
        
        Returns:
            MFCC ?孵噩??(time_frames, n_mfcc, 1) - 撌脫撅雁摨虫?璅∪?雿輻
        """
        try:
            # ??銝?頛詨?澆?
            if isinstance(audio_input, str):
                # 瑼?頝臬?
                y, sr = librosa.load(audio_input, sr=self.sample_rate, duration=self.duration)
            elif isinstance(audio_input, bytes):
                # ???唾?鞈? (bytes)
                y, sr = sf.read(io.BytesIO(audio_input), samplerate=self.sample_rate)
                # 頧??箏?脤?
                if len(y.shape) > 1:
                    y = np.mean(y, axis=1)
                # ??瑕漲
                if len(y) > self.expected_length:
                    y = y[:self.expected_length]
            elif isinstance(audio_input, np.ndarray):
                # numpy array
                y = audio_input
                # ?身撌脩甇?Ⅱ?⊥見???仿?閬?脰??璅?
                if len(y) > self.expected_length:
                    y = y[:self.expected_length]
                elif len(y) < self.expected_length:
                    # ?嗅‵??
                    y = np.pad(y, (0, self.expected_length - len(y)), mode='constant')
            else:
                raise ValueError(f"銝?渡??唾??澆?: {type(audio_input)}")
            
            # 蝣箔??箏?脤?
            if len(y.shape) > 1:
                y = np.mean(y, axis=1)
            
            # 隤踵?瑕漲?喳摰???
            if len(y) > self.expected_length:
                y = y[:self.expected_length]
            elif len(y) < self.expected_length:
                y = np.pad(y, (0, self.expected_length - len(y)), mode='constant')
            
            # ?? MFCC ?孵噩
            # n_mfcc: MFCC 靽?賊?
            # hop_length: ??閫??摨?(頛???= ?湧???閫??摨?
            mfccs = librosa.feature.mfcc(
                y=y,
                sr=self.sample_rate,
                n_mfcc=self.n_mfcc,
                hop_length=512
            )
            
            # 頧蔭: (n_mfcc, time_frames) -> (time_frames, n_mfcc)
            mfccs = mfccs.T
            
            # ?游?蝬剖漲隞亦泵?芋?撓??(batch_size, time_frames, n_mfcc, 1)
            mfccs = np.expand_dims(mfccs, axis=0)  # batch dimension
            mfccs = np.expand_dims(mfccs, axis=-1)  # channel dimension
            
            return mfccs
            
        except Exception as e:
            raise ValueError(f"?唾????隤? {e}")
    
    def predict(self, audio_input: Union[str, np.ndarray, bytes]) -> Dict[str, any]:
        """
        ?瑁??唾????刻?
        
        撠?閮?訾葉?閮?CNN ?刻?瘚?
        
        Args:
            audio_input: ?唾?頛詨 (?舀憭車?澆?嚗? preprocess_audio)
        
        Returns:
            {
                "class": "Class A",           # ?葫憿
                "confidence": 0.95,           # 靽∪???
                "all_probs": {...},           # ????亦?璈???
                "status": "success"           # ??Ⅳ
            }
        """
        try:
            # 1. ???閮?(?? MFCC ?孵噩)
            mfcc_features = self.preprocess_audio(audio_input)
            
            # 2. 璅∪??刻?
            predictions = self.model.predict(mfcc_features, verbose=0)
            
            # 3. ???擃???憿?縑敹?
            class_idx = np.argmax(predictions[0])
            confidence = float(predictions[0][class_idx])
            predicted_class = CLASS_CATEGORIES[class_idx]
            
            # 4. 撱箇?????亦?璈???摮
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
            # ?航炊??: ??航炊???
            print(f"[Audio] ?刻??航炊: {e}")
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
            "model_type": "CNN (MFCC-based)",
            "sample_rate": self.sample_rate,
            "duration": self.duration,
            "n_mfcc": self.n_mfcc,
            "num_classes": len(CLASS_CATEGORIES),
            "categories": CLASS_CATEGORIES,
            "model_path": self.model_path or "default_architecture"
        }


# ?典?撖虫? (?桐?璅∪?嚗??銴??交芋??
_audio_engine_instance = None

def get_audio_engine(model_path: Optional[str] = None) -> AudioEngine:
    """
    ?? AudioEngine ?桐?撖虫?
    
    ?踹???頛璅∪?嚗????園????交???
    """
    global _audio_engine_instance
    if _audio_engine_instance is None:
        _audio_engine_instance = AudioEngine(model_path=model_path)
    return _audio_engine_instance

