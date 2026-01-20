import requests
import base64
import json
import os
import time

# 設定目標伺服器 (Level 1 PC)
SERVER_URL = "http://localhost:5000/predict"

def get_dummy_data():
    """模擬讀取影像與音訊檔案"""
    
    # 嘗試讀取專案中的測試圖片，如果沒有則生成全黑圖片
    image_data = None
    if os.path.exists("data/test_image.jpg"):
        with open("data/test_image.jpg", "rb") as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')
    else:
        # 建立一個簡單的 224x224 全黑圖片 (PNG 格式的 base64)
        # 這裡為了簡化，直接使用一個極短的無效 base64 或者你可以用 PIL 生成
        # 為避免 PIL 依賴，我們假設已有圖片或傳送空值測試錯誤處理
        print("未找到測試圖片，將嘗試使用 dummy base64 (可能導致 vision error)")
        image_data = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=" # 1x1 pixel

    # 模擬音訊資料 (Optional)
    audio_data = None
    # if os.path.exists("data/test_audio.wav"):
    #     with open("data/test_audio.wav", "rb") as f:
    #         audio_data = base64.b64encode(f.read()).decode('utf-8')

    return image_data, audio_data

def simulate_pi_request():
    print(f"正在連接伺服器: {SERVER_URL}")
    
    image_b64, audio_b64 = get_dummy_data()
    
    payload = {
        "image": image_b64,
        "audio": audio_b64,
        "timestamp": time.time()
    }
    
    try:
        start_time = time.time()
        response = requests.post(SERVER_URL, json=payload, timeout=30)
        duration = time.time() - start_time
        
        print(f"請求耗時: {duration:.2f} 秒")
        print(f"HTTP 狀態碼: {response.status_code}")
        
        if response.status_code == 200:
            print("\n----- 伺服器回傳 (JSON) -----")
            print(json.dumps(response.json(), indent=2, ensure_ascii=False))
            print("-----------------------------")
        else:
            print(f"錯誤回應: {response.text}")
            
    except Exception as e:
        print(f"連線失敗: {e}")
        print("請確認 app.py 是否已啟動")

if __name__ == "__main__":
    simulate_pi_request()
