# -*- coding: utf-8 -*-
"""
AIOT 智慧垃圾桶 - 衝擊聲觸發測試工具 (Impact Sound Trigger Test)

功能:
  1. 麥克風持續監聽，使用環形緩衝區保留最近 1 秒音訊
  2. 偵測到衝擊聲 (RMS 能量突增) 時自動觸發
  3. 觸發後續錄 1 秒 → 合併前後共 2 秒完整音訊
  4. 收音完成後拍照 (確保垃圾已穩定)
  5. 音量補償 → Mel-spectrogram → 上傳 PC 推論伺服器
  6. [選用] ESP32 致動控制

使用方式:
  python impact_trigger_test.py

安全性:
  此為獨立測試腳本，不修改任何現有程式碼。
  ESP32 致動功能預設關閉 (ENABLE_ACTUATOR = False)。

Author: Embedded System Engineer
"""

import os
import sys
import time
import threading
import numpy as np

# pyrefly: ignore [missing-import]
import sounddevice as sd
import cv2
import requests

# 匯入同級模組
try:
    from src.hardware.audio_processor import audio_to_mel_spectrogram_image
    from src.hardware.esp32_uart import ESP32UART
    from env_loader import load_env
except ImportError:
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from src.hardware.audio_processor import audio_to_mel_spectrogram_image
    from src.hardware.esp32_uart import ESP32UART
    from env_loader import load_env

# 載入環境變數
load_env()

# ═══════════════════════════════════════════════════════════════════
# 可調整參數
# ═══════════════════════════════════════════════════════════════════

# --- 麥克風硬體設定 ---
AUDIO_DEV_ID = 1        # Google voiceHAT SoundCard
FS = 48000              # 取樣率 48kHz
CHANNELS = 2            # 錄音通道數

# --- 衝擊偵測參數 ---
PRE_TRIGGER_SEC = 1.0   # 觸發前保留的音訊秒數
POST_TRIGGER_SEC = 1.0  # 觸發後續錄的音訊秒數
IMPACT_THRESHOLD = 5.0  # 衝擊判定倍率 (瞬間 RMS > 背景 RMS × 此值 = 衝擊)
COOLDOWN_SEC = 3.0      # 觸發後冷卻時間 (避免重複觸發)
BG_ADAPT_RATE = 0.02    # 背景噪音 RMS 滑動平均更新速率 (越小越穩定)

# --- 音量補償 ---
TARGET_PEAK = 0.9       # 自動音量補償目標峰值

# --- PC 推論伺服器 ---
PC_SERVER_IP = os.getenv("PC_SERVER_IP", "192.168.31.18")
PC_SERVER_PORT = os.getenv("PC_SERVER_PORT", "5000")
PC_SERVER_URL = f"http://{PC_SERVER_IP}:{PC_SERVER_PORT}/predict"
TIMEOUT_SECONDS = 10

# --- ESP32 致動 (預設關閉，安全測試用) ---
ENABLE_ACTUATOR = False
ESP32_PORT = os.getenv("SERIAL_PORT", "/dev/ttyUSB0")
CLASS_MAPPING = {
    "paper":   {"pitch": 45, "yaw": 0},
    "plastic": {"pitch": 135, "yaw": 0},
    "general": {"pitch": 45, "yaw": 90},
    "metal":   {"pitch": 135, "yaw": 90}
}

# ═══════════════════════════════════════════════════════════════════
# 狀態機狀態常數
# ═══════════════════════════════════════════════════════════════════
STATE_LISTENING = "LISTENING"     # 監聽中，偵測衝擊
STATE_RECORDING = "RECORDING"     # 觸發後，續錄後 1 秒
STATE_PROCESSING = "PROCESSING"   # 處理中 (拍照/推論)，暫停偵測


# ═══════════════════════════════════════════════════════════════════
# 環形緩衝區 (Circular Audio Buffer)
# ═══════════════════════════════════════════════════════════════════

