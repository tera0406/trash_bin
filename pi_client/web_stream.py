import io
import sys
import time
from flask import Flask, Response
from picamera2 import Picamera2

# 匯入系統相機防過曝設定
try:
    from config import (
        CAMERA_EXPOSURE_VALUE,
        CAMERA_METERING_MODE,
        CAMERA_CONTRAST,
        CAMERA_BRIGHTNESS
    )
except ImportError:
    CAMERA_EXPOSURE_VALUE = -1.0
    CAMERA_METERING_MODE = "spot"
    CAMERA_CONTRAST = 1.0
    CAMERA_BRIGHTNESS = 0.0

def apply_camera_settings(picam2):
    """根據系統設定，套用 Picamera2 相機參數 (如曝光補償、測光模式等) 以防止過曝"""
    try:
        from libcamera import controls
        control_dict = {}
        
        # 1. 曝光補償 (Exposure Value)
        control_dict["ExposureValue"] = CAMERA_EXPOSURE_VALUE
        
        # 2. 測光模式 (Metering Mode)
        mode = CAMERA_METERING_MODE.lower().strip()
        if mode == "spot":
            control_dict["AeMeteringMode"] = controls.AeMeteringModeEnum.MeteringSpot
        elif mode in ("centre-weighted", "center-weighted"):
            control_dict["AeMeteringMode"] = controls.AeMeteringModeEnum.MeteringCentreWeighted
        elif mode == "matrix":
            control_dict["AeMeteringMode"] = controls.AeMeteringModeEnum.MeteringMatrix
            
        # 3. 對比度
        control_dict["Contrast"] = CAMERA_CONTRAST
        
        # 4. 亮度
        control_dict["Brightness"] = CAMERA_BRIGHTNESS
        
        print(f"[Camera Stream] 正在套用防過曝相機參數: {control_dict}")
        picam2.set_controls(control_dict)
    except ImportError:
        print("[Camera Stream] [Warning] 無法載入 libcamera.controls，跳過測光與曝光參數設定 (僅在 Raspberry Pi 環境支援)")
    except Exception as e:
        print(f"[Camera Stream] [Warning] 套用相機參數失敗: {e}")

app = Flask(__name__)

# 初始化 Picamera2
try:
    picam2 = Picamera2()
    # 配置相機：設定解析度
    # 解析度越高，延遲可能越大，建議 640x480 或 1280x720
    config = picam2.create_video_configuration(main={"size": (640, 480)})
    picam2.configure(config)
    apply_camera_settings(picam2)
    picam2.start()
except RuntimeError as e:
    print("[ERROR] Unable to initialize Picamera2:", e)
    print("[HINT] The camera device may already be in use by another process.")
    print("       Close other camera applications or run: sudo fuser -k /dev/video0")
    sys.exit(1)

def generate_frames():
    while True:
        # 建立一個記憶體緩衝區來存放 JPEG
        stream = io.BytesIO()
        
        # 捕捉單幀影像到緩衝區
        picam2.capture_file(stream, format="jpeg")
        
        frame = stream.getvalue()
        
        # multipart 格式傳輸
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        
        # 稍微縮短循環，避免過度占用 CPU
        time.sleep(0.03)

@app.route('/')
def index():
    return "<h1>Libcamera Live Stream</h1><img src='/video_feed' width='100%'>"

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == "__main__":
    # 監聽 0.0.0.0 讓區域網路內的電腦可以存取
    try:
        app.run(host='0.0.0.0', port=5000, debug=False)
    finally:
        picam2.stop()
        
#####sudo fuser -k /dev/video0