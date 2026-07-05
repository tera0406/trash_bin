import os

def load_env(env_path=None):
    """
    無縫載入 .env 檔案為環境變數。
    優先使用 python-dotenv，若未安裝則使用純 Python 簡易語法分析器載入 .env。
    """
    if env_path is None:
        # 優先尋找當前檔案所在目錄的 .env 或主執行目錄的 .env
        base_dir = os.path.dirname(os.path.abspath(__file__))
        env_path = os.path.join(base_dir, ".env")
        if not os.path.exists(env_path):
            env_path = ".env"
            
    if not os.path.exists(env_path):
        return False
        
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path, override=True)
        return True
    except ImportError:
        # 純 Python 簡易解析器
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, val = line.split("=", 1)
                        # 移除前後空格
                        key = key.strip()
                        val = val.strip()
                        # 移除外層引號
                        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                            val = val[1:-1]
                        os.environ[key] = val
            return True
        except Exception as e:
            print(f"[EnvLoader] 警告: 載入 {env_path} 失敗 - {e}")
            return False
