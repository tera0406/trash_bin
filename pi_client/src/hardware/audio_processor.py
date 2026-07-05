# -*- coding: utf-8 -*-
"""
AIOT 智慧垃圾桶 - 音訊處理與環形緩衝區模組
"""
import numpy as np
import cv2
import time
import threading
import sys

# 嘗試匯入 sounddevice (若無此模組則切換為 Mock 模式)
try:
    # pyrefly: ignore [missing-import]
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False

# --- 預設工程參數設定 ---
# 預設基準值 (作為無法使用實體聲卡時的 Mock 模式參數)
FS = 48000        # 預設 48kHz
DURATION = 2.0    # 2秒
TARGET_PEAK = 0.9 # 目標峰值 (1.0 為最大不破音極限)
CHANNELS = 2      # 預設雙通道

def find_best_input_device():
    """
    動態搜尋系統中最適合的錄音設備 ID。
    優先順序：
    1. 若 config 中有設定 AUDIO_DEVICE_TARGET，且為數字，直接使用該 ID
    2. 若 config 中有設定 AUDIO_DEVICE_TARGET，且為字串，優先搜尋設備名稱包含該關鍵字的 ID
    3. 包含 "voicehat", "respeaker", "usb", "mic", "microphone", "proto" 等關鍵字的輸入設備
    4. 系統預設的輸入設備 (kind='input')
    5. 設備列表中第一個支援輸入的實體設備
    6. 回退預設值 1
    """
    if not HAS_SOUNDDEVICE:
        return 1
        
    # 嘗試從 config 取得目標設備名稱或 ID
    target = None
    try:
        from config import AUDIO_DEVICE_TARGET
        target = AUDIO_DEVICE_TARGET
    except ImportError:
        import os
        parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        try:
            from config import AUDIO_DEVICE_TARGET
            target = AUDIO_DEVICE_TARGET
        except ImportError:
            pass
            
    # 如果 target 是數字，直接轉成 int 回傳
    if target is not None:
        try:
            return int(target)
        except ValueError:
            # 說明是字串關鍵字，例如 "ATR4650"
            pass

    try:
        devices = sd.query_devices()
        
        # 1. 優先搜尋指定的目標設備關鍵字
        if target and isinstance(target, str) and target.strip():
            target_lower = target.lower()
            for idx, dev in enumerate(devices):
                if dev.get('max_input_channels', 0) > 0:
                    name_lower = dev.get('name', '').lower()
                    if target_lower in name_lower:
                        print(f"[Audio] 🔍 匹配到指定的目標麥克風 ({target}): ID {idx} - {dev['name']}")
                        return idx

        # 2. 優先匹配常見的麥克風硬體關鍵字
        keywords = ["voicehat", "respeaker", "usb", "mic", "microphone", "proto"]
        for idx, dev in enumerate(devices):
            if dev.get('max_input_channels', 0) > 0:
                name_lower = dev.get('name', '').lower()
                if any(kw in name_lower for kw in keywords):
                    print(f"[Audio] 🔍 動態匹配到優選麥克風: ID {idx} - {dev['name']}")
                    return idx
                    
        # 3. 嘗試獲取系統預設輸入設備
        try:
            default_device = sd.query_devices(kind='input')
            if default_device:
                for idx, dev in enumerate(devices):
                    if dev == default_device:
                        print(f"[Audio] 🔍 使用系統預設輸入設備: ID {idx} - {dev['name']}")
                        return idx
        except Exception:
            pass

        # 4. 尋找第一個支援輸入的設備
        for idx, dev in enumerate(devices):
            if dev.get('max_input_channels', 0) > 0:
                print(f"[Audio] 🔍 使用第一個支援的輸入設備: ID {idx} - {dev['name']}")
                return idx
                
    except Exception as e:
        print(f"[Audio] ⚠️ 動態搜尋錄音設備失敗: {e}，回退使用預設 ID 1")
    return 1

# 執行搜尋，動態獲取最合適的音訊輸入設備 ID
AUDIO_DEV_ID = find_best_input_device()

