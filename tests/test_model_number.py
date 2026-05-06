import tensorflow as tf

# 載入模型
model = tf.keras.models.load_model('C:\\Users\\User\\smart_trash_bin_pc\\models\\best_multimodal_model.keras')

# 1. 檢查輸入數量與名稱 (相容寫法)
inputs = model.inputs
print(f"--- 模型輸入資訊 ---")
print(f"輸入張量數量: {len(inputs)}")

for i, inp in enumerate(inputs):
    # 這裡會印出每一層輸入的名稱與形狀
    print(f"輸入 {i}: 名稱='{inp.name}', 形狀={inp.shape}")

# 2. 檢查模型架構摘要
model.summary()