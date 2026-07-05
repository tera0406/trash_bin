import streamlit as st
import numpy as np
import pandas as pd
import time
import os
import sys
import io
import json

# 確保可以匯入 pi_client 目錄下的其他既有模組
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 匯入網路管理助手
from src.network import wifi_helper

# 嘗試匯入 ESP32 UART 與配置
try:
    from src.hardware.esp32_uart import ESP32UART
    from config import CLASS_MAPPING, ESP32_PORT, PITCH_NEUTRAL, ENABLE_ACTUATOR, AUDIO_NORM_MIN_THRESHOLD, AUDIO_NORM_MAX_GAIN
except ImportError:
    ESP32UART = None
    CLASS_MAPPING = {
        "paper":   {"pitch": 45, "yaw": 0},
        "plastic": {"pitch": 135, "yaw": 0},
        "general": {"pitch": 45, "yaw": 90},
        "metal":   {"pitch": 135, "yaw": 90},
    }
    ESP32_PORT = "/dev/ttyUSB0"
    PITCH_NEUTRAL = 98
    ENABLE_ACTUATOR = False
    AUDIO_NORM_MIN_THRESHOLD = 1e-5
    AUDIO_NORM_MAX_GAIN = 100.0


# 嘗試匯入專案的音訊處理模組與配置
try:
    from src.hardware.audio_processor import record_and_process_audio, audio_to_mel_spectrogram_image, FS, CHANNELS, AUDIO_DEV_ID
except ImportError:
    # 回退預設值
    FS = 48000
    CHANNELS = 2
    AUDIO_DEV_ID = 1
    record_and_process_audio = None
    audio_to_mel_spectrogram_image = None

# 嘗試匯入 sounddevice 庫
try:
    import sounddevice as sd
    sounddevice_available = True
except ImportError:
    sounddevice_available = False

# --- Streamlit 頁面設定 ---
st.set_page_config(
    page_title="🗑️ 智慧垃圾桶 - 聲音與運行狀態監測站",
    page_icon="🎙️",
    layout="centered",
    initial_sidebar_state="expanded"
)

# 注入科技感客製 CSS 樣式
st.markdown("""
    <style>
    .main {
        background-color: #0f1116;
        color: #e2e8f0;
    }
    .stApp {
        background-color: #0f1116;
    }
    h1, h2, h3, h4 {
        color: #38bdf8 !important;
        font-family: 'Inter', sans-serif;
    }
    .metric-card {
        background-color: #1e293b;
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 20px;
        margin: 10px 0;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
    }
    .status-panel {
        border-radius: 12px;
        padding: 24px;
        text-align: center;
        margin-bottom: 20px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.25);
    }
    .state-title {
        font-size: 1.1em;
        text-transform: uppercase;
        letter-spacing: 2px;
        color: #94a3b8;
        margin-bottom: 6px;
    }
    .state-value {
        font-size: 2.2em;
        font-weight: 800;
        margin-bottom: 8px;
    }
    .status-badge {
        padding: 6px 14px;
        border-radius: 20px;
        font-weight: bold;
        display: inline-block;
        font-size: 0.9em;
    }
    .status-green {
        background-color: rgba(16, 185, 129, 0.15);
        color: #10b981;
        border: 1px solid #10b981;
    }
    .status-yellow {
        background-color: rgba(245, 158, 11, 0.15);
        color: #f59e0b;
        border: 1px solid #f59e0b;
    }
    .status-blue {
        background-color: rgba(14, 165, 233, 0.15);
        color: #0ea5e9;
        border: 1px solid #0ea5e9;
    }
    .status-red {
        background-color: rgba(239, 68, 68, 0.15);
        color: #ef4444;
        border: 1px solid #ef4444;
    }
    </style>
""", unsafe_allow_html=True)

st.title("🗑️ 智慧垃圾桶 - 實時監測看板")
st.markdown("連線 Raspberry Pi 核心控制程序，提供垃圾投放實時狀態、物體照片快照、碰撞錄音回放與分類日誌。")

# 檢查相機佔用說明
with st.sidebar:
    st.header("🛠️ 監測站控制中心")
    auto_refresh = st.checkbox("🔄 啟用看板自動刷新 (2秒)", value=True)
    
    # 讀取與控制伺服馬達致動開關
    current_actuator_state = wifi_helper.get_current_env_actuator(default=ENABLE_ACTUATOR)
    enable_actuator = st.checkbox("⚙️ 啟用伺服馬達 (Servo) 動作", value=current_actuator_state)
    if enable_actuator != current_actuator_state:
        wifi_helper.update_env_enable_actuator(enable_actuator)
        st.toast(f"已{'開啟' if enable_actuator else '關閉'}伺服馬達動作，主控程序將即時套用！", icon="⚙️")
        
    st.info("ℹ️ **相機零衝突觀測說明**\n\n主控程序已被啟動並佔用相機。本看板會即時顯示垃圾投放瞬間被「拍下並上傳的真實照片」，既保證看得到現場快照，又 100% 避免程序設備衝突！")
    st.markdown("---")
    st.markdown("💡 **操作指引**\n1. 在 **運行監控** 頁籤查看即時狀態。\n2. 當有投遞發生，畫面會即時更新快照與音軌。\n3. 在 **收訊診斷** 頁籤可手動測試聲音輸入規格與生成 AI 頻譜圖。")

# --- 功能分頁面板 ---
tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 垃圾桶運行監控", "🎤 麥克風收訊診斷", "📁 採集 Dataset 工具", "🌐 網路與 Tailscale 設定", "⚙️ 舵機與重量硬體調校"])


# 獲取 monitor_state.json 檔案路徑
state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp", "monitor_state.json")
state_data = {}
if os.path.exists(state_file):
    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            state_data = json.load(f)
    except Exception:
        pass