# 取得選定設備的實際預設取樣率與通道數，確保 100% 驅動相容
try:
    if HAS_SOUNDDEVICE:
        dev_info = sd.query_devices(AUDIO_DEV_ID, 'input')
        FS = int(dev_info.get('default_samplerate', 48000))
        CHANNELS = int(min(dev_info.get('max_input_channels', 2), 2))
        print(f"[Audio] 🎤 偵測到麥克風支援能力 - 取樣率: {FS}Hz | 通道數: {CHANNELS}")
except Exception as e:
    print(f"[Audio] ⚠️ 查詢麥克風具體參數失敗: {e}，回退使用預設參數 48kHz / 雙通道")

# 嘗試從 config 匯入低通截止頻率與標準化設定
try:
    from config import AUDIO_LOWPASS_CUTOFF, AUDIO_NORM_MIN_THRESHOLD, AUDIO_NORM_MAX_GAIN
except ImportError:
    import os
    parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    try:
        from config import AUDIO_LOWPASS_CUTOFF, AUDIO_NORM_MIN_THRESHOLD, AUDIO_NORM_MAX_GAIN
    except ImportError:
        AUDIO_LOWPASS_CUTOFF = 8000.0
        AUDIO_NORM_MIN_THRESHOLD = 1e-5
        AUDIO_NORM_MAX_GAIN = 100.0


class AudioBuffer:
    """
    執行緒安全的環形音訊緩衝區，預期緩衝 duration 秒的音訊 (預設 3.0 秒)
    """
    def __init__(self, duration=3.0, samplerate=FS, channels=CHANNELS):
        self.samplerate = samplerate
        self.channels = channels
        self.buffer_size = int(duration * samplerate)
        self.buffer = np.zeros((self.buffer_size, channels), dtype=np.float32)
        self.write_ptr = 0
        self.lock = threading.Lock()

    def add_data(self, data):
        """將新資料寫入環形緩衝區 (自動處理 wrap around)"""
        n_samples = len(data)
        with self.lock:
            # 確保寫入長度不超過緩衝區總長
            if n_samples > self.buffer_size:
                data = data[-self.buffer_size:]
                n_samples = len(data)

            if self.write_ptr + n_samples <= self.buffer_size:
                self.buffer[self.write_ptr : self.write_ptr + n_samples] = data
                self.write_ptr = (self.write_ptr + n_samples) % self.buffer_size
            else:
                first_part = self.buffer_size - self.write_ptr
                self.buffer[self.write_ptr : self.buffer_size] = data[:first_part]
                second_part = n_samples - first_part
                self.buffer[0 : second_part] = data[first_part:]
                self.write_ptr = second_part

    def get_last_seconds(self, seconds=1.0):
        """提取最後幾秒的音訊 (回傳 numpy.ndarray)"""
        n_samples = int(seconds * self.samplerate)
        with self.lock:
            if n_samples > self.buffer_size:
                n_samples = self.buffer_size

            if self.write_ptr >= n_samples:
                data = self.buffer[self.write_ptr - n_samples : self.write_ptr]
            else:
                part2 = self.buffer[0 : self.write_ptr]
                part1_len = n_samples - self.write_ptr
                part1 = self.buffer[self.buffer_size - part1_len : self.buffer_size]
                data = np.concatenate((part1, part2), axis=0)
            return data.copy()


