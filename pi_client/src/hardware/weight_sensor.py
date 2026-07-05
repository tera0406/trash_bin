# -*- coding: utf-8 -*-
"""
AIOT 智慧垃圾桶 - 重量感測器模組 (透過 ESP32 UART 通訊)
"""
import os
import sys
import time
import numpy as np

# 匯入系統設定
try:
    from config import WEIGHT_TARE_SAMPLES, WEIGHT_CALIBRATION_FACTOR
except ImportError:
    parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    from config import WEIGHT_TARE_SAMPLES, WEIGHT_CALIBRATION_FACTOR



class WeightSensor:
    """
    透過 ESP32 UART 讀取 HX711 重量感測器。

    HX711 直接接在 ESP32 上 (DOUT=GPIO17, SCK=GPIO16)，
    ESP32 韌體負責底層 ADC 讀取，Pi 端透過 UART 下達指令查詢：

    指令格式:
      GET_WEIGHT\n → ESP32 回傳 "WEIGHT:{raw_value}"
      TARE\n       → ESP32 回傳 "ACK:TARE_DONE"

    在 PC 開發環境 (無串口) 時自動切換為 Mock 模式。
    """

    def __init__(self, uart_conn=None):
        """
        Args:
            uart_conn: 已建立的 serial.Serial 連線物件。
                       若為 None，嘗試自動連線；若連線失敗則切換 Mock 模式。
        """
        self.conn = uart_conn
        self.mock = False
        self.tare_value = 0.0           # Pi 端軟體歸零偏移量
        self.calibration_factor = WEIGHT_CALIBRATION_FACTOR  # 原始值 → 公克 (已用 108.5g 砝碼校準)


        # 若沒有傳入連線，嘗試自動建立
        if self.conn is None:
            try:
                import serial as pyserial
                port = os.getenv("SERIAL_PORT", "/dev/ttyUSB0")
                if os.path.exists(port):
                    self.conn = pyserial.Serial(port, 115200, timeout=1.5)
                    time.sleep(0.5)
                    self.conn.reset_input_buffer()
                    print(f"  [Weight] UART 連線成功 ({port})")
                else:
                    raise FileNotFoundError(f"{port} 不存在")
            except Exception as e:
                print(f"  [Weight] ⚠️ UART 不可用 ({e})，切換 Mock 模式")
                self.mock = True

    def _send_weight_cmd(self, cmd: str, timeout: float = 2.0) -> str:
        """
        透過 UART 發送指令給 ESP32 及讀取回應。
        過濾 [Debug] 和 [ESP32] 開頭的訊息，只回傳協定回應。
        """
        if self.mock or not self.conn or not self.conn.is_open:
            return ""

        try:
            self.conn.reset_input_buffer()
            self.conn.write((cmd + "\n").encode('utf-8'))

            start = time.time()
            while (time.time() - start) < timeout:
                if self.conn.in_waiting:
                    line = self.conn.readline().decode('utf-8', errors='ignore').strip()
                    if not line:
                        continue
                    if line.startswith("EVENT:"):
                        # 攔截並暫存主動上報事件，避免在此遺失
                        try:
                            from src.hardware.esp32_uart import _shared_pending_events
                            _shared_pending_events.append(line)
                        except:
                            pass
                        continue
                    if line.startswith("[Debug]") or line.startswith("[ESP32]"):
                        continue
                    return line
                time.sleep(0.01)
        except Exception as e:
            print(f"  [Weight] UART 讀取錯誤: {e}")

        return ""

    def tare(self, samples: int = WEIGHT_TARE_SAMPLES):
        """
        歸零校準 (Tare)。

        物理意義:
          讓 ESP32 端的 HX711 重新校準零點，
          同時也在 Pi 端做軟體歸零 (多次取平均消除雜訊)。
        """
        if self.mock:
            self.tare_value = 0.0
            print(f"  [Mock] Tare 完成")
            return

        # 先嘗試 ESP32 硬體歸零
        resp = self._send_weight_cmd("TARE")
        if "TARE_DONE" in resp:
            print("  [Weight] ESP32 硬體歸零完成")

        # 再做 Pi 端軟體歸零 (取多次平均)
        readings = []
        for _ in range(samples):
            raw = self._read_raw()
            if not np.isnan(raw):
                readings.append(raw)
            time.sleep(0.15)

        if readings:
            self.tare_value = float(np.mean(readings))
            std = float(np.std(readings))
            print(f"  [Weight] Pi 軟體歸零完成 (偏移: {self.tare_value:.0f}, σ: {std:.1f})")

    def _read_raw(self) -> float:
        """讀取 HX711 原始 ADC 值 (透過 ESP32)。"""
        if self.mock:
            # Mock: 95% 雜訊, 5% 模擬投入
            if np.random.random() < 0.05:
                return float(np.random.uniform(500, 2500))
            return float(np.random.normal(0, 15))

        resp = self._send_weight_cmd("GET_WEIGHT")
        if resp.startswith("WEIGHT:"):
            try:
                return float(resp.split(":")[1])
            except (ValueError, IndexError):
                pass
        return float('nan')

    def read_grams(self) -> float:
        """
        讀取當前重量 (相對基準的公克數)。

        物理意義:
          回傳值 = (ESP32 回傳的原始值 - Pi 端歸零偏移) / 校準係數
          正值 = 桶內重量增加了
          ~0   = 無變化

        Returns:
          float: 重量變化值 (公克)
        """
        raw = self._read_raw()
        if np.isnan(raw):
            return 0.0  # 讀取失敗時回傳 0，避免觸發誤判
        return (raw - self.tare_value) / self.calibration_factor