class CircularAudioBuffer:
    """
    固定大小的環形音訊緩衝區。
    持續寫入新資料時，最舊的資料會被自動覆蓋，
    因此隨時可以讀出「最近 N 秒」的音訊。
    """

    def __init__(self, max_samples: int):
        self.buffer = np.zeros(max_samples, dtype=np.float32)
        self.max_samples = max_samples
        self.write_pos = 0
        self.total_written = 0
        self._lock = threading.Lock()

    def write(self, data: np.ndarray):
        """將一段音訊資料寫入環形緩衝區。"""
        n = len(data)
        with self._lock:
            if n >= self.max_samples:
                self.buffer[:] = data[-self.max_samples:]
                self.write_pos = 0
            else:
                end_pos = self.write_pos + n
                if end_pos <= self.max_samples:
                    self.buffer[self.write_pos:end_pos] = data
                else:
                    first_part = self.max_samples - self.write_pos
                    self.buffer[self.write_pos:] = data[:first_part]
                    self.buffer[:n - first_part] = data[first_part:]
                self.write_pos = end_pos % self.max_samples
            self.total_written += n

    def read(self) -> np.ndarray:
        """讀出緩衝區中所有有效的音訊資料 (按時間順序)。"""
        with self._lock:
            if self.total_written >= self.max_samples:
                return np.concatenate([
                    self.buffer[self.write_pos:],
                    self.buffer[:self.write_pos]
                ]).copy()
            else:
                return self.buffer[:self.write_pos].copy()

    def clear(self):
        """清空緩衝區。"""
        with self._lock:
            self.buffer[:] = 0
            self.write_pos = 0
            self.total_written = 0


# ═══════════════════════════════════════════════════════════════════
# 衝擊偵測器 (Impact Detector)
# ═══════════════════════════════════════════════════════════════════

class ImpactDetector:
    """
    基於 RMS 能量突增的衝擊聲偵測器。

    工作原理:
      - 持續追蹤背景噪音的 RMS 滑動平均值。
      - 當某個 chunk 的瞬間 RMS 超過背景 × IMPACT_THRESHOLD 時，
        判定為衝擊事件。
      - 內建冷卻時間機制，避免短時間內重複觸發。
    """

    def __init__(
        self,
        threshold: float = IMPACT_THRESHOLD,
        cooldown: float = COOLDOWN_SEC,
        adapt_rate: float = BG_ADAPT_RATE,
    ):
        self.threshold = threshold
        self.cooldown = cooldown
        self.adapt_rate = adapt_rate
        self.bg_rms = 0.0
        self.last_trigger_time = 0
        self._initialized = False

    def feed(self, chunk: np.ndarray) -> bool:
        """
        餵入一段音訊 chunk，回傳是否偵測到衝擊。

        Args:
            chunk: 單聲道 float32 音訊片段

        Returns:
            True = 偵測到衝擊事件
        """
        rms = float(np.sqrt(np.mean(chunk ** 2)))

        # 初始化背景 RMS
        if not self._initialized:
            if self.bg_rms == 0.0:
                self.bg_rms = rms
            else:
                self.bg_rms = 0.8 * self.bg_rms + 0.2 * rms
            self._initialized = True
            return False

        # 冷卻期間：只更新背景，不觸發
        now = time.time()
        in_cooldown = (now - self.last_trigger_time) < self.cooldown

        # 衝擊判定
        min_rms = 0.005  # 極低音量保底閾值
        effective_threshold = max(self.bg_rms * self.threshold, min_rms)
        is_impact = rms > effective_threshold

        if is_impact and not in_cooldown:
            self.last_trigger_time = now
            return True

        # 非衝擊時，緩慢更新背景 RMS
        if not is_impact:
            self.bg_rms = (1 - self.adapt_rate) * self.bg_rms + self.adapt_rate * rms

        return False

    def get_bg_rms(self) -> float:
        """回傳目前的背景噪音 RMS 值。"""
        return self.bg_rms


# ═══════════════════════════════════════════════════════════════════
# 音量自動補償 (與 audio_processor / collect_audio 一致)
# ═══════════════════════════════════════════════════════════════════

def normalize_audio(audio: np.ndarray, target_peak: float = TARGET_PEAK) -> np.ndarray:
    """對單聲道音訊做自動音量標準化。"""
    current_max = np.max(np.abs(audio))
    if current_max > 0.001:
        gain = target_peak / current_max
        audio = audio * gain
        print(f"  [處理] 音量已自動補償 (原峰值: {current_max:.4f} → 增益: {gain:.2f}x)")
    else:
        print("  [警告] 錄製音量過低，未進行自動音量補償")
    return audio


# ═══════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════