# ==========================================
# Tab 1: 垃圾桶運行監控 (Live Dashboard)
# ==========================================
with tab1:
    if not state_data:
        st.warning("⚠️ 尚無實時監控數據。請先在 Raspberry Pi 或終端機上運行主控制器程序：")
        st.code("python pi_client/composite_trigger_controller.py", language="bash")
        st.info("當主程序啟動後，本看板將自動感應連線並開始呈現動態狀態。")
    else:
        if state_data:
            status = state_data.get("status", {})
            current_state = status.get("current_state", "UNKNOWN")
            current_weight = status.get("current_weight", 0.0)
            current_tare = status.get("current_tare", 0.0)
            last_update = status.get("last_update", time.time())
            
            # 依狀態決定呈現樣式與顏色
            if current_state == "IDLE":
                bg_color = "rgba(16, 185, 129, 0.08)"
                border_color = "#10b981"
                text_color = "#10b981"
                state_desc = "🟢 系統空閒，持續監測重量與幀差變動中"
            elif current_state == "TRIGGER":
                bg_color = "rgba(245, 158, 11, 0.08)"
                border_color = "#f59e0b"
                text_color = "#f59e0b"
                state_desc = "🟡 偵測到投遞！重量/畫面變更，去抖確認中..."
            elif current_state == "CAPTURE":
                bg_color = "rgba(14, 165, 233, 0.08)"
                border_color = "#0ea5e9"
                text_color = "#0ea5e9"
                state_desc = "🔵 確認投遞！正在進行多媒體錄製與推論..."
            else:
                bg_color = "rgba(148, 163, 184, 0.08)"
                border_color = "#94a3b8"
                text_color = "#e2e8f0"
                state_desc = "🔘 狀態未知"

            # 狀態燈號看板
            st.markdown(f"""
            <div class="status-panel" style="background-color: {bg_color}; border: 2px solid {border_color};">
                <div class="state-title">當前有限狀態機 (FSM) 狀態</div>
                <div class="state-value" style="color: {text_color};">{current_state}</div>
                <div style="font-size: 1.05em; color: #cbd5e1; font-weight: 500;">{state_desc}</div>
                <div style="font-size: 0.85em; color: #64748b; margin-top: 8px;">
                    最後通訊時間: {time.strftime('%H:%M:%S', time.localtime(last_update))}
                </div>
            </div>
            """, unsafe_allow_html=True)

            # 重量與即時資訊
            col_w1, col_w2, col_w3 = st.columns(3)
            with col_w1:
                st.metric("當前垃圾桶新增重量", f"{current_weight:+.1f} g")
            with col_w2:
                st.metric("🎯 動態歸零基準", f"{current_tare:,.0f} ADC")
            with col_w3:
                # 計算與最後通訊的間隔，結合當前狀態判斷主控制器是否仍活躍 (增加容錯秒數防 clock drift/網路延遲，且觸發中直接視為活躍)
                is_alive = (abs(time.time() - last_update) < 25.0) or (current_state in ("TRIGGER", "CAPTURE"))
                st.metric("主程序連線狀態", "🟢 活躍中" if is_alive else "🔴 離線")
            st.markdown("---")

            # 最新一次投放詳細資料
            last_event = state_data.get("last_event")
            if not last_event:
                st.info("💡 系統已成功連線，正在等待下一次垃圾投遞觸發...")
            else:
                st.subheader("📸 最新一次投遞觀測快照")
                
                # 媒體與推論資訊排版
                m_col1, m_col2 = st.columns([1, 1])
                
                with m_col1:
                    # 嘗試載入並顯示投放快照
                    capture_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp", "last_capture.jpg")
                    if os.path.exists(capture_path):
                        st.image(capture_path, caption="📸 投遞瞬間物體快照", width='stretch')
                    else:
                        st.warning("⚠️ 尚未建立快照照片檔。")
                        
                with m_col2:
                    # 嘗試載入並顯示碰撞聲 Mel-Spectrogram
                    spec_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp", "last_spec.jpg")
                    if os.path.exists(spec_path):
                        st.image(spec_path, caption="🔮 AI 碰撞聲音頻譜特徵 (Mel-Spectrogram)", width='stretch')
                    else:
                        st.info("💡 該次投遞未生成音訊頻譜。")

                # 嘗試載入音軌
                audio_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp", "last_audio.wav")
                if os.path.exists(audio_path):
                    st.markdown("**🔊 垃圾投遞碰撞聲音回放 (Last Collision Audio)**")
                    st.audio(audio_path, format="audio/wav")


                # AI 辨識回報卡片
                is_gemini_val = last_event.get("is_gemini", False)
                mode_badge = (
                    '<span class="status-badge status-blue" style="font-size: 0.85em; padding: 2px 8px;">☁️ Gemini 雲端備援</span>'
                    if is_gemini_val else
                    '<span class="status-badge status-green" style="font-size: 0.85em; padding: 2px 8px;">⚡ 本地交叉融合推論</span>'
                )

                st.markdown(f"""
                <div class="metric-card">
                    <h4 style="margin-top:0;">🤖 AI 邊緣分類推論結果</h4>
                    <p style="margin: 6px 0;"><strong>投放時間：</strong> <code>{last_event.get('timestamp')}</code></p>
                    <p style="margin: 6px 0;"><strong>觸發來源：</strong> <code>{last_event.get('source')}</code></p>
                    <p style="margin: 6px 0; font-size: 1.1em;">
                        <strong>預測分類：</strong> 
                        <span style="color: #38bdf8; font-weight: bold; text-transform: uppercase;">
                            {last_event.get('label')}
                        </span>
                    </p>
                    <p style="margin: 6px 0;"><strong>推論模式：</strong> {mode_badge}</p>
                    <p style="margin: 6px 0;"><strong>使用模型：</strong> <code>{last_event.get('model_used', 'gemini-flash-latest' if is_gemini_val else 'best_hierarchical_modelV04.keras')}</code></p>
                    <p style="margin: 6px 0;"><strong>信心度 (Confidence)：</strong> <code>{last_event.get('confidence', 0.0):.2f}</code></p>
                    <p style="margin: 6px 0;"><strong>網路延遲：</strong> <code>{last_event.get('latency_ms', 0.0):.0f} ms</code></p>
                </div>
                """, unsafe_allow_html=True)
                
                # Gemini 推論原因 (Reasoning)
                reasoning = last_event.get("reasoning", "")
                if reasoning:
                    st.info(f"💡 **AI 決策依據說明 (Gemini Reasoning)：**\n{reasoning}")

                # 顯示四個分類的個別機率分布
                probs = last_event.get("probabilities")
                if probs:
                    st.markdown("#### 📊 四大分類個別機率分布")
                    
                    colors = {
                        "paper": "#f59e0b",    # 琥珀金/黃色
                        "plastic": "#0ea5e9",  # 科技藍
                        "metal": "#f97316",    # 活力橘
                        "general": "#64748b"   # 鐵灰色
                    }
                    
                    chinese_labels = {
                        "paper": "紙類 (Paper)",
                        "plastic": "塑膠 (Plastic)",
                        "metal": "金屬 (Metal)",
                        "general": "一般垃圾 (General)"
                    }

                    prob_cols = st.columns(2)
                    for idx, (cat, val) in enumerate(probs.items()):
                        col = prob_cols[idx % 2]
                        color = colors.get(cat, "#38bdf8")
                        name = chinese_labels.get(cat, cat.upper())
                        
                        col.markdown(f"""
                        <div style="display: flex; justify-content: space-between; margin-bottom: 4px; font-size: 0.95em;">
                            <span style="font-weight: 600; color: {color};">■ {name}</span>
                            <span style="font-family: monospace; font-weight: bold; color: #e2e8f0;">{val:.2%}</span>
                        </div>
                        """, unsafe_allow_html=True)
                        col.progress(min(max(float(val), 0.0), 1.0))

                # 顯示本地模型原始機率分布 (如果有 Gemini 備援修正)
                local_probs = last_event.get("local_probabilities")
                if is_gemini_val and local_probs:
                    with st.expander("🔍 檢視本地交叉融合模型原始機率分布 (Gemini 修正前)"):
                        st.markdown("<p style='font-size:0.9em; color:#94a3b8;'>本地模型因信心值低於門檻，已由雲端 Gemini 進行思維鏈輔助修正。以下為本地模型原始推論之個別機率：</p>", unsafe_allow_html=True)
                        local_cols = st.columns(2)
                        for idx, (cat, val) in enumerate(local_probs.items()):
                            col = local_cols[idx % 2]
                            color = colors.get(cat, "#38bdf8")
                            name = chinese_labels.get(cat, cat.upper())
                            
                            col.markdown(f"""
                            <div style="display: flex; justify-content: space-between; margin-bottom: 4px; font-size: 0.9em;">
                                <span style="font-weight: 500; color: #94a3b8;">■ {name}</span>
                                <span style="font-family: monospace; color: #94a3b8;">{val:.2%}</span>
                            </div>
                            """, unsafe_allow_html=True)
                            col.progress(min(max(float(val), 0.0), 1.0))

            # 歷史投遞記錄表
            history = state_data.get("history", [])
            if history:
                st.markdown("### 📋 歷史投遞日誌記錄 (最近 50 次)")
                
                # 整理成 DataFrame 顯示
                import pandas as pd
                try:
                    df = pd.DataFrame(history)
                    # 補足 is_gemini 欄位以防舊資料不存在
                    if "is_gemini" not in df.columns:
                        df["is_gemini"] = False
                    else:
                        df["is_gemini"] = df["is_gemini"].fillna(False)

                    # 補足 model_used 欄位以防舊資料不存在
                    if "model_used" not in df.columns:
                        df["model_used"] = df["is_gemini"].map(lambda x: "gemini-flash-latest" if x else "best_hierarchical_modelV04.keras")
                    else:
                        df["model_used"] = df["model_used"].fillna("best_hierarchical_modelV04.keras")

                    # 重新排列與重命名欄位以利閱讀
                    cols_to_show = ["timestamp", "weight", "source", "label", "confidence", "is_gemini", "model_used", "latency_ms"]
                    
                    # 確保所有顯示欄位皆存在，以防舊版本資料缺項引發 KeyError
                    for col in cols_to_show:
                        if col not in df.columns:
                            if col == "weight":
                                df[col] = 0.0
                            elif col == "confidence":
                                df[col] = 0.0
                            elif col == "latency_ms":
                                df[col] = 0.0
                            elif col == "is_gemini":
                                df[col] = False
                            elif col == "model_used":
                                df[col] = "unknown"
                            else:
                                df[col] = ""
                                
                    df_filtered = df[cols_to_show].copy()
                    
                    # 轉換為更易讀的文字標籤
                    df_filtered["is_gemini"] = df_filtered["is_gemini"].map(
                        lambda x: "☁️ Gemini 備援" if x else "⚡ 本地推論"
                    )
                    
                    df_filtered.columns = ["投遞時間", "重量增量 (g)", "觸發來源", "預測類別", "信心度", "推論模式", "使用模型", "推論延遲 (ms)"]
                    st.dataframe(df_filtered, width='stretch')
                except Exception as e:
                    st.error(f"渲染歷史表格失敗: {e}")

