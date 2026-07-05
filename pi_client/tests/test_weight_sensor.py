# -*- coding: utf-8 -*-
"""
HX711 重量感測器測試腳本 (透過 ESP32 UART)

架構:
  HX711 ──GPIO 17/16──→ ESP32 ──UART──→ Raspberry Pi (本腳本)

ESP32 支援的重量指令:
  GET_WEIGHT  → 回傳 "WEIGHT:{raw_value}"
  TARE        → 回傳 "ACK:TARE_DONE"

使用方式:
  python tests/test_weight_sensor.py

Author: Embedded System Engineer
"""

import os
import sys
import time
import serial
import serial.tools.list_ports
import numpy as np

# 匯入環境變數載入器
try:
    from env_loader import load_env
except ImportError:
    # 支援從 tests 資料夾執行時，導入父目錄的核心模組
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.append(parent_dir)
    from env_loader import load_env

load_env()

# ═══════════════════════════════════════════════════════════════════
# 設定
# ═══════════════════════════════════════════════════════════════════
SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/ttyUSB0")
BAUDRATE = 115200
TIMEOUT = 2.0


# ═══════════════════════════════════════════════════════════════════
# ESP32 重量感測器通訊類別
# ═══════════════════════════════════════════════════════════════════

class WeightSensorUART:
    """
    透過 UART 與 ESP32 通訊，讀取 HX711 重量感測器數據。

    ESP32 韌體已新增兩個指令:
      GET_WEIGHT → 回傳 "WEIGHT:{raw_value}" (取 5 次平均的原始 ADC 值)
      TARE       → 回傳 "ACK:TARE_DONE" (歸零校準)
    """

    def __init__(self, port=SERIAL_PORT, baudrate=BAUDRATE, timeout=TIMEOUT):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.conn = None
        self.tare_value = 0.0       # Pi 端的軟體歸零偏移量
        self.calibration = 1.0      # 原始值 → 公克的換算係數 (需校準)

    def connect(self) -> bool:
        """建立 UART 連線。"""
        target = self.port

        # 如果指定的串口不存在，嘗試自動搜尋
        if not os.path.exists(target):
            print(f"[UART] 指定的 {target} 不存在，搜尋可用串口...")
            ports = list(serial.tools.list_ports.comports())
            usb_ports = [p.device for p in ports
                         if any(k in (p.device + p.description + (p.hwid or "")).upper()
                                for k in ["USB", "ACM", "CH340", "CP210"])]
            if usb_ports:
                target = usb_ports[0]
                print(f"[UART] 找到: {target}")
            else:
                print("[UART] ❌ 未找到任何 USB 串口")
                return False

        try:
            self.conn = serial.Serial(target, self.baudrate, timeout=self.timeout)
            self.port = target
            self.conn.reset_input_buffer()
            print(f"[UART] ✅ 已連線 {target} @ {self.baudrate}bps")

            # 等待 ESP32 啟動 (讀取啟動訊息)
            print("[UART] 等待 ESP32 啟動...")
            time.sleep(2)
            while self.conn.in_waiting:
                line = self.conn.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    print(f"  [ESP32] {line}")
            return True

        except Exception as e:
            print(f"[UART] ❌ 連線失敗: {e}")
            return False

    def disconnect(self):
        """關閉連線。"""
        if self.conn and self.conn.is_open:
            self.conn.close()
            print("[UART] 連線已關閉")

    def _send_command(self, cmd: str, timeout: float = 2.0) -> str:
        """
        發送指令並讀取回應 (過濾 Debug 訊息)。

        Args:
            cmd: 指令字串 (不含換行)
            timeout: 等待回應超時

        Returns:
            回應字串，或 "" 表示超時
        """
        if not self.conn or not self.conn.is_open:
            return ""

        self.conn.reset_input_buffer()
        self.conn.write((cmd + "\n").encode('utf-8'))

        start = time.time()
        while (time.time() - start) < timeout:
            if self.conn.in_waiting:
                line = self.conn.readline().decode('utf-8', errors='ignore').strip()
                if not line:
                    continue
                # 過濾 Debug 訊息
                if line.startswith("[Debug]") or line.startswith("[ESP32]"):
                    continue
                return line
            time.sleep(0.01)

        return ""

    def get_weight_raw(self, retries: int = 3) -> float:
        """
        讀取 HX711 原始值 (含重試機制)。

        HX711 偶爾會回 ERR:HX711_NOT_READY (正在轉換中)，
        自動重試最多 retries 次，每次間隔 0.3 秒。

        Returns:
            float: 原始 ADC 值，或 NaN 表示讀取失敗
        """
        for attempt in range(retries):
            resp = self._send_command("GET_WEIGHT")
            if resp.startswith("WEIGHT:"):
                try:
                    return float(resp.split(":")[1])
                except (ValueError, IndexError):
                    pass
            elif "NOT_READY" in resp:
                # HX711 正在轉換，短暫等待後重試
                if attempt < retries - 1:
                    time.sleep(0.3)
                    continue
            elif resp.startswith("ERR:"):
                print(f"  [Error] {resp}")
            elif resp == "":
                # 超時無回應
                if attempt < retries - 1:
                    time.sleep(0.2)
                    continue

        return float('nan')

    def get_weight_grams(self) -> float:
        """
        讀取重量 (公克，扣除 Pi 端軟體歸零值)。

        Returns:
            float: 重量 (公克)
        """
        raw = self.get_weight_raw()
        if np.isnan(raw):
            return float('nan')
        return (raw - self.tare_value) / self.calibration

    def tare_esp32(self) -> bool:
        """
        發送歸零指令到 ESP32 (硬體歸零)。

        Returns:
            bool: 是否成功
        """
        resp = self._send_command("TARE")
        if "TARE_DONE" in resp:
            self.tare_value = 0.0  # ESP32 已歸零，清除 Pi 端偏移
            return True
        print(f"  [Error] 歸零失敗: {resp}")
        return False

    def tare_software(self, samples=10) -> bool:
        """
        Pi 端軟體歸零 (不動 ESP32，只記錄偏移量)。

        Args:
            samples: 取樣次數

        Returns:
            bool: 是否成功
        """
        readings = []
        for _ in range(samples):
            raw = self.get_weight_raw()
            if not np.isnan(raw):
                readings.append(raw)
            time.sleep(0.15)

        if len(readings) < 3:
            print("  [Error] 取樣失敗次數過多")
            return False

        self.tare_value = float(np.mean(readings))
        std = float(np.std(readings))
        print(f"  [Tare] 偏移量: {self.tare_value:.1f} | σ: {std:.1f}")
        return True