def main():
    picam2 = None
    uart = None

    try:
        # ── 1. 初始化相機 ────────────────────────────────────────
        print("[Init] 正在初始化相機 (Picamera2)...")
        # pyrefly: ignore [missing-import]
        from picamera2 import Picamera2
        picam2 = Picamera2()
        config = picam2.create_preview_configuration(
            main={"format": "RGB888", "size": (640, 480)}
        )
        picam2.configure(config)
        picam2.start()
        print("[Init] 相機啟動成功")

        # ── 2. [選用] 初始化 ESP32 UART ──────────────────────────
        if ENABLE_ACTUATOR:
            print(f"[Init] 正在連接 ESP32 ({ESP32_PORT})...")
            uart = ESP32UART(port=ESP32_PORT)
            if uart.connect():
                print("[Init] ESP32 連接成功")
                time.sleep(2)
            else:
                print("[Warning] ESP32 連接失敗，致動功能將無法使用")
                uart = None
        else:
            print("[Init] ESP32 致動功能已關閉 (ENABLE_ACTUATOR = False)")

        # ── 3. 初始化音訊子系統 ──────────────────────────────────
        pre_samples = int(PRE_TRIGGER_SEC * FS)
        post_samples = int(POST_TRIGGER_SEC * FS)
        chunk_size = int(FS * 0.05)  # 50ms per chunk (偵測解析度)

        # 前觸發環形緩衝區 (持續保留最近 1 秒)
        ring_buffer = CircularAudioBuffer(max_samples=pre_samples)

        # 後觸發線性緩衝區 (觸發後開始填充，滿了就停)
        post_buffer = CircularAudioBuffer(max_samples=post_samples)

        detector = ImpactDetector()

        # 共享狀態 (callback 與主執行緒之間)
        state = {"current": STATE_LISTENING}
        state_lock = threading.Lock()
        trigger_event = threading.Event()
        recording_done = threading.Event()
        post_recorded_samples = {"count": 0}

        def audio_callback(indata, frames, time_info, status):
            """
            sounddevice InputStream callback：
            根據狀態機決定行為。
              LISTENING   → 寫入前觸發環形緩衝區 + 衝擊偵測
              RECORDING   → 寫入後觸發緩衝區
              PROCESSING  → 忽略 (等主執行緒完成)
            """
            if status:
                print(f"  [Audio Status] {status}")

            # 混音成單聲道
            if indata.shape[1] > 1:
                mono = np.mean(indata, axis=1)
            else:
                mono = indata[:, 0]

            with state_lock:
                current_state = state["current"]

            if current_state == STATE_LISTENING:
                # 持續寫入前觸發環形緩衝區
                ring_buffer.write(mono)
                # 衝擊偵測
                if detector.feed(mono):
                    with state_lock:
                        state["current"] = STATE_RECORDING
                        post_recorded_samples["count"] = 0
                        post_buffer.clear()
                    trigger_event.set()

            elif current_state == STATE_RECORDING:
                # 觸發後：將資料寫入後觸發緩衝區
                post_buffer.write(mono)
                post_recorded_samples["count"] += len(mono)
                if post_recorded_samples["count"] >= post_samples:
                    with state_lock:
                        state["current"] = STATE_PROCESSING
                    recording_done.set()

            # STATE_PROCESSING: 什麼都不做

        # ── 4. 啟動持續監聽 ──────────────────────────────────────
        print("\n" + "=" * 56)
        print("  AIOT 衝擊聲觸發測試工具 (Impact Trigger Test)")
        print("  🎤 麥克風持續監聽中...")
        print(f"  衝擊閾值: 背景 RMS × {IMPACT_THRESHOLD}")
        print(f"  音訊範圍: 前 {PRE_TRIGGER_SEC}s + 後 {POST_TRIGGER_SEC}s")
        print(f"  冷卻時間: {COOLDOWN_SEC}s")
        print(f"  致動功能: {'啟用' if ENABLE_ACTUATOR else '關閉'}")
        print("  按下 Ctrl+C 結束程式")
        print("=" * 56)

        stream = sd.InputStream(
            samplerate=FS,
            channels=CHANNELS,
            dtype='float32',
            device=AUDIO_DEV_ID,
            blocksize=chunk_size,
            callback=audio_callback,
        )

        with stream:
            print(f"\n[Listen] 🔊 背景噪音校準中 (請保持安靜 2 秒)...")
            time.sleep(2.0)
            print(f"[Listen] 背景 RMS = {detector.get_bg_rms():.6f}")
            print(f"[Listen] ✅ 就緒！等待衝擊聲...\n")

            while True:
                # 等待觸發事件
                triggered = trigger_event.wait(timeout=0.1)
                if not triggered:
                    continue

                trigger_event.clear()
                trigger_time = time.time()

                # ── 觸發！ ───────────────────────────────────────
                print(f"[⚡ IMPACT] 偵測到衝擊聲！ (背景 RMS: {detector.get_bg_rms():.6f})")

                # 5a. 凍結「前 1 秒」音訊 (callback 已切到 RECORDING)
                pre_audio = ring_buffer.read()

                # 5b. 等待「後 1 秒」錄製完成 (由 callback 自動填充)
                print(f"[Record] 續錄後 {POST_TRIGGER_SEC} 秒中...")
                recording_done.wait(timeout=POST_TRIGGER_SEC + 1.0)
                recording_done.clear()

                post_audio = post_buffer.read()

                # 5c. 合併前後音訊
                full_audio = np.concatenate([pre_audio, post_audio])
                total_sec = len(full_audio) / FS
                print(f"[Audio] 音訊合併完成 (總長: {total_sec:.2f}s, 樣本數: {len(full_audio)})")

                # ── 6. 收音完成，現在拍照 (垃圾已穩定) ────────────
                print("[Camera] 📸 拍照中 (垃圾已穩定)...")
                rgb_frame = picam2.capture_array()
                frame = cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2BGR)
                _, img_encoded = cv2.imencode('.jpg', frame)
                img_bytes = img_encoded.tobytes()
                print("[Camera] 拍照完成")

                # ── 7. 音量補償 + Mel-spectrogram ────────────────
                normalized = normalize_audio(full_audio)
                spec_bytes = audio_to_mel_spectrogram_image(normalized, samplerate=FS)

                # ── 8. 上傳 PC 推論伺服器 ────────────────────────
                files = {
                    "image": ("capture.jpg", img_bytes, "image/jpeg")
                }
                if spec_bytes:
                    files["audio_spec"] = ("spectrogram.jpg", spec_bytes, "image/jpeg")
                    print("[Audio] ✅ 已附帶 Mel-spectrogram 頻譜圖")
                else:
                    print("[Audio] ⚠️ 未能生成頻譜圖")

                print(f"[Network] 上傳至 PC 推論伺服器 ({PC_SERVER_URL})...")

                try:
                    start_time = time.time()
                    resp = requests.post(PC_SERVER_URL, files=files, timeout=TIMEOUT_SECONDS)
                    latency = (time.time() - start_time) * 1000

                    if resp.status_code == 200:
                        res = resp.json()
                        cls = res.get("label", "unknown")
                        conf = res.get("confidence", 0.0)
                        is_gemini = res.get("is_gemini", False)
                        reason = res.get("reasoning", "")

                        print(f"[Result] 🏷️  類別: {cls} | 信心值: {conf:.2f} | Gemini: {is_gemini}")
                        if is_gemini:
                            print(f"         原因: {reason}")
                        print(f"         耗時: {latency:.0f}ms")

                        # ── 9. [選用] ESP32 致動 ─────────────────
                        if uart and cls in CLASS_MAPPING:
                            action = CLASS_MAPPING[cls]
                            print(f"[Action] 傳送指令 → Pitch:{action['pitch']}, Yaw:{action['yaw']}")
                            success, err = uart.send_move_command(action['pitch'], action['yaw'])
                            if success:
                                print("[ESP32] 收到指令 (ACK)，等待動作完成...")
                                resp_uart = uart.read_response(timeout=6.0)
                                if resp_uart and "DONE" in resp_uart:
                                    print("[ESP32] ✅ 移動到位 (DONE)")
                                else:
                                    print(f"[Warning] 未確認動作完成 (回應: {resp_uart})")
                            else:
                                print(f"[Error] 致動指令失敗: {err}")

                            time.sleep(1.5)
                            print("[Action] 傳送歸位指令...")
                            success, err = uart.send_reset_command()
                            if success:
                                resp_uart = uart.read_response(timeout=6.0)
                                if resp_uart and "DONE" in resp_uart:
                                    print("[ESP32] ✅ 歸位完成 (DONE)")
                    else:
                        print(f"[Error] 伺服器錯誤: {resp.status_code} - {resp.text}")

                except Exception as e:
                    print(f"[Error] 連線失敗: {e}")

                # ── 10. 冷卻期 → 清除緩衝區 → 回到監聽 ───────────
                elapsed = time.time() - trigger_time
                remaining_cooldown = max(0, COOLDOWN_SEC - elapsed)
                if remaining_cooldown > 0:
                    print(f"\n[Cooldown] 冷卻中 ({remaining_cooldown:.1f}s)...")
                    time.sleep(remaining_cooldown)

                # 清空前觸發緩衝區，避免殘留舊音訊汙染下一次偵測
                ring_buffer.clear()

                # 切回監聽狀態
                with state_lock:
                    state["current"] = STATE_LISTENING
                print(f"[Listen] ✅ 就緒！等待下一次衝擊聲...\n")

    except KeyboardInterrupt:
        print("\n\n[System] 使用者中斷，正在結束...")
    except ImportError as e:
        print(f"[Error] 缺少必要套件: {e}")
        print("        請確認已安裝 picamera2, sounddevice, opencv-python, requests")
    except Exception as e:
        import traceback
        print(f"[System Error] {e}")
        traceback.print_exc()
    finally:
        if picam2:
            picam2.stop()
            picam2.close()
        if uart:
            uart.disconnect()
        print("[System] 資源已釋放，程式結束。")


if __name__ == "__main__":
    main()