# ==========================================
# Tab 2: 麥克風收訊診斷
# ==========================================
with tab2:
    st.subheader("🛠&nbsp; 麥克風診斷錄製與特徵驗證")
    st.markdown("用以手動測試麥克風是否收訊健全。點擊下方按鈕後，對麥克風製造聲音，系統會顯示波形與頻譜圖。")
    
    # 檢查 sounddevice 是否可用
    if not sounddevice_available:
        st.error("❌ 找不到 `sounddevice` 庫，無法執行測試。")
    else:
        # 獲取系統音訊輸入設備
        try:
            devices = sd.query_devices()
            input_devices = []
            for idx, dev in enumerate(devices):
                if dev['max_input_channels'] > 0:
                    input_devices.append({
                        'id': idx,
                        'name': dev['name'],
                        'channels': dev['max_input_channels'],
                        'samplerate': dev['default_samplerate']
                    })
        except Exception as e:
            input_devices = []
            
        # 根據是否有硬體設備選擇模式
        is_mock_mic = False
        if not input_devices:
            st.warning("🔮 **自動切換「虛擬模擬麥克風」模式**：檢測到當前系統（或開發機環境）無實體麥克風輸入裝置。系統已自動為您配置高品質模擬訊號產生器，您依然可以點選下方按鈕，手動產生與測試 AI 碰撞聲頻譜特徵！")
            is_mock_mic = True
            device_options = {-1: "🔮 虛擬模擬麥克風 (Simulated Input)"}
            selected_device_id = -1
            
            st.selectbox(
                "選擇麥克風設備 (Microphone Device)",
                options=[-1],
                format_func=lambda x: device_options[x],
                index=0,
                key="diag_device_select",
                disabled=True
            )
        else:
            device_options = {dev['id']: f"ID {dev['id']}: {dev['name']}" for dev in input_devices}
            default_device_index = AUDIO_DEV_ID if AUDIO_DEV_ID in device_options else list(device_options.keys())[0]

            selected_device_id = st.selectbox(
                "選擇麥克風設備 (Microphone Device)",
                options=list(device_options.keys()),
                format_func=lambda x: device_options[x],
                index=list(device_options.keys()).index(default_device_index),
                key="diag_device_select"
            )

        duration = st.slider("設定錄製時長 (秒)", min_value=1.0, max_value=5.0, value=2.0, step=0.5, key="diag_duration_slider")
        start_rec = st.button("🚀 開始手動錄音測試", use_container_width=True)

        if start_rec:
            status_container = st.empty()
            
            try:
                if is_mock_mic:
                    status_container.info(f"🎤 模擬錄製中，時長為 {duration} 秒... 請製造些虛擬碰撞聲！")
                    # 模擬錄音動態進度條
                    progress_bar = st.progress(0.0)
                    for i in range(100):
                        time.sleep(duration / 100.0)
                        progress_bar.progress((i + 1) / 100.0)
                    
                    # 產生高品質碰撞與摩擦模擬訊號 (多頻率衰減正弦波 + 高斯噪聲)
                    t = np.linspace(0, duration, int(duration * FS))
                    impact = 0.5 * np.sin(2 * np.pi * 320 * t) * np.exp(-4.0 * t)
                    resonance = 0.25 * np.sin(2 * np.pi * 180 * t) * np.exp(-1.5 * t)
                    high_pitch = 0.15 * np.sin(2 * np.pi * 950 * t) * np.exp(-8.0 * t)
                    noise = 0.05 * np.random.normal(0, 0.1, len(t))
                    mono_audio = impact + resonance + high_pitch + noise
                    mono_audio = np.clip(mono_audio, -1.0, 1.0)
                    
                    progress_bar.empty()
                else:
                    status_container.info(f"🎤 錄音中，時長為 {duration} 秒... 請對著麥克風製造些聲音！")
                    raw_recording = sd.rec(
                        int(duration * FS),
                        samplerate=FS,
                        channels=1,
                        dtype='float32',
                        device=selected_device_id
                    )
                    sd.wait()
                    mono_audio = raw_recording.flatten()
                    
                status_container.success("✅ 錄音完成！")
                        
                # 音訊指標
                peak_val = float(np.max(np.abs(mono_audio)))
                rms_val = float(np.sqrt(np.mean(mono_audio**2)))
                
                # 品質分級
                if peak_val > 0.05:
                    status_html = '<span class="status-badge status-green">🟢 收音品質優良</span>'
                    feedback = "偵測到明顯的聲音訊號，麥克風運作健全。"
                elif peak_val > 0.005:
                    status_html = '<span class="status-badge status-yellow">🟡 訊號微弱 (音量偏低)</span>'
                    feedback = "成功錄下聲音，但振幅低。請確認麥克風朝向或系統音量。"
                else:
                    status_html = '<span class="status-badge status-red">🔴 偵測為完全靜音</span>'
                    feedback = "未偵測到任何聲音起伏！請檢查麥克風硬體開關。"

                st.markdown(f"""
                <div class="metric-card">
                    <h4>📊 聲音品質診斷</h4>
                    <p><strong>收訊狀態：</strong>{status_html}</p>
                    <p><strong>最大峰值振幅 (Peak)：</strong> <code>{peak_val:.5f}</code></p>
                    <p><strong>均方根音量 (RMS)：</strong> <code>{rms_val:.5f}</code></p>
                    <p style="color: #94a3b8; font-size: 0.9em; border-top: 1px solid #334155; padding-top: 8px;">💡 {feedback}</p>
                </div>
                """, unsafe_allow_html=True)
                
                st.markdown("#### 📈 聲音時域波形")
                st.line_chart(mono_audio[:int(len(mono_audio)/2):10])
                
                st.markdown("#### 🔊 錄音回放")
                st.audio(mono_audio, format="audio/wav", sample_rate=FS)
                
                if audio_to_mel_spectrogram_image is not None:
                    st.markdown("#### 🔮 AI 辨識特徵頻譜圖 (Mel-Spectrogram)")
                    # 雙安全閥平滑自動增益 (AGC)
                    if peak_val > AUDIO_NORM_MIN_THRESHOLD:
                        gain = 0.9 / peak_val
                        if gain > AUDIO_NORM_MAX_GAIN:
                            gain = AUDIO_NORM_MAX_GAIN
                        normalized_audio = mono_audio * gain
                    else:
                        normalized_audio = mono_audio
                    
                    spec_bytes = audio_to_mel_spectrogram_image(normalized_audio, samplerate=FS)
                    if spec_bytes:
                        st.image(spec_bytes, caption="生成之 Mel-Spectrogram (VIRIDIS 彩色色表)", width=350)
            except Exception as e:
                st.error(f"手動錄音測試失敗: {e}")