# ═══════════════════════════════════════════════════════════════════
# 測試功能
# ═══════════════════════════════════════════════════════════════════

def test_continuous(sensor: WeightSensorUART):
    """模式 1: 連續即時讀取"""
    print("\n" + "=" * 55)
    print("  📊 連續即時讀取 (按 Ctrl+C 停止)")
    print("=" * 55 + "\n")

    try:
        count = 0
        fail_streak = 0  # 連續失敗計數
        while True:
            raw = sensor.get_weight_raw()
            count += 1

            if np.isnan(raw):
                fail_streak += 1
                print(f"  [{count:4d}] ❌ 讀取失敗 (連續 {fail_streak} 次)")
                if fail_streak >= 5:
                    print("\n  ⚠️ 連續 5 次失敗，可能原因:")
                    print("     - HX711 接線鬆脫")
                    print("     - ESP32 韌體未包含 GET_WEIGHT 指令")
                    print("     - 串口被其他程式佔用")
                    fail_streak = 0  # 重置，避免重複提示
            else:
                fail_streak = 0
                grams = (raw - sensor.tare_value) / sensor.calibration
                bar_len = max(0, min(40, int(abs(grams) / 2)))
                bar = "█" * bar_len
                sign = "+" if grams >= 0 else "-"
                print(f"  [{count:4d}] RAW: {raw:10.0f} | {sign}{abs(grams):7.1f}g | {bar}")

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n  已停止\n")


def test_tare(sensor: WeightSensorUART):
    """模式 2: 歸零校準"""
    print("\n" + "=" * 55)
    print("  ⚖️ 歸零校準")
    print("=" * 55)

    print("\n  選擇歸零方式:")
    print("  1. ESP32 硬體歸零 (建議，會重設 HX711 零點)")
    print("  2. Pi 軟體歸零 (不動 ESP32，只記錄偏移)")
    choice = input("  請選擇 (1/2): ").strip()

    if choice == '1':
        input("  請確保秤上沒有東西，按 Enter 開始...")
        if sensor.tare_esp32():
            print("  ✅ ESP32 硬體歸零完成")
        else:
            print("  ❌ 歸零失敗")
    elif choice == '2':
        input("  請確保秤上沒有東西，按 Enter 開始...")
        print("  取樣中...")
        if sensor.tare_software(samples=15):
            print("  ✅ 軟體歸零完成")
        else:
            print("  ❌ 歸零失敗")
    print()


def test_calibration(sensor: WeightSensorUART):
    """模式 3: 砝碼校準"""
    print("\n" + "=" * 55)
    print("  🔧 砝碼校準 (計算 calibration factor)")
    print("=" * 55)

    # Step 1: 歸零
    input("\n  [Step 1] 清空秤面，按 Enter 歸零...")
    sensor.tare_esp32()
    time.sleep(0.5)
    sensor.tare_software(samples=10)

    # Step 2: 放上砝碼
    try:
        known_weight = float(input("\n  [Step 2] 放上砝碼，輸入已知重量 (公克): "))
    except ValueError:
        print("  ❌ 無效輸入")
        return

    if known_weight <= 0:
        print("  ❌ 重量必須 > 0")
        return

    input(f"  [Step 3] 確認 {known_weight}g 砝碼已放好，按 Enter...")

    # Step 3: 讀取
    print("  取樣中 (20 次)...")
    readings = []
    for _ in range(20):
        raw = sensor.get_weight_raw()
        if not np.isnan(raw):
            readings.append(raw)
        time.sleep(0.15)

    if len(readings) < 10:
        print("  ❌ 有效讀數過少，請檢查接線")
        return

    raw_avg = float(np.mean(readings))
    raw_diff = raw_avg - sensor.tare_value
    new_factor = raw_diff / known_weight

    print(f"\n  ════════ 校準結果 ════════")
    print(f"  空秤基準值:     {sensor.tare_value:.0f}")
    print(f"  砝碼原始讀數:   {raw_avg:.0f}")
    print(f"  原始值變化量:   {raw_diff:.0f}")
    print(f"  已知重量:       {known_weight:.1f}g")
    print(f"  ─────────────────────────")
    print(f"  ★ 校準係數:     {new_factor:.2f}")
    print(f"  ════════════════════════\n")

    apply = input("  套用? (y/n): ").strip().lower()
    if apply == 'y':
        sensor.calibration = new_factor
        print(f"  ✅ 已套用！請記下此數值: {new_factor:.2f}")
    print()


