# -*- coding: utf-8 -*-
"""
AIOT 智慧垃圾桶 - 樹莓派網路與 Tailscale 管理助手
"""
import os
import sys
import subprocess
import argparse
import socket

# 避免 Windows 終端機 (CP950) 列印 Emoji/UTF-8 字元時發生編碼報錯
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

def get_env_path():
    """獲取 .env 檔案的絕對路徑"""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_dir, ".env")

def get_network_status():
    """
    獲取當前網路連線狀態，包含 SSID、本機 IP 與 Tailscale IP
    """
    status = {
        "os": sys.platform,
        "is_linux": sys.platform.startswith("linux"),
        "ssid": "未連接 Wi-Fi / 未知",
        "local_ips": [],
        "tailscale_ip": "未啟用 / 未取得",
        "error": None
    }
    
    # 1. 取得本機所有 IP 地址
    try:
        # 透過連接外部 DNS 來獲取主要外網 IP (非 127.0.0.1)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        primary_ip = s.getsockname()[0]
        s.close()
        status["local_ips"].append(primary_ip)
    except Exception:
        pass

    # 備用方案：如果上面抓不到，在 Linux 下跑 hostname -I
    if status["is_linux"]:
        try:
            ips = subprocess.check_output(["hostname", "-I"]).decode("utf-8").strip().split()
            for ip in ips:
                if ip not in status["local_ips"]:
                    status["local_ips"].append(ip)
        except Exception:
            pass
    else:
        # Windows/Mac 測試環境，增加 Mock 或本機 IP
        try:
            hostname = socket.gethostname()
            ips = socket.gethostbyname_ex(hostname)[2]
            for ip in ips:
                if not ip.startswith("127.") and ip not in status["local_ips"]:
                    status["local_ips"].append(ip)
        except Exception:
            pass

    # 2. 獲取當前連線 Wi-Fi SSID 與 Tailscale IP
    if status["is_linux"]:
        # 2a. Wi-Fi SSID (Bullseye - iwgetid, Bookworm - nmcli)
        try:
            # 優先使用 iwgetid (Bullseye)
            ssid = subprocess.check_output(["iwgetid", "-r"]).decode("utf-8").strip()
            if ssid:
                status["ssid"] = ssid
        except Exception:
            # 備用使用 nmcli (Bookworm)
            try:
                ssid = subprocess.check_output(
                    "nmcli -t -f active,ssid dev wifi | grep '^yes:' | cut -d':' -f2",
                    shell=True
                ).decode("utf-8").strip()
                if ssid:
                    status["ssid"] = ssid
            except Exception:
                pass

        # 2b. Tailscale IP
        try:
            ts_ip = subprocess.check_output(["tailscale", "ip", "-4"]).decode("utf-8").strip()
            if ts_ip:
                status["tailscale_ip"] = ts_ip
                # 從 local_ips 移除 tailscale_ip 以免混淆
                if ts_ip in status["local_ips"]:
                    status["local_ips"].remove(ts_ip)
        except Exception:
            # 嘗試讀取網卡介面尾碼
            try:
                ip_addr = subprocess.check_output(["ip", "addr", "show", "tailscale0"]).decode("utf-8")
                for line in ip_addr.split("\n"):
                    if "inet " in line:
                        ts_ip = line.strip().split()[1].split("/")[0]
                        status["tailscale_ip"] = ts_ip
                        if ts_ip in status["local_ips"]:
                            status["local_ips"].remove(ts_ip)
                        break
            except Exception:
                pass
    else:
        # Windows / Mac 模擬測試環境
        status["ssid"] = "模擬 Wi-Fi (開發測試環境)"
        status["tailscale_ip"] = "100.115.12.34 (模擬)"

    return status