# ==========================================
# Tab 3: 📁 採集 Dataset 工具
# ==========================================
with tab3:
    st.subheader("📁 垃圾分類數據集 (Dataset) 採集與標記工具")
    st.markdown("當垃圾桶主程式運行時，會自動捕捉最新一次投遞的影像與碰撞聲。本頁面讓您能以「零衝突」的方式，對這些最新暫存檔案進行人工標記，並歸檔至對應的數據集目錄下，以供後續模型訓練。")

    # 定義路徑
    pi_client_dir = os.path.dirname(os.path.abspath(__file__))
    temp_dir = os.path.join(pi_client_dir, "temp")
    dataset_dir = os.path.join(os.path.dirname(pi_client_dir), "dataset")
    
    # 初始化 dataset 資料夾
    categories = ["paper", "plastic", "metal", "general", "others"]
    for cat in categories:
        os.makedirs(os.path.join(dataset_dir, cat), exist_ok=True)

    # 檢查暫存檔是否存在
    capture_path = os.path.join(temp_dir, "last_capture.jpg")
    audio_path = os.path.join(temp_dir, "last_audio.wav")
    spec_path = os.path.join(temp_dir, "last_spec.jpg")

    has_temp = os.path.exists(capture_path) or os.path.exists(audio_path)

    # 模擬暫存檔產生器 (為方便 Demo 與非 Pi 環境)
    if not has_temp:
        col_mock1, col_mock2 = st.columns([2, 1])
        with col_mock1:
            st.info("💡 偵測到目前暫無任何垃圾投遞暫存數據。您可以在主控程式執行投遞後自動生成，或在下方一鍵生成模擬測試樣本以測試此頁籤功能。")
        with col_mock2:
            if st.button("🛠️ 產生模擬測試樣本", use_container_width=True):
                try:
                    import cv2
                    img = np.zeros((480, 640, 3), dtype=np.uint8)
                    for y in range(480):
                        img[y, :, 0] = int(y / 480 * 120)
                        img[y, :, 1] = int(y / 480 * 180)
                        img[y, :, 2] = 220
                    cv2.putText(img, "MOCK DATASET SAMPLE", (120, 220), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
                    cv2.putText(img, "Paper Cup (Simulated)", (160, 270), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (226, 232, 240), 2)
                    cv2.putText(img, time.strftime("%Y-%m-%d %H:%M:%S"), (180, 320), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (148, 163, 184), 1)
                    os.makedirs(temp_dir, exist_ok=True)
                    cv2.imwrite(capture_path, img)

                    # 模擬 WAV
                    import wave
                    import struct
                    with wave.open(audio_path, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(44100)
                        for i in range(44100):
                            val = int(30000.0 * np.sin(2.0 * np.pi * 440.0 * i / 44100.0) * np.exp(-5.0 * i / 44100.0))
                            wf.writeframes(struct.pack('h', val))

                    # 模擬頻譜
                    spec_img = np.zeros((256, 256, 3), dtype=np.uint8)
                    for y in range(256):
                        spec_img[y, :, 0] = y
                        spec_img[y, :, 1] = 255 - y
                        spec_img[y, :, 2] = int(y/2)
                    cv2.putText(spec_img, "Spectrogram", (30, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                    cv2.imwrite(spec_path, spec_img)

                    st.success("✅ 成功產生模擬樣本！將立即為您刷新頁面。")
                    time.sleep(0.5)
                    st.rerun()
                except Exception as ex:
                    st.error(f"產生模擬檔案失敗: {ex}")
    else:
        st.markdown("### 🔍 當前最新投放暫存數據")
        
        # 顯示圖片與音檔
        col_pv1, col_pv2 = st.columns(2)
        with col_pv1:
            if os.path.exists(capture_path):
                st.image(capture_path, caption="📸 投遞瞬間物體照片", width='stretch')
            else:
                st.info("無照片暫存")
        with col_pv2:
            if os.path.exists(spec_path):
                st.image(spec_path, caption="🔮 音訊 Mel-Spectrogram 頻譜", width='stretch')
            else:
                st.info("無頻譜暫存")
            
            if os.path.exists(audio_path):
                st.markdown("**🔊 碰撞錄音回放：**")
                st.audio(audio_path, format="audio/wav")
            else:
                st.info("無錄音暫存")

        st.markdown("---")

        # 標記控制面板
        st.markdown("### 🏷️ 數據集歸檔標記 (Data Annotation)")
        
        # 嘗試讀取 AI 預測類別與即時重量資訊
        ai_label = "unknown"
        current_weight_g = 0.0
        trigger_source_str = "UNKNOWN"
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    state_data = json.load(f)
                    ai_label = state_data.get("last_event", {}).get("label", "unknown").lower()
                    current_weight_g = state_data.get("last_event", {}).get("weight", 0.0)
                    trigger_source_str = state_data.get("last_event", {}).get("source", "UNKNOWN")
            except:
                pass
        
        # 提示 AI 預測結果以供標記參考
        if ai_label in categories:
            st.info(f"🤖 **AI 預測類別為：{ai_label.upper()}** (此資訊僅供參考，請在下方手動選擇正確分類)")
        else:
            st.info("🤖 **AI 無法確定類別**，請手動選擇正確的真實分類。")

        # 1. 真實分類單選 (預設 index=None 實現無偏見標記，防自動預設)
        selected_label = st.radio(
            "選擇此投放的 **真實垃圾類別 (True Label)**：",
            options=categories,
            format_func=lambda x: x.upper(),
            index=None,
            horizontal=True
        )

        # 2. 進階：採集備註與動態重量標籤
        col_meta1, col_meta2 = st.columns([2, 1])
        with col_meta1:
            sample_note = st.text_input("📝 採集樣本描述備註 (Note)", placeholder="例如：鋁罐稍微壓扁、乾淨寶特瓶、含水 general")
        with col_meta2:
            st.metric("⚖️ 投放增量 (重量)", f"{current_weight_g:+.1f} g")

        col_act1, col_act2 = st.columns(2)
        with col_act1:
            btn_save_dataset = st.button("💾 儲存並歸檔至 Dataset", use_container_width=True, type="primary")
        with col_act2:
            btn_wipe_temp = st.button("🧹 清空此暫存資料 (不歸檔)", use_container_width=True)

        if btn_save_dataset:
            if selected_label is None:
                st.warning("⚠️ 請先在上方單選框選擇真實的垃圾類別以進行歸檔標記！")
            else:
                import shutil
                import uuid
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                unique_id = str(uuid.uuid4())[:4]
                
                # 定義目標路徑
                target_cat_dir = os.path.join(dataset_dir, selected_label)
                
                saved_files = []
                
                # 複製照片
                if os.path.exists(capture_path):
                    img_name = f"{selected_label}_img_{timestamp}_{unique_id}.jpg"
                    shutil.copy(capture_path, os.path.join(target_cat_dir, img_name))
                    saved_files.append(f"📷 照片: {img_name}")
                    
                # 複製頻譜
                if os.path.exists(spec_path):
                    spec_name = f"{selected_label}_spec_{timestamp}_{unique_id}.jpg"
                    shutil.copy(spec_path, os.path.join(target_cat_dir, spec_name))
                    saved_files.append(f"🔮 頻譜圖: {spec_name}")
                
                if saved_files:
                    st.success(f"🎉 **歸檔成功！** 已保存以下檔案至 `dataset/{selected_label}/`：\n" + "\n".join(saved_files))
                    
                    # 自動清空暫存以防重複儲存
                    for p in [capture_path, audio_path, spec_path]:
                        if os.path.exists(p):
                            try:
                                os.remove(p)
                            except:
                                pass
                    time.sleep(1.0)
                    st.rerun()
                else:
                    st.error("❌ 找不到任何可歸檔的暫存媒體檔案！")

        if btn_wipe_temp:
            for p in [capture_path, audio_path, spec_path]:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except:
                        pass
            st.success("🧹 暫存快照媒體已成功清空！")
            time.sleep(1.0)
            st.rerun()

    st.markdown("---")

    # 顯示最近歸檔的前 10 筆紀錄與撤銷按鈕
    st.markdown("#### 🕒 最近採集歸檔歷史 (前 10 筆)")
    recent_records = []
    for cat in categories:
        cat_path = os.path.join(dataset_dir, cat)
        if os.path.exists(cat_path):
            for f in os.listdir(cat_path):
                if f.endswith(".jpg") and "_img_" in f:
                    f_path = os.path.join(cat_path, f)
                    recent_records.append({
                        "filename": f,
                        "category": cat,
                        "time": os.path.getmtime(f_path),
                        "path": f_path
                    })
    
    if recent_records:
        # 按修改時間降序排序
        recent_records.sort(key=lambda x: x["time"], reverse=True)
        show_records = recent_records[:10]
        
        df_recent = pd.DataFrame([{
            "類別": r["category"].upper(),
            "檔案名稱": r["filename"],
            "採集時間": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["time"]))
        } for r in show_records])
        
        st.dataframe(df_recent, width='stretch')
        
        # 撤銷/刪除最近一筆按鈕 (防呆)
        latest_r = recent_records[0]
        st.markdown(f"💡 *如果不小心標記錯誤，您可以一鍵撤銷最近一次採集的檔案：* `{latest_r['filename']}`")
        if st.button("🗑️ 撤銷最近一次採集 (刪除該照片與對應音檔)"):
            try:
                if os.path.exists(latest_r["path"]):
                    os.remove(latest_r["path"])
                aud_filename = latest_r["filename"].replace("_img_", "_aud_").replace(".jpg", ".wav")
                aud_path = os.path.join(dataset_dir, latest_r["category"], aud_filename)
                if os.path.exists(aud_path):
                    os.remove(aud_path)
                spec_filename = latest_r["filename"].replace("_img_", "_spec_").replace(".jpg", ".jpg")
                spec_path = os.path.join(dataset_dir, latest_r["category"], spec_filename)
                if os.path.exists(spec_path):
                    os.remove(spec_path)
                # JSON
                meta_filename = latest_r["filename"].replace("_img_", "_meta_").replace(".jpg", ".json")
                meta_path = os.path.join(dataset_dir, latest_r["category"], meta_filename)
                if os.path.exists(meta_path):
                    os.remove(meta_path)
                
                st.success("✅ 已成功撤銷最近一筆採集！")
                time.sleep(1.0)
                st.rerun()
            except Exception as e:
                st.error(f"撤銷失敗: {e}")
    else:
        st.info("尚無採集歸檔歷史。")

    st.markdown("---")

    # 數據集實時統計與紀錄
    st.markdown("### 📊 數據集實時統計 (Dataset Statistics)")
    
    # 掃描 dataset 各類別的檔案數量
    stats_data = []
    total_imgs = 0
    total_auds = 0
    
    for cat in categories:
        cat_path = os.path.join(dataset_dir, cat)
        if os.path.exists(cat_path):
            files = os.listdir(cat_path)
            img_count = len([f for f in files if f.endswith(".jpg") and "_img_" in f])
            aud_count = len([f for f in files if f.endswith(".wav") and "_aud_" in f])
            stats_data.append({
                "類別 (Category)": cat.upper(),
                "已採集照片數": img_count,
                "已採集音檔數": aud_count
            })
            total_imgs += img_count
            total_auds += aud_count
        else:
            stats_data.append({
                "類別 (Category)": cat.upper(),
                "已採集照片數": 0,
                "已採集音檔數": 0
            })

    # 以 Metric Cards 顯示總數
    col_st1, col_st2 = st.columns(2)
    with col_st1:
        st.metric("📦 數據集總照片數", f"{total_imgs} 張")
    with col_st2:
        st.metric("🎙️ 數據集總音檔數", f"{total_auds} 個")

    # 表格與長條圖並排呈現 (Aesthetic Wow!)
    col_ch1, col_ch2 = st.columns([1, 1])
    with col_ch1:
        import pandas as pd
        df_stats = pd.DataFrame(stats_data)
        st.table(df_stats)
    with col_ch2:
        chart_data = pd.DataFrame({
            "照片數": [s["已採集照片數"] for s in stats_data],
            "音檔數": [s["已採集音檔數"] for s in stats_data]
        }, index=[s["類別 (Category)"] for s in stats_data])
        st.bar_chart(chart_data, color=["#0ea5e9", "#10b981"])

    st.markdown("---")

    # 🔍 數據集瀏覽與管理 (Dataset Explorer)
    st.markdown("### 🔍 數據集瀏覽與管理 (Dataset Explorer)")
    exp_cat = st.selectbox("選擇要瀏覽的數據集類別：", options=categories, format_func=lambda x: x.upper())
    
    exp_cat_dir = os.path.join(dataset_dir, exp_cat)
    if os.path.exists(exp_cat_dir):
        # 獲取該目錄下的所有圖片
        cat_files = [f for f in os.listdir(exp_cat_dir) if f.endswith(".jpg") and "_img_" in f]
        if not cat_files:
            st.info(f"📁 類別 {exp_cat.upper()} 中目前尚無已保存的採集樣本。")
        else:
            # 檔案選擇
            selected_file = st.selectbox("選擇要預覽的樣本檔案：", options=cat_files)
            
            # 顯示預覽排版
            prev_col1, prev_col2, prev_col3 = st.columns([1.2, 1.2, 1.6])
            with prev_col1:
                st.image(os.path.join(exp_cat_dir, selected_file), caption="📸 垃圾物體照片 (Snapshot)", width='stretch')
            
            with prev_col2:
                # 尋找對應的 Mel 頻譜圖
                spec_file = selected_file.replace("_img_", "_spec_")
                spec_path = os.path.join(exp_cat_dir, spec_file)
                if os.path.exists(spec_path):
                    st.image(spec_path, caption="🔮 音訊頻譜圖 (Mel-Spectrogram)", width='stretch')
                else:
                    st.info("💡 該樣本無音訊頻譜圖檔")
            
            with prev_col3:
                # 尋找對應的 WAV
                aud_file = selected_file.replace("_img_", "_aud_").replace(".jpg", ".wav")
                aud_path = os.path.join(exp_cat_dir, aud_file)
                if os.path.exists(aud_path):
                    st.markdown("**🔊 音軌回放：**")
                    st.audio(aud_path, format="audio/wav")
                else:
                    st.info("💡 該樣本無音軌記錄")
                
                # 尋找對應的 JSON Metadata
                meta_file = selected_file.replace("_img_", "_meta_").replace(".jpg", ".json")
                meta_path = os.path.join(exp_cat_dir, meta_file)
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, 'r', encoding='utf-8') as f:
                            m_data = json.load(f)
                        st.markdown("**📝 樣本詮釋資料 (Metadata)：**")
                        st.markdown(f"- **時間：** `{m_data.get('timestamp')}`")
                        st.markdown(f"- **重量增量：** `{m_data.get('weight_g', 0.0):+.1f} g`")
                        st.markdown(f"- **觸發來源：** `{m_data.get('trigger_source', 'UNKNOWN')}`")
                        st.markdown(f"- **描述備註：** `{m_data.get('note') if m_data.get('note') else '無備註'}`")
                    except:
                        st.info("💡 Metadata 損毀或無法載入")
                else:
                    st.info("💡 該樣本無 Metadata 側邊檔")
                
                # 刪除此樣本按鈕
                st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
                if st.button("🚨 刪除此樣本 (永久清除檔案)"):
                    try:
                        # 刪除 JPG
                        os.remove(os.path.join(exp_cat_dir, selected_file))
                        # 嘗試刪除 WAV
                        if os.path.exists(aud_path):
                            os.remove(aud_path)
                        # 嘗試刪除 Spec JPG
                        if os.path.exists(spec_path):
                            os.remove(spec_path)
                        # 嘗試刪除 JSON
                        if os.path.exists(meta_path):
                            os.remove(meta_path)
                        
                        st.success(f"🗑️ 已成功刪除樣本 {selected_file}！")
                        time.sleep(1.0)
                        st.rerun()
                    except Exception as e:
                        st.error(f"刪除失敗: {e}")
    else:
        st.info("資料夾不存在")

    st.markdown("---")

    # 📦 數據集一鍵壓縮與下載 (Dataset Export)
    st.markdown("### 📦 數據集一鍵壓縮與下載 (Dataset Export)")
    st.markdown("想要將樹莓派上採集的資料集下載至本地 PC 來訓練模型嗎？點選下方按鈕，系統會自動將整個 `dataset/` 資料夾壓縮打包，並提供一鍵下載按鈕！")
    
    btn_build_zip = st.button("🚀 壓縮打包整個 Dataset 資料夾")
    
    zip_export_path = os.path.join(temp_dir, "dataset_export.zip")
    if btn_build_zip:
        with st.spinner("📦 正在打包 dataset 目錄中，請稍候..."):
            try:
                import zipfile
                # 確保 temp 目錄存在
                os.makedirs(temp_dir, exist_ok=True)
                
                # 建立 ZIP
                with zipfile.ZipFile(zip_export_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for root, dirs, files in os.walk(dataset_dir):
                        for file in files:
                            # 排除臨時或隐藏檔
                            if file.startswith('.'):
                                continue
                            filepath = os.path.join(root, file)
                            # 計算相對壓縮路徑，讓解壓後直接是各類別資料夾
                            arcname = os.path.relpath(filepath, os.path.dirname(dataset_dir))
                            zipf.write(filepath, arcname)
                            
                st.success("🎉 **打包成功！** 已完成 dataset 檔案壓縮。")
            except Exception as e:
                st.error(f"❌ 壓縮失敗: {e}")

    # 若 ZIP 檔已建立，呈現下載按鈕
    if os.path.exists(zip_export_path):
        try:
            with open(zip_export_path, 'rb') as f:
                zip_bytes = f.read()
            st.download_button(
                label="📥 點我下載整個 Dataset 壓縮檔 (.zip)",
                data=zip_bytes,
                file_name=f"trash_bin_dataset_{time.strftime('%Y%m%d_%H%M%S')}.zip",
                mime="application/zip",
                use_container_width=True
            )
        except Exception as e:
            st.error(f"讀取下載檔錯誤: {e}")

# ==========================================
# Tab 4: 網路與 Tailscale 設定
# ==========================================
with tab4:
    st.subheader("🌐 樹莓派網路連線與 Tailscale 設定")
    st.markdown("用以輕鬆登錄外部 Wi-Fi（如手機熱點），並設定 PC 伺服器的固定 Tailscale 連線，使帶出門 Demo 流程完全自動化。")
    
    # 獲取當前網路狀態與設定
    net_status = wifi_helper.get_network_status()
    current_pc_ip, current_pc_port = wifi_helper.get_current_env_server()
    
    # 1. 網路診斷卡片
    col_n1, col_n2 = st.columns(2)
    with col_n1:
        st.markdown(f"""
        <div class="metric-card" style="border-left: 5px solid #38bdf8;">
            <h4 style="margin-top:0; color:#38bdf8;">📡 樹莓派網路狀態</h4>
            <p style="margin: 4px 0;"><strong>當前 Wi-Fi SSID：</strong> <code>{net_status['ssid']}</code></p>
            <p style="margin: 4px 0;"><strong>本機 IP：</strong> <code>{', '.join(net_status['local_ips']) if net_status['local_ips'] else '無 IP'}</code></p>
            <p style="margin: 4px 0;"><strong>系統環境：</strong> <code>{net_status['os']}</code></p>
        </div>
        """, unsafe_allow_html=True)
        
    with col_n2:
        # 特別強調 Tailscale 的固定 IP
        st.markdown(f"""
        <div class="metric-card" style="border-left: 5px solid #10b981; background-color: rgba(16,185,129,0.03);">
            <h4 style="margin-top:0; color:#10b981;">🛡️ Tailscale 固定虛擬網</h4>
            <p style="margin: 4px 0;"><strong>本機 Tailscale IP：</strong> <code>{net_status['tailscale_ip']}</code></p>
            <p style="margin: 4px 0; color:#94a3b8; font-size:0.9em;">💡 只要樹莓派與 PC 都安裝並登入 Tailscale，無論連線何種 Wi-Fi/手機熱點，皆能使用 Tailscale IP 進行無縫互連！</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # 2. PC 伺服器 IP 與 Port 設定編輯器
    st.subheader("💻 PC 推論伺服器連線設定")
    st.markdown("在此配置垃圾桶主控制器連線的 PC 推論伺服器端點。**建議直接填寫 PC 的 Tailscale IP**，如此出門即可免改 IP 直接連通！")
    
    col_ip1, col_ip2 = st.columns([3, 1])
    with col_ip1:
        new_pc_ip = st.text_input("PC 伺服器 IP 地址 (PC_SERVER_IP)", value=current_pc_ip)
    with col_ip2:
        new_pc_port = st.text_input("Port", value=current_pc_port)
        
    # 如果輸入的是本機或局域網 IP，溫馨提示使用 Tailscale IP
    if new_pc_ip.startswith("192.168.") or new_pc_ip.startswith("172.") or new_pc_ip.startswith("10."):
        if not new_pc_ip.startswith("100."): # Tailscale IP 通常是 100.x.y.z
            st.warning("⚠️ 偵測到您目前使用的是局域網 IP（192.168.x.x 等）。帶出門 Demo 時局域網 IP 會改變，建議更換為 **PC 的 Tailscale IP（通常為 100.x.y.z）** 以實現跨網路免改 IP 互聯！")
            
    btn_save_ip = st.button("💾 儲存並更新 .env 設定", use_container_width=True)
    if btn_save_ip:
        if not new_pc_ip.strip():
            st.error("❌ IP 地址不能為空！")
        else:
            success, msg = wifi_helper.update_env_pc_ip(new_pc_ip.strip())
            if success:
                st.success(f"✅ {msg}")
                # 重新載入，以便下次重新整理時反映最新值
                time.sleep(1.0)
                st.rerun()
            else:
                st.error(f"❌ {msg}")

    st.markdown("---")

    # 3. Wi-Fi 新增器
    st.subheader("📶 登錄新 Wi-Fi 連線 (例如手機熱點)")
    st.markdown("樹莓派可以記憶多組 Wi-Fi 連線設定。在此登錄您的手機熱點，出門時開啟手機熱點，樹莓派將會**自動切換連線**！")
    
    wifi_ssid = st.text_input("Wi-Fi SSID (名稱)")
    wifi_password = st.text_input("Wi-Fi 密碼", type="password")
    
    btn_add_wifi = st.button("➕ 將此 Wi-Fi 寫入樹莓派", use_container_width=True)
    if btn_add_wifi:
        if not wifi_ssid.strip():
            st.error("❌ Wi-Fi SSID 不能為空！")
        elif len(wifi_password) < 8:
            st.error("❌ Wi-Fi 密碼長度不能少於 8 碼！")
        else:
            with st.spinner("正在寫入樹莓派網路配置並嘗試連線..."):
                success, msg = wifi_helper.add_wifi(wifi_ssid.strip(), wifi_password)
                if success:
                    st.success(f"✅ {msg}")
                else:
                    st.error(f"❌ {msg}")
                    # 在 Windows 等非 Linux 開發機上提供友好提示
                    if "win32" in sys.platform or "darwin" in sys.platform:
                        st.info(f"💡 **模擬提示**：如果在樹莓派 (Linux) 實機上，本功能會自動：\n1. 針對新版 Bookworm：執行 `sudo nmcli dev wifi connect \"{wifi_ssid}\" password \"***\"`\n2. 針對舊版 Bullseye：寫入 `/etc/wpa_supplicant/wpa_supplicant.conf` 並執行 `wpa_cli reconfigure`\n\n這樣做能讓樹莓派同時記得多個網路，開機即自動切換，不需要每次修改！")

# ==========================================
# Tab 5: ⚙️ 舵機手動測試 (Servo Control)
# ==========================================
with tab5:
    st.subheader("🛠️ 舵機與重量感測器硬體調校")
    
    # 建立子分頁面板，區分舵機手動測試與重量感測器校準
    sub_tab_servo, sub_tab_weight = st.tabs(["⚙️ 雙軸舵機手動測試", "⚖️ 重量感測器實時校準"])
    
    # 共用連線變數宣告
    enable_real_serial = st.session_state.get("real_serial_check", False)
    
    # ==========================================
    # Sub-Tab 1: 雙軸舵機手動測試
    # ==========================================
    with sub_tab_servo:
        st.markdown("用以手動調整分類檔板的 俯仰角 (Pitch) 與 偏航角 (Yaw)，以驗證 ESP32 舵機致動動作是否確實到位。")

        # 我們需要動態管理序列埠連線，為防佔用背景 composite_trigger_controller 的連接埠，
        # 預設採用「模擬發送」，使用者可手動開啟「🔌 啟用實體序列埠連線」進行真機測試。
        st.markdown("### 🔌 連線模式設定")
        enable_real_serial = st.checkbox("🔌 啟用實體序列埠連線 (會嘗試開啟 UART Port)", value=False, key="real_serial_check")
        
        # 建立或模擬連線
        uart_instance = None
        serial_port_name = os.getenv("SERIAL_PORT", ESP32_PORT)
        
        if enable_real_serial:
            if ESP32UART is None:
                st.error("❌ 系統中缺少 `esp32_uart` 庫，無法建立連線。")
            else:
                # 建立或從 session_state 讀取連線，避免 Streamlit 重新整理時重複建立
                if 'st_uart' not in st.session_state or st.session_state.st_uart is None:
                    with st.spinner(f"正在與 ESP32 ({serial_port_name}) 建立 UART 連線..."):
                        try:
                            u = ESP32UART(port=serial_port_name)
                            if u.connect():
                                st.session_state.st_uart = u
                                st.success(f"✅ 成功與 ESP32 ({serial_port_name}) 建立連線！")
                            else:
                                st.error(f"❌ 無法開啟序列埠 {serial_port_name}，可能是背景主控制器程序正在執行並佔用了串口。")
                                st.session_state.st_uart = None
                        except Exception as e:
                            st.error(f"❌ 連線異常: {e}")
                            st.session_state.st_uart = None
                
                uart_instance = st.session_state.st_uart
        else:
            # 若使用者取消勾選，釋放 session_state 中的實體連線
            if 'st_uart' in st.session_state and st.session_state.st_uart is not None:
                try:
                    st.session_state.st_uart.disconnect()
                except:
                    pass
                st.session_state.st_uart = None
                st.info("🔌 實體序列埠連線已斷開，切換回虛擬模擬控制模式。")

        # 顯示連線狀態 Badge
        if uart_instance and uart_instance.serial_conn and uart_instance.serial_conn.is_open:
            st.markdown(f'<span class="status-badge status-green">🟢 實體序列埠連線成功 (Port: {uart_instance.port})</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="status-badge status-yellow">🟡 虛擬模擬控制模式 (無串口佔用)</span>', unsafe_allow_html=True)

        st.markdown("---")

        # 手動滑桿控制
        st.markdown("### 🎛️ 手動角度微調")
        
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            pitch_val = st.slider("Pitch 俯仰角 (上下滑動)", min_value=0, max_value=180, value=PITCH_NEUTRAL, step=5)
        with col_s2:
            yaw_val = st.slider("Yaw 偏航角 (左右旋轉 - 物理角度 0~270°)", min_value=0, max_value=270, value=90, step=5)

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            btn_send_servo = st.button("🚀 傳送角度至舵機", use_container_width=True)
        with col_btn2:
            btn_reset_servo = st.button("🔄 傳送歸位指令 (RESET)", use_container_width=True)

        # 處理手動按鈕動作
        if btn_send_servo:
            # 將物理角度 0~270° 映射至 ESP32 的 0~180 範圍 (除以 1.5)
            yaw_write = int(yaw_val / 1.5)
            cmd_str = f"MOVE:P:{pitch_val}:Y:{yaw_write}\\n"
            st.markdown(f"**📟 傳送指令流：** `MOVE:P:{pitch_val}:Y:{yaw_write}\\n` (物理角度 Yaw: {yaw_val}°)")
            
            if uart_instance and uart_instance.serial_conn and uart_instance.serial_conn.is_open:
                with st.spinner("正在發送指令給 ESP32..."):
                    success, err = uart_instance.send_move_command(pitch_val, yaw_write)
                    if success:
                        st.success("✅ 指令已送出並收到 ACK！")
                    else:
                        st.error(f"❌ 傳送失敗: {err}")
            else:
                st.info("💡 **模擬發送成功**！(已成功模擬傳送，若要實機測試，請勾選上方的「啟用實體序列埠連線」)")

        if btn_reset_servo:
            st.markdown("**📟 傳送指令流：** `RESET\\n`")
            if uart_instance and uart_instance.serial_conn and uart_instance.serial_conn.is_open:
                with st.spinner("正在發送歸位指令給 ESP32..."):
                    success, err = uart_instance.send_reset_command()
                    if success:
                        st.success("✅ 歸位指令已送出並收到 ACK！")
                    else:
                        st.error(f"❌ 歸位失敗: {err}")
            else:
                st.info("💡 **模擬歸位發送成功**！")

        st.markdown("---")

        # 4 大預設分類角度一鍵測試
        st.markdown("### 🏷️ 垃圾分類預設角度測試")
        st.markdown("點擊以下按鈕會直接將舵機轉動到系統中對應垃圾種類的投遞位置，可用來驗證各垃圾通道的實體滑落狀態：")

        col_c1, col_c2, col_c3, col_c4 = st.columns(4)
        
        with col_c1:
            p_val, y_val = CLASS_MAPPING["paper"]["pitch"], CLASS_MAPPING["paper"]["yaw"]
            adjusted_p = PITCH_NEUTRAL + (p_val - 90)
            physical_y = int(y_val * 1.5)
            if st.button("📄 測試 Paper 位置", help=f"Pitch: {adjusted_p} (原本: {p_val}), Yaw: {physical_y}° (寫入值: {y_val})", use_container_width=True):
                st.markdown(f"**測試種類**: `Paper` | **發送角度**: Pitch={adjusted_p}°, Yaw={physical_y}° (寫入值={y_val})")
                if uart_instance and uart_instance.serial_conn and uart_instance.serial_conn.is_open:
                    uart_instance.send_move_command(adjusted_p, y_val)
                    st.success("✅ 指令送出成功！")
                else:
                    st.info(f"💡 模擬發送：`MOVE:P:{adjusted_p}:Y:{y_val}\\n`")

        with col_c2:
            p_val, y_val = CLASS_MAPPING["plastic"]["pitch"], CLASS_MAPPING["plastic"]["yaw"]
            adjusted_p = PITCH_NEUTRAL + (p_val - 90)
            physical_y = int(y_val * 1.5)
            if st.button("🥤 測試 Plastic 位置", help=f"Pitch: {adjusted_p} (原本: {p_val}), Yaw: {physical_y}° (寫入值: {y_val})", use_container_width=True):
                st.markdown(f"**測試種類**: `Plastic` | **發送角度**: Pitch={adjusted_p}°, Yaw={physical_y}° (寫入值={y_val})")
                if uart_instance and uart_instance.serial_conn and uart_instance.serial_conn.is_open:
                    uart_instance.send_move_command(adjusted_p, y_val)
                    st.success("✅ 指令送出成功！")
                else:
                    st.info(f"💡 模擬發送：`MOVE:P:{adjusted_p}:Y:{y_val}\\n`")

        with col_c3:
            p_val, y_val = CLASS_MAPPING["general"]["pitch"], CLASS_MAPPING["general"]["yaw"]
            adjusted_p = PITCH_NEUTRAL + (p_val - 90)
            physical_y = int(y_val * 1.5)
            if st.button("🗑️ 測試 General 位置", help=f"Pitch: {adjusted_p} (原本: {p_val}), Yaw: {physical_y}° (寫入值: {y_val})", use_container_width=True):
                st.markdown(f"**測試種類**: `General` | **發送角度**: Pitch={adjusted_p}°, Yaw={physical_y}° (寫入值={y_val})")
                if uart_instance and uart_instance.serial_conn and uart_instance.serial_conn.is_open:
                    uart_instance.send_move_command(adjusted_p, y_val)
                    st.success("✅ 指令送出成功！")
                else:
                    st.info(f"💡 模擬發送：`MOVE:P:{adjusted_p}:Y:{y_val}\\n`")

        with col_c4:
            p_val, y_val = CLASS_MAPPING["metal"]["pitch"], CLASS_MAPPING["metal"]["yaw"]
            adjusted_p = PITCH_NEUTRAL + (p_val - 90)
            physical_y = int(y_val * 1.5)
            if st.button("🥫 測試 Metal 位置", help=f"Pitch: {adjusted_p} (原本: {p_val}), Yaw: {physical_y}° (寫入值: {y_val})", use_container_width=True):
                st.markdown(f"**測試種類**: `Metal` | **發送角度**: Pitch={adjusted_p}°, Yaw={physical_y}° (寫入值={y_val})")
                if uart_instance and uart_instance.serial_conn and uart_instance.serial_conn.is_open:
                    uart_instance.send_move_command(adjusted_p, y_val)
                    st.success("✅ 指令送出成功！")
                else:
                    st.info(f"💡 模擬發送：`MOVE:P:{adjusted_p}:Y:{y_val}\\n`")

    # ==========================================
    # Sub-Tab 2: 重量感測器實時校準
    # ==========================================
    with sub_tab_weight:
        st.markdown("### ⚖️ 重量感測器 (HX711) 實時校準與噪訊診斷")
        st.markdown("本工具提供實時 ADC 原始讀數、噪訊 $\sigma$ 標準差診斷，並支援空桶軟體去皮 (Tare) 與已知砝碼一鍵校準，**自動計算係數並覆寫寫入 `config.py`**。")
        # 嘗試匯入 WeightSensor 與配置
        weight_sensor_available = False
        try:
            from src.hardware.weight_sensor import WeightSensor
            from config import WEIGHT_CALIBRATION_FACTOR
            weight_sensor_available = True
        except ImportError:
            try:
                from config import WEIGHT_CALIBRATION_FACTOR
            except ImportError:
                WEIGHT_CALIBRATION_FACTOR = -217.71
            
            # 定義一個 Mock/Fallback 類別，避免後續呼叫 NameError 崩潰
            class WeightSensor:
                def __init__(self, uart_conn=None):
                    self.mock = True
                    self.tare_value = 0.0
                    self.calibration_factor = WEIGHT_CALIBRATION_FACTOR
                def _read_raw(self):
                    return float('nan')
                def read_grams(self):
                    return 0.0
                def tare(self, samples=5):
                    pass
            weight_sensor_available = False

        # 顯示當前配置狀態
        st.markdown("#### 📊 當前重量配置參數")
        bg_status = state_data.get("status", {})
        bg_tare = bg_status.get("current_tare", None)
        
        if bg_tare is not None:
            col_cfg1, col_cfg2, col_cfg3 = st.columns(3)
            with col_cfg1:
                st.metric("當前 config.py 係數 (CALIBRATION_FACTOR)", f"{WEIGHT_CALIBRATION_FACTOR:.2f}")
            with col_cfg2:
                st.metric("🎯 背景主程序動態去皮基準 (Dynamic Tare)", f"{bg_tare:,.0f} ADC")
            with col_cfg3:
                current_tare = st.session_state.get("cal_tare_value", 0.0)
                st.metric("當前臨時手動零點基準 (Manual Tare)", f"{current_tare:.1f}")
        else:
            col_cfg1, col_cfg2 = st.columns(2)
            with col_cfg1:
                st.metric("當前 config.py 係數 (CALIBRATION_FACTOR)", f"{WEIGHT_CALIBRATION_FACTOR:.2f}")
            with col_cfg2:
                current_tare = st.session_state.get("cal_tare_value", 0.0)
                st.metric("當前臨時手動零點基準 (Manual Tare)", f"{current_tare:.1f}")
            
        # 建立或共用重量感測器連線
        sensor = None
        if enable_real_serial and 'st_uart' in st.session_state and st.session_state.st_uart is not None:
            try:
                # 實機狀態下：直接共用已經建立的實體 UART 連線物件
                sensor = WeightSensor(uart_conn=st.session_state.st_uart.serial_conn)
            except Exception as e:
                st.warning(f"共用串口連線失敗，改用獨立偵測: {e}")
                
        if sensor is None:
            # 自動建立或切換為模擬 (若在 Windows 執行)
            sensor = WeightSensor()
            
        if sensor.mock:
            st.warning("🟡 當前處於重量模擬測試模式 (Mock Mode)。在樹莓派上請確認串口可用。")
            
        st.markdown("---")
        
        # 實時讀取測試
        st.markdown("#### 🔄 實時重量讀取與噪訊診斷 (Diagnostics)")
        st.markdown("點擊下方按鈕將進行 **5 次連續取樣**，計算平均 ADC 值與標準差 $\sigma$。標準差偏高代表環境震動劇烈，不利於秤重。")
        
        btn_read_weight_test = st.button("🔍 開始連續採樣 5 次", use_container_width=True)
        if btn_read_weight_test:
            with st.spinner("正在向重量感測器讀取數據..."):
                readings = []
                for idx in range(5):
                    raw = sensor._read_raw()
                    if not np.isnan(raw):
                        readings.append(raw)
                    time.sleep(0.15)
                    
                if readings:
                    avg_raw = float(np.mean(readings))
                    std_raw = float(np.std(readings))
                    
                    # 計算克數
                    cal_factor = st.session_state.get("cal_factor_temp", WEIGHT_CALIBRATION_FACTOR)
                    tare_val = st.session_state.get("cal_tare_value", 0.0)
                    grams = (avg_raw - tare_val) / cal_factor
                    
                    st.success("✅ 採樣成功！")
                    
                    # 繪製讀取結果
                    col_res1, col_res2, col_res3 = st.columns(3)
                    with col_res1:
                        st.metric("平均原始讀數 (ADC)", f"{avg_raw:.1f}")
                    with col_res2:
                        if std_raw < 15.0:
                            noise_badge = "🟢 極度穩定"
                        elif std_raw < 60.0:
                            noise_badge = "🟡 輕微抖動"
                        else:
                            noise_badge = "🔴 嚴重噪訊/環境晃動"
                        st.metric("標準差 σ (噪訊大小)", f"{std_raw:.1f}", help=noise_badge)
                    with col_res3:
                        st.metric("換算重量 (公克)", f"{grams:+.1f} g")
                        
                    # 列出每次讀數表格
                    df_readings = pd.DataFrame({
                        "採樣次數": [f"第 {i+1} 次" for i in range(len(readings))],
                        "原始讀數 (ADC)": readings
                    })
                    st.table(df_readings)
                else:
                    st.error("❌ 讀取重量感測器失敗。請確認實體連線與電源。")
                    
        st.markdown("---")
        
        # 歸零與校準控制
        st.markdown("#### ⚖️ 實時軟體去皮 (Tare) 與一鍵校準")
        st.markdown("請依照以下兩步驟完成高精準度的校準程序：")
        
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            st.markdown("**第一步：清空垃圾桶去皮 (Tare)**")
            st.markdown("請確認分類板上無任何物品後，點擊按鈕取樣 10 次平均建立歸零基準。")
            if bg_tare is not None:
                st.caption("💡 **提示：** 背景主程序已在運行中，其會自動在每次投遞冷卻後進行動態去皮追蹤。若您在此處執行手動去皮，僅會影響本頁籤的即時重量診斷與第二步的砝碼校準。")
            btn_cal_tare = st.button("⚖️ 實時空桶去皮歸零 (10 次平均)", use_container_width=True)
            
            if btn_cal_tare:
                with st.spinner("正在進行高精度歸零去皮中..."):
                    readings = []
                    for _ in range(10):
                        raw = sensor._read_raw()
                        if not np.isnan(raw):
                            readings.append(raw)
                        time.sleep(0.1)
                        
                    if readings:
                        avg_tare = float(np.mean(readings))
                        st.session_state["cal_tare_value"] = avg_tare
                        sensor.tare_value = avg_tare
                        st.success(f"✅ 空桶去皮完成！零點基準：{avg_tare:.1f}")
                        time.sleep(1.0)
                        st.rerun()
                    else:
                        st.error("❌ 去皮失敗，無法讀取 ADC。")
                        
        with col_t2:
            st.markdown("**第二步：放上已知砝碼一鍵校準**")
            st.markdown("請在板上放置已知重量的砝碼 (例如 `108.5`g 或手動輸入)：")
            cal_weight_g = st.number_input("砝碼重量 (公克)", min_value=1.0, max_value=5000.0, value=108.5, step=0.1)
            
            btn_run_cal = st.button("⚖️ 開始自動校準並寫入 config.py", use_container_width=True, type="primary")
            
            if btn_run_cal:
                tare_val = st.session_state.get("cal_tare_value", None)
                if tare_val is None:
                    st.error("❌ 校準前，請先點擊左側的「第一步：空桶去皮歸零」按鈕！")
                else:
                    with st.spinner(f"正在連續取樣 10 次進行校準 (目標砝碼: {cal_weight_g}g)..."):
                        readings = []
                        for _ in range(10):
                            raw = sensor._read_raw()
                            if not np.isnan(raw):
                                readings.append(raw)
                            time.sleep(0.1)
                            
                        if readings:
                            avg_raw = float(np.mean(readings))
                            
                            # 物理意義: (原始讀數 - 歸零基準) / 此值 = 公克數
                            # 由此求得係數: new_factor = (平均讀數 - 歸零基準) / 砝碼公克數
                            new_factor = (avg_raw - tare_val) / cal_weight_g
                            
                            # 防呆限制
                            if abs(new_factor) < 0.05:
                                st.error(f"❌ 校準係數過小 ({new_factor:.4f})！請確認板上是否確實放有 {cal_weight_g}g 砝碼？")
                            else:
                                # 更新 config.py
                                success, msg = wifi_helper.update_config_calibration_factor(new_factor)
                                if success:
                                    st.success(f"🎉 **校準係數計算與 config.py 寫入成功！**\n\n* 平均原始讀數: `{avg_raw:.1f}`\n* 零點基準: `{tare_val:.1f}`\n* **全新 WEIGHT_CALIBRATION_FACTOR：`{new_factor:.4f}`**\n\n系統已自動覆寫並更新設定檔，下一次啟動將自動套用！")
                                    st.session_state["cal_factor_temp"] = new_factor
                                    time.sleep(3.0)
                                    st.rerun()
                                else:
                                    st.error(f"❌ 寫入 config.py 失敗：{msg}")
                        else:
                            st.error("❌ 讀取數值失敗，無法完成校準。")

# --- 處理看板自動重新整理 (放在整個 UI 渲染之後) ---
if auto_refresh:
    time.sleep(2.0)
    st.rerun()