def test_stability(sensor: WeightSensorUART):
    """模式 4: 穩定度測試"""
    print("\n" + "=" * 55)
    print("  📈 穩定度測試 (50 次取樣)")
    print("=" * 55)

    input("  按 Enter 開始...")
    print("  取樣中:", end="", flush=True)

    samples = []
    for i in range(50):
        g = sensor.get_weight_grams()
        if not np.isnan(g):
            samples.append(g)
        if (i + 1) % 10 == 0:
            print(f" {i+1}", end="", flush=True)
        time.sleep(0.15)

    if len(samples) < 10:
        print("\n  ❌ 有效讀數過少")
        return

    samples = np.array(samples)
    print(f"\n\n  ════════ 統計結果 ({len(samples)} 筆) ════════")
    print(f"  平均值:   {np.mean(samples):+.1f}g")
    print(f"  標準差:   {np.std(samples):.2f}g")
    print(f"  最大值:   {np.max(samples):+.1f}g")
    print(f"  最小值:   {np.min(samples):+.1f}g")
    print(f"  峰對峰值: {np.ptp(samples):.1f}g")
    print(f"  ══════════════════════════════")

    if np.std(samples) < 0.5:
        print("  ✅ 穩定性: 優秀")
    elif np.std(samples) < 2.0:
        print("  ⚠️ 穩定性: 普通")
    else:
        print("  ❌ 穩定性: 差，檢查接線/供電")
    print()


def test_trigger_sim(sensor: WeightSensorUART):
    """模式 5: 觸發模擬 (偵測重量突增)"""
    print("\n" + "=" * 55)
    print("  🎯 觸發偵測模擬")
    print("  監測重量變化，超過門檻時顯示觸發")
    print("  按 Ctrl+C 停止")
    print("=" * 55)

    try:
        threshold = float(input("\n  輸入觸發門檻 (公克, 建議 3~10): ") or "5")
    except ValueError:
        threshold = 5.0

    print(f"\n  門檻: {threshold:.1f}g | 監測中...\n")

    try:
        while True:
            grams = sensor.get_weight_grams()
            if np.isnan(grams):
                time.sleep(0.5)
                continue

            if abs(grams) > threshold:
                print(f"  ⚡ 觸發！重量: {grams:+.1f}g (門檻: {threshold}g)")
            else:
                print(f"  ── 待機 | {grams:+.1f}g", end="\r")

            time.sleep(0.3)

    except KeyboardInterrupt:
        print("\n\n  已停止\n")


# ═══════════════════════════════════════════════════════════════════
# 主程式
# ═══════════════════════════════════════════════════════════════════

def main():
    print("\n" + "=" * 55)
    print("  ⚖️ HX711 重量感測器測試工具 (via ESP32 UART)")
    print("=" * 55)

    sensor = WeightSensorUART()

    if not sensor.connect():
        print("\n[Error] 無法連線 ESP32，請確認:")
        print("  1. ESP32 已接上 USB")
        print("  2. 韌體已燒錄 (含 GET_WEIGHT 指令)")
        print(f"  3. .env 中 SERIAL_PORT 設定正確 (目前: {SERIAL_PORT})")
        sys.exit(1)

    # 初始軟體歸零
    print("\n[Init] 初始歸零...")
    sensor.tare_software(samples=10)

    while True:
        print("\n  ┌────────────────────────────────────┐")
        print("  │  選擇測試模式:                       │")
        print("  │  1. 連續即時讀取                      │")
        print("  │  2. 歸零校準 (Tare)                  │")
        print("  │  3. 砝碼校準 (計算 Factor)            │")
        print("  │  4. 穩定度測試 (統計分析)              │")
        print("  │  5. 觸發偵測模擬                      │")
        print("  │  q. 離開                             │")
        print("  └────────────────────────────────────┘")

        choice = input("\n  請選擇 (1-5/q): ").strip().lower()

        if choice == '1':
            test_continuous(sensor)
        elif choice == '2':
            test_tare(sensor)
        elif choice == '3':
            test_calibration(sensor)
        elif choice == '4':
            test_stability(sensor)
        elif choice == '5':
            test_trigger_sim(sensor)
        elif choice == 'q':
            break

    sensor.disconnect()
    print("\n[System] 測試結束。")


if __name__ == "__main__":
    main()