class BackgroundAudioRecorder:
    """
    背景音訊錄製器，持續在背景進行環形錄音。
    支援實體麥克風串流 (sounddevice)；若不可用則自動切換為 Mock 模擬模式。
    """
    def __init__(self, buffer_duration=3.0, samplerate=FS, channels=CHANNELS, device_id=AUDIO_DEV_ID):
        self.samplerate = samplerate
        self.channels = channels
        self.device_id = device_id
        self.buffer = AudioBuffer(duration=buffer_duration, samplerate=samplerate, channels=channels)
        self.stream = None
        self.running = False
        self.is_mock = False
        self._mock_thread = None

    def _callback(self, indata, frames, time_info, status):
        """sounddevice InputStream callback"""
        if status:
            print(f"  [Audio] 串流狀態警示: {status}")
        self.buffer.add_data(indata)

    def _mock_recording_loop(self):
        """Mock 模式下的背景模擬音訊生成線程，每秒寫入 48000 點"""
        chunk_size = 1024
        sleep_time = chunk_size / self.samplerate
        while self.running:
            # 生成極小的白噪音雜訊
            noise = np.random.normal(0, 0.005, (chunk_size, self.channels)).astype(np.float32)
            self.buffer.add_data(noise)
            time.sleep(sleep_time)

    def start(self):
        """啟動錄音串流 (若實體設備不可用，則切換至 Mock 模式)"""
        if self.running:
            return
        self.running = True

        if HAS_SOUNDDEVICE:
            try:
                # 測試開啟串流
                self.stream = sd.InputStream(
                    samplerate=self.samplerate,
                    channels=self.channels,
                    dtype='float32',
                    device=self.device_id,
                    callback=self._callback
                )
                self.stream.start()
                self.is_mock = False
                print(f"[Audio] 🎤 背景音訊環形緩衝區已啟動實體錄音流 (設備 ID: {self.device_id})")
                return
            except Exception as e:
                print(f"[Audio] ⚠️ 無法啟動實體錄音流 ({e})，切換至 Mock 模擬錄音")
        else:
            print("[Audio] ⚠️ 系統未偵測到 sounddevice 套件，切換至 Mock 模擬錄音")

        # 啟動 Mock 線程
        self.is_mock = True
        self._mock_thread = threading.Thread(target=self._mock_recording_loop, daemon=True)
        self._mock_thread.start()
        print("[Audio] 🎤 背景音訊環形緩衝區已啟動 Mock 模擬錄音線程")

    def stop(self):
        """停止背景錄音"""
        self.running = False
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

        if self._mock_thread:
            self._mock_thread.join(timeout=1.0)
            self._mock_thread = None
        print("[Audio] 🎤 背景音訊環形緩衝區已安全停止")

    def get_last_seconds(self, seconds=1.0):
        """
        提取最後幾秒的音訊，混音成單聲道，並完成音量自動標準化
        """
        raw_data = self.buffer.get_last_seconds(seconds)

        # 1. 混音成單聲道 (取通道平均值，若有相位相消或單聲道折半則選取較佳通道)
        if raw_data.shape[1] > 1:
            ch0 = raw_data[:, 0]
            ch1 = raw_data[:, 1]
            peak0 = np.max(np.abs(ch0))
            peak1 = np.max(np.abs(ch1))
            
            mono_data = np.mean(raw_data, axis=1)
            mean_peak = np.max(np.abs(mono_data))
            
            max_ch_peak = max(peak0, peak1)
            # 若平均後的峰值相較於最大的單通道峰值衰減了 30% 以上，說明存在反相抵消或單側靜音折半
            if mean_peak < max_ch_peak * 0.7:
                mono_data = ch0 if peak0 >= peak1 else ch1
                if not self.is_mock:
                    print(f"  [音訊提取] ⚠️ 偵測到通道相消或單側靜音 (Ch0 peak: {peak0:.5f}, Ch1 peak: {peak1:.5f}, Mean peak: {mean_peak:.5f})，已自動切換為優選單通道輸入。")
        else:
            mono_data = raw_data.flatten()

        # ── 1b. 低通濾波器，濾除樹莓派高頻噪聲 (電磁干擾 / 線圈音) ──
        if AUDIO_LOWPASS_CUTOFF is not None and AUDIO_LOWPASS_CUTOFF > 0:
            mono_data = lowpass_filter(mono_data, self.samplerate, cutoff=AUDIO_LOWPASS_CUTOFF)

        # 2. 自動標準化處理 (雙安全閥：降門檻 + 增益封頂)
        current_max = np.max(np.abs(mono_data))
        if current_max > AUDIO_NORM_MIN_THRESHOLD:
            gain = TARGET_PEAK / current_max
            if gain > AUDIO_NORM_MAX_GAIN:
                gain = AUDIO_NORM_MAX_GAIN
            normalized_audio = mono_data * gain
            # 只有在非 Mock 模式下才印出補償訊息，避免 console 被洗版
            if not self.is_mock:
                print(f"  [音訊提取] 提取 {seconds} 秒, 自動補償增益: {gain:.2f}x (原峰值: {current_max:.6f})")
        else:
            normalized_audio = mono_data
            if not self.is_mock:
                print(f"  [音訊提取] 提取音量極低 ({current_max:.6f} <= {AUDIO_NORM_MIN_THRESHOLD})，未進行自動音量補償")

        return normalized_audio