def add_wifi(ssid, password):
    """
    登錄新的 Wi-Fi 連線 (自動適應 Bookworm/nmcli 與 Bullseye/wpa_supplicant)
    """
    is_linux = sys.platform.startswith("linux")
    if not is_linux:
        return False, "新增 Wi-Fi 功能僅支援於 Raspberry Pi (Linux) 實機上運作！"

    # 1. 檢查是否安裝 NetworkManager (nmcli) - Raspberry Pi OS 12 (Bookworm) 預設
    has_nmcli = False
    try:
        subprocess.check_call(["which", "nmcli"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        has_nmcli = True
    except Exception:
        pass

    if has_nmcli:
        print(f"[Network] 檢測到 NetworkManager，使用 nmcli 進行 Wi-Fi 新增...")
        cmd = ["sudo", "nmcli", "dev", "wifi", "connect", ssid, "password", password]
        try:
            # 設定 15 秒超時防止掛起
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=15).decode("utf-8")
            return True, f"成功透過 nmcli 連接並儲存網路！\n系統訊息：{output}"
        except subprocess.CalledProcessError as e:
            return False, f"透過 nmcli 新增網路失敗：{e.output.decode('utf-8')}"
        except subprocess.TimeoutExpired:
            return False, "透過 nmcli 連線逾時，但該 Wi-Fi 設定可能已儲存成功。請確認密碼或熱點是否開啟。"

    # 2. 備用方案：編輯 wpa_supplicant.conf - Raspberry Pi OS 11 (Bullseye) 或更舊版
    wpa_path = "/etc/wpa_supplicant/wpa_supplicant.conf"
    if os.path.exists(wpa_path):
        print(f"[Network] 檢測到 wpa_supplicant，將直接編輯 {wpa_path}...")
        
        # 構建新的 network block 內容
        new_network = (
            f"\nnetwork={{\n"
            f'    ssid="{ssid}"\n'
            f'    psk="{password}"\n'
            f"    priority=5\n"
            f"}}\n"
        )
        
        try:
            # 讀取現有內容，防範重複寫入
            with open(wpa_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            if f'ssid="{ssid}"' in content:
                # 簡單替換或提示已存在
                return True, f"Wi-Fi「{ssid}」先前已於 wpa_supplicant.conf 中配置過！"
            
            # 使用 sudo 權限安全寫入（透過 Python 直接寫入如果沒權限，需要用 sudo tee）
            # 我們這裡用 shell 寫入以解決權限問題
            cmd = f'echo {repr(new_network)} | sudo tee -a {wpa_path}'
            subprocess.check_call(cmd, shell=True)
            
            # 重新加載配置
            try:
                subprocess.check_call(["sudo", "wpa_cli", "-i", "wlan0", "reconfigure"])
            except Exception as reconfig_err:
                print(f"[Warning] wpa_cli reconfigure 失敗: {reconfig_err}，請重啟網路服務。")
                
            return True, f"成功寫入 {wpa_path} 並發送重新配置指令！"
        except subprocess.CalledProcessError as e:
            return False, f"寫入 wpa_supplicant 失敗，需要 sudo 權限：{str(e)}"
        except Exception as e:
            return False, f"寫入 wpa_supplicant.conf 發生非預期錯誤：{str(e)}"

    return False, "系統中未找到 nmcli，亦無 /etc/wpa_supplicant/wpa_supplicant.conf 檔案，無法配置 Wi-Fi。"

def update_env_pc_ip(new_ip):
    """
    修改 .env 檔案中的 PC_SERVER_IP，保留其他參數與註解
    """
    env_file = get_env_path()
    if not os.path.exists(env_file):
        # 如果檔案不存在，則建立預設檔案
        try:
            with open(env_file, "w", encoding="utf-8") as f:
                f.write(
                    "# ==================== PC 推論伺服器連線設定 ====================\n"
                    f"PC_SERVER_IP={new_ip}\n"
                    "PC_SERVER_PORT=5000\n"
                    "\n"
                    "# ==================== ESP32 UART 序列埠通訊設定 ====================\n"
                    "SERIAL_PORT=/dev/ttyUSB0\n"
                )
            return True, "成功建立並更新 .env 檔案！"
        except Exception as e:
            return False, f"建立 .env 失敗: {str(e)}"

    try:
        with open(env_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        new_lines = []
        updated = False
        
        for line in lines:
            stripped = line.strip()
            # 匹配 PC_SERVER_IP
            if stripped.startswith("PC_SERVER_IP=") or stripped.startswith("PC_SERVER_IP ="):
                # 保留可能存在的行尾註解
                parts = line.split("#", 1)
                comment = f"  # {parts[1].strip()}" if len(parts) > 1 else ""
                new_lines.append(f"PC_SERVER_IP={new_ip}{comment}\n")
                updated = True
            else:
                new_lines.append(line)
        
        # 若在檔案中沒找到該變數，則直接補在最後
        if not updated:
            new_lines.append(f"\nPC_SERVER_IP={new_ip}\n")

        with open(env_file, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        return True, f"成功更新 .env 中的 PC 伺服器 IP 為：{new_ip}"
    except Exception as e:
        return False, f"更新 .env 檔案出錯: {str(e)}"

def get_current_env_server():
    """獲取當前 .env 中的 PC Server IP 與 Port"""
    env_file = get_env_path()
    ip = "192.168.31.18"  # 預設值
    port = "5000"
    
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("PC_SERVER_IP=") or stripped.startswith("PC_SERVER_IP ="):
                        val = stripped.split("=", 1)[1].split("#", 1)[0].strip()
                        # 去除引號
                        ip = val.strip("'\"")
                    elif stripped.startswith("PC_SERVER_PORT=") or stripped.startswith("PC_SERVER_PORT ="):
                        val = stripped.split("=", 1)[1].split("#", 1)[0].strip()
                        port = val.strip("'\"")
        except Exception:
            pass
            
    return ip, port

def update_config_calibration_factor(new_factor):
    """
    修改 config.py 檔案中的 WEIGHT_CALIBRATION_FACTOR，保留其他參數與註解
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    config_file = os.path.join(base_dir, "config.py")
    if not os.path.exists(config_file):
        return False, "找不到 config.py 檔案！"

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        new_lines = []
        updated = False
        
        for line in lines:
            stripped = line.strip()
            # 匹配 WEIGHT_CALIBRATION_FACTOR
            if stripped.startswith("WEIGHT_CALIBRATION_FACTOR=") or stripped.startswith("WEIGHT_CALIBRATION_FACTOR ="):
                # 保留可能存在的行尾註解
                parts = line.split("#", 1)
                comment = f"  # {parts[1].strip()}" if len(parts) > 1 else ""
                new_lines.append(f"WEIGHT_CALIBRATION_FACTOR = {new_factor}{comment}\n")
                updated = True
            else:
                new_lines.append(line)
        
        if not updated:
            new_lines.append(f"\nWEIGHT_CALIBRATION_FACTOR = {new_factor}\n")

        with open(config_file, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        return True, f"成功更新 config.py 中的重量校準係數為：{new_factor}"
    except Exception as e:
        return False, f"更新 config.py 檔案出錯: {str(e)}"

def get_current_env_actuator(default=True):
    """獲取當前 .env 中的 ENABLE_ACTUATOR"""
    env_file = get_env_path()
    enabled = default
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("ENABLE_ACTUATOR=") or stripped.startswith("ENABLE_ACTUATOR ="):
                        val = stripped.split("=", 1)[1].split("#", 1)[0].strip()
                        enabled = val.strip("'\"").lower() == "true"
        except Exception:
            pass
    return enabled

def update_env_enable_actuator(enabled: bool):
    """
    修改 .env 檔案中的 ENABLE_ACTUATOR，保留其他參數與註解
    """
    env_file = get_env_path()
    val = "True" if enabled else "False"
    if not os.path.exists(env_file):
        try:
            with open(env_file, "w", encoding="utf-8") as f:
                f.write(
                    "# ==================== ESP32 舵機致動啟用設定 ====================\n"
                    f"ENABLE_ACTUATOR={val}\n"
                )
            return True, "成功建立並更新 .env 檔案！"
        except Exception as e:
            return False, f"建立 .env 失敗: {str(e)}"

    try:
        with open(env_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        new_lines = []
        updated = False
        
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("ENABLE_ACTUATOR=") or stripped.startswith("ENABLE_ACTUATOR ="):
                parts = line.split("#", 1)
                comment = f"  # {parts[1].strip()}" if len(parts) > 1 else ""
                new_lines.append(f"ENABLE_ACTUATOR={val}{comment}\n")
                updated = True
            else:
                new_lines.append(line)
        
        if not updated:
            new_lines.append(f"\nENABLE_ACTUATOR={val}\n")

        with open(env_file, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        return True, f"成功更新 .env 中的舵機啟用狀態為：{val}"
    except Exception as e:
        return False, f"更新 .env 檔案出錯: {str(e)}"

def get_current_env_pitch_neutral():
    """獲取當前 .env 中的 PITCH_NEUTRAL"""
    env_file = get_env_path()
    pitch = 98  # 預設值
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("PITCH_NEUTRAL=") or stripped.startswith("PITCH_NEUTRAL ="):
                        val = stripped.split("=", 1)[1].split("#", 1)[0].strip()
                        pitch = int(val.strip("'\""))
        except Exception:
            pass
    return pitch

def update_env_pitch_neutral(new_pitch: int):
    """
    修改 .env 檔案中的 PITCH_NEUTRAL，保留其他參數與註解
    """
    env_file = get_env_path()
    if not os.path.exists(env_file):
        try:
            with open(env_file, "w", encoding="utf-8") as f:
                f.write(
                    "# ==================== ESP32 舵機水平校準設定 ====================\n"
                    f"PITCH_NEUTRAL={new_pitch}\n"
                )
            return True, "成功建立並更新 .env 檔案！"
        except Exception as e:
            return False, f"建立 .env 失敗: {str(e)}"

    try:
        with open(env_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        new_lines = []
        updated = False
        
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("PITCH_NEUTRAL=") or stripped.startswith("PITCH_NEUTRAL ="):
                parts = line.split("#", 1)
                comment = f"  # {parts[1].strip()}" if len(parts) > 1 else ""
                new_lines.append(f"PITCH_NEUTRAL={new_pitch}{comment}\n")
                updated = True
            else:
                new_lines.append(line)
        
        if not updated:
            new_lines.append(f"\nPITCH_NEUTRAL={new_pitch}\n")

        with open(env_file, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        return True, f"成功更新 .env 中的 Pitch 中立角為：{new_pitch}"
    except Exception as e:
        return False, f"更新 .env 檔案出錯: {str(e)}"

def main():
    parser = argparse.ArgumentParser(description="AIOT 智慧垃圾桶 - 樹莓派網路與 Tailscale 管理助手")
    subparsers = parser.add_subparsers(dest="command", help="子指令功能")

    # status 指令
    subparsers.add_parser("status", help="獲取當前網路、IP 與 Tailscale 狀態")

    # add-wifi 指令
    wifi_parser = subparsers.add_parser("add-wifi", help="登錄新的 Wi-Fi 連線")
    wifi_parser.add_argument("ssid", type=str, help="Wi-Fi SSID (名稱)")
    wifi_parser.add_argument("password", type=str, help="Wi-Fi 密碼")

    # set-server 指令
    server_parser = subparsers.add_parser("set-server", help="修改 PC 推論伺服器 IP 設定")
    server_parser.add_argument("ip", type=str, help="PC 伺服器 IP (推薦使用 Tailscale 固定 IP)")

    args = parser.parse_args()

    if args.command == "status":
        status = get_network_status()
        ip, port = get_current_env_server()
        print("\n=== 📡 樹莓派網路狀態診斷 ===")
        print(f"操作系統環境: {status['os']}")
        print(f"當前連線 Wi-Fi: {status['ssid']}")
        print(f"本機區域網 IP: {', '.join(status['local_ips']) if status['local_ips'] else '無 IP 連線'}")
        print(f"Tailscale 固定 IP: {status['tailscale_ip']}")
        print(f"設定的 PC 推論端點: http://{ip}:{port}/predict")
        print("===============================\n")

    elif args.command == "add-wifi":
        print(f"\n[Network] 正在嘗試為樹莓派登錄 Wi-Fi 網路: {args.ssid}...")
        success, msg = add_wifi(args.ssid, args.password)
        if success:
            print(f"✅ 成功！{msg}\n")
        else:
            print(f"❌ 失敗：{msg}\n")

    elif args.command == "set-server":
        success, msg = update_env_pc_ip(args.ip)
        if success:
            print(f"\n✅ 設定成功！{msg}\n")
        else:
            print(f"\n❌ 設定失敗：{msg}\n")
            
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