def lowpass_filter(y, samplerate, cutoff=8000.0):
    """
    使用純 Numpy FFT 實現的零相位磚牆式低通濾波器 (Brick-wall Low-pass Filter)。
    可完美濾除高於 cutoff 頻率的所有高頻噪訊 (例如樹莓派高頻電磁噪聲/線圈音)。
    """
    if y is None or len(y) == 0:
        return y
    
    n = len(y)
    y_fft = np.fft.rfft(y)
    freqs = np.fft.rfftfreq(n, d=1.0/samplerate)
    
    # 將高於截止頻率的頻譜分量設為 0
    y_fft[freqs > cutoff] = 0.0
    
    # 逆變換回時域
    y_filtered = np.fft.irfft(y_fft, n=n)
    return y_filtered.astype(np.float32)


# --- 以下維持原模組方法，以利相容性 ---

def record_and_process_audio(duration=DURATION, samplerate=FS, channels=CHANNELS, device_id=AUDIO_DEV_ID):
    """
    採集原始聲音 (float32)，使用多通道錄音後混音成單聲道，並進行自動音量標準化 (相容原有單次錄製)。
    """
    if not HAS_SOUNDDEVICE:
        print("  [Warning] 無法使用 sounddevice，回傳靜音資料")
        return np.zeros(int(duration * samplerate), dtype=np.float32)

    print(f"[*] 🎤 錄音中... 請投擲物體！(時長: {duration}秒)")
    try:
        raw_recording = sd.rec(
            int(duration * samplerate),
            samplerate=samplerate,
            channels=channels,
            dtype='float32',
            device=device_id
        )
        sd.wait()
        
        # 1. 混音成單聲道 (取通道平均值，若有相位相消或單聲道折半則選取較佳通道)
        if raw_recording.shape[1] > 1:
            ch0 = raw_recording[:, 0]
            ch1 = raw_recording[:, 1]
            peak0 = np.max(np.abs(ch0))
            peak1 = np.max(np.abs(ch1))
            
            mono_data = np.mean(raw_recording, axis=1)
            mean_peak = np.max(np.abs(mono_data))
            
            max_ch_peak = max(peak0, peak1)
            if mean_peak < max_ch_peak * 0.7:
                mono_data = ch0 if peak0 >= peak1 else ch1
                print(f"  [處理] ⚠️ 偵測到通道相消或單側靜音 (Ch0 peak: {peak0:.5f}, Ch1 peak: {peak1:.5f}, Mean peak: {mean_peak:.5f})，已自動切換為優選單通道輸入。")
        else:
            mono_data = raw_recording.flatten()
            
        # ── 1b. 低通濾波器，濾除樹莓派高頻噪聲 (電磁干擾 / 線圈音) ──
        if AUDIO_LOWPASS_CUTOFF is not None and AUDIO_LOWPASS_CUTOFF > 0:
            mono_data = lowpass_filter(mono_data, samplerate, cutoff=AUDIO_LOWPASS_CUTOFF)

        # 2. 自動標準化處理 (雙安全閥：降門檻 + 增益封頂)
        current_max = np.max(np.abs(mono_data))
        
        if current_max > AUDIO_NORM_MIN_THRESHOLD:
            gain = TARGET_PEAK / current_max
            if gain > AUDIO_NORM_MAX_GAIN:
                gain = AUDIO_NORM_MAX_GAIN
            normalized_audio = mono_data * gain
            print(f"  [處理] 音量已自動補償: {gain:.2f}x (原峰值: {current_max:.6f})")
        else:
            normalized_audio = mono_data
            print(f"  [警告] 錄製音量極低 ({current_max:.6f} <= {AUDIO_NORM_MIN_THRESHOLD})，未進行自動音量補償")
            
        return normalized_audio
        
    except Exception as e:
        print(f"  [Error] 錄音失敗: {e}")
        return np.zeros(int(duration * samplerate), dtype=np.float32)


def get_mel_filterbank(sr, n_fft, n_mels):
    """
    純 Numpy 實現的 Mel 濾波器組 (Mel Filterbank) 生成，與 librosa.filters.mel 輸出一致。
    """
    def hz_to_mel(hz):
        return 2595.0 * np.log10(1.0 + hz / 700.0)
    
    def mel_to_hz(mel):
        return 700.0 * (10.0**(mel / 2595.0) - 1.0)
        
    mel_min = hz_to_mel(0.0)
    mel_max = hz_to_mel(sr / 2.0)
    
    mels = np.linspace(mel_min, mel_max, n_mels + 2)
    hz = mel_to_hz(mels)
    
    bins = np.floor((n_fft + 1) * hz / sr).astype(int)
    
    fbank = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float32)
    for i in range(1, n_mels + 1):
        l = bins[i - 1]
        c = bins[i]
        r = bins[i + 1]
        for k in range(l, c):
            if c != l:
                fbank[i - 1, k] = (k - l) / (c - l)
        for k in range(c, r):
            if r != c:
                fbank[i - 1, k] = (r - k) / (r - c)
                
    return fbank


def stft_power(y, n_fft=2048, hop_length=512):
    """
    純 Numpy 實現的短時傅立葉變換 (STFT)，計算功率譜 (Power Spectrogram)。
    """
    window = np.hanning(n_fft).astype(np.float32)
    y_padded = np.pad(y, n_fft // 2, mode='reflect')
    n_frames = 1 + (len(y_padded) - n_fft) // hop_length
    
    n_freqs = n_fft // 2 + 1
    stft_matrix = np.zeros((n_freqs, n_frames), dtype=np.float32)
    
    for i in range(n_frames):
        start = i * hop_length
        frame = y_padded[start:start + n_fft]
        fft_res = np.fft.rfft(frame * window)
        stft_matrix[:, i] = np.abs(fft_res)**2
        
    return stft_matrix


def audio_to_mel_spectrogram_image(y, samplerate=FS):
    """
    將音訊波形轉為 Mel-spectrogram 頻譜圖並輸出為 JPEG 影像 bytes，供 Cross-Fusion 模型使用。
    """
    if y is None or len(y) == 0:
        print("  [Warning] 音訊數據為空，無法生成頻譜圖")
        return None
        
    try:
        power_spec = stft_power(y, n_fft=2048, hop_length=512)
        fbank = get_mel_filterbank(samplerate, n_fft=2048, n_mels=128)
        S = np.dot(fbank, power_spec)
        
        S_dB = 10.0 * np.log10(np.maximum(S, 1e-10))
        S_dB = S_dB - np.max(S_dB)
        
        min_val = -80.0
        max_val = 0.0
        S_norm = np.clip(S_dB, min_val, max_val)
        S_norm = (S_norm - min_val) / (max_val - min_val)
        S_norm = (S_norm * 255.0).astype(np.uint8)
        
        S_norm = np.flipud(S_norm)
        
        try:
            color_img = cv2.applyColorMap(S_norm, cv2.COLORMAP_VIRIDIS)
        except Exception:
            color_img = cv2.merge([S_norm, S_norm, S_norm])
            
        color_img = cv2.resize(color_img, (224, 224))
        
        _, img_encoded = cv2.imencode('.jpg', color_img)
        return img_encoded.tobytes()
        
    except Exception as e:
        print(f"  [Error] Mel-spectrogram 生成失敗: {e}")
        return None
