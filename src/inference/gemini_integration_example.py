"""
Gemini 輔助諮詢模組整合範例
示範如何在推論流程中使用 gemini_consultant.py

使用情境:
- 當本地 EfficientNet 模型信心值 < threshold (例如 0.8) 時
- 啟動 Gemini 輔助諮詢系統
- 處理困難樣本 (模糊、重疊、複合材質)
"""

import os
import sys

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from PIL import Image
try:
    from src.inference.vision_engine import get_vision_engine
except ImportError:
    print("\n[WARNING] Could not import vison_engine (likely missing TensorFlow). Using Mock Vision Engine.")
    class MockVisionEngine:
        def predict(self, image):
            return {
                "class": "Class B",
                "confidence": 0.65, # Low confidence to trigger Gemini
                "all_probs": {"Class A": 0.1, "Class B": 0.65, "Class C": 0.1, "Class D": 0.15},
                "status": "success"
            }
    
    def get_vision_engine():
        return MockVisionEngine()

from src.inference.gemini_consultant import get_gemini_consultant
from src.inference.gemini_fallback import get_gemini_fallback

# ===========================
# 範例 1: 直接使用 GeminiConsultant
# ===========================

def example_direct_consultant():
    """
    直接使用 GeminiConsultant 模組的範例
    """
    print("\n=== 範例 1: 直接使用 GeminiConsultant ===")
    
    # 1. 初始化 GeminiConsultant
    consultant = get_gemini_consultant(
        model_name="gemini-1.5-flash"  # 或 "gemini-1.5-pro"
    )
    
    if not consultant.is_available():
        print("錯誤: Gemini API 未配置，請設定 GOOGLE_API_KEY")
        return
    
    # 2. 載入測試影像
    # 注意: 這裡使用假設的路徑，實際使用時請替換為真實影像路徑
    try:
        # 範例: 從檔案載入
        # image = Image.open("path/to/test_image.jpg")
        
        # 或建立一個測試影像 (實際使用時請替換)
        from PIL import Image as PILImage
        import numpy as np
        test_image = PILImage.fromarray(
            np.random.randint(0, 255, (224, 224, 3), dtype=np.uint8)
        )
        print("使用測試影像 (隨機生成)")
        
        # 3. 執行諮詢 (假設本地模型預測為 Class B，信心值 0.65)
        result = consultant.consult(
            image_input=test_image,
            local_prediction="Class B",
            local_confidence=0.65
        )
        
        # 4. 處理結果
        print(f"\nGemini 諮詢結果:")
        print(f"  類別: {result['category']}")
        print(f"  信心值: {result['confidence']:.2f}")
        print(f"  推理依據: {result['reasoning']}")
        print(f"  狀態: {result['status']}")
        print(f"  回應時間: {result.get('response_time', 0):.2f} 秒")
        
        # 5. 檢查是否需要降級策略
        if result.get("fallback", False):
            print("\n警告: 發生錯誤，建議啟動降級策略 (如提示使用者手動分類)")
        
    except Exception as e:
        print(f"錯誤: {e}")


# ===========================
# 範例 2: 整合到推論流程 (推薦方式)
# ===========================

def example_integrated_workflow(image_path: str, confidence_threshold: float = 0.8):
    """
    整合到完整推論流程的範例
    
    流程:
    1. 使用本地 EfficientNet 模型進行推論
    2. 若信心值 < threshold，啟動 Gemini 輔助諮詢
    3. 根據結果決定最終分類
    
    Args:
        image_path: 影像檔案路徑
        confidence_threshold: 觸發 Gemini 的信心值閾值
    """
    print(f"\n=== 範例 2: 整合推論流程 (閾值: {confidence_threshold}) ===")
    
    try:
        # 1. 載入影像
        image = Image.open(image_path)
        print(f"已載入影像: {image_path}")
        
        # 2. 使用本地 EfficientNet 模型推論
        vision_engine = get_vision_engine()
        local_result = vision_engine.predict(image)
        
        local_class = local_result["class"]
        local_confidence = local_result["confidence"]
        
        print(f"\n本地模型推論結果:")
        print(f"  類別: {local_class}")
        print(f"  信心值: {local_confidence:.2f}")
        
        # 3. 判斷是否需要 Gemini 輔助
        if local_confidence < confidence_threshold:
            print(f"\n本地信心值 ({local_confidence:.2f}) < 閾值 ({confidence_threshold:.2f})")
            print("啟動 Gemini 輔助諮詢...")
            
            # 使用 GeminiFallback (內部會呼叫 GeminiConsultant)
            gemini_fallback = get_gemini_fallback(confidence_threshold=confidence_threshold)
            
            gemini_result = gemini_fallback.classify_with_gemini(
                image_input=image,
                local_prediction=local_class,
                local_confidence=local_confidence
            )
            
            print(f"\nGemini 輔助諮詢結果:")
            print(f"  類別: {gemini_result['class']}")
            print(f"  信心值: {gemini_result['confidence']:.2f}")
            print(f"  推理依據: {gemini_result['reasoning']}")
            print(f"  狀態: {gemini_result['status']}")
            
            # 4. 決策邏輯: 優先採用 Gemini 結果 (因為本地信心值低)
            if gemini_result["status"] == "success":
                final_class = gemini_result["class"]
                final_confidence = gemini_result["confidence"]
                print(f"\n最終決策: 採用 Gemini 結果")
            else:
                # Gemini 失敗，使用本地結果 (降級策略)
                final_class = local_class
                final_confidence = local_confidence
                print(f"\n最終決策: Gemini 失敗，採用本地結果 (降級策略)")
        else:
            # 本地信心值足夠，直接使用本地結果
            final_class = local_class
            final_confidence = local_confidence
            print(f"\n本地信心值足夠，直接採用本地結果")
        
        print(f"\n=== 最終分類結果 ===")
        print(f"類別: {final_class}")
        print(f"信心值: {final_confidence:.2f}")
        
        return {
            "class": final_class,
            "confidence": final_confidence,
            "source": "gemini" if local_confidence < confidence_threshold else "local"
        }
        
    except FileNotFoundError:
        print(f"錯誤: 找不到影像檔案: {image_path}")
    except Exception as e:
        print(f"錯誤: {e}")


# ===========================
# 範例 3: 錯誤處理與降級策略
# ===========================

def example_error_handling():
    """
    示範錯誤處理與降級策略
    """
    print("\n=== 範例 3: 錯誤處理與降級策略 ===")
    
    consultant = get_gemini_consultant()
    
    if not consultant.is_available():
        print("Gemini API 未配置，無法執行範例")
        return
    
    # 模擬一個 API 錯誤情境 (實際使用時會自動處理)
    print("\n當 Gemini API 發生錯誤時:")
    print("1. 檢查 result['status'] 是否為 'success'")
    print("2. 檢查 result.get('fallback', False) 是否為 True")
    print("3. 根據錯誤類型決定降級策略:")
    print("   - timeout: 提示使用者稍後再試")
    print("   - network_error: 檢查網路連線")
    print("   - quota_exceeded: 提示 API 配額已用完")
    print("   - 其他錯誤: 使用本地模型結果或提示手動分類")
    
    # 範例: 檢查結果並決定降級策略
    def handle_gemini_result(result: dict, local_result: dict) -> dict:
        """
        處理 Gemini 結果並決定降級策略
        """
        if result["status"] == "success":
            return {
                "class": result["category"],
                "confidence": result["confidence"],
                "source": "gemini"
            }
        else:
            # 降級策略: 使用本地結果
            print(f"\n降級策略: 使用本地模型結果")
            return {
                "class": local_result["class"],
                "confidence": local_result["confidence"],
                "source": "local_fallback",
                "gemini_error": result["status"]
            }
    
    print("\n降級策略函式已定義，可在實際流程中使用")


# ===========================
# 主程式
# ===========================

if __name__ == "__main__":
    print("=" * 60)
    print("Gemini 輔助諮詢模組整合範例")
    print("=" * 60)
    
    # 檢查環境變數
    if not os.getenv("GOOGLE_API_KEY"):
        print("\n警告: 未設定 GOOGLE_API_KEY 環境變數")
        print("請在 .env 檔案中設定，或使用以下指令:")
        print("  export GOOGLE_API_KEY=your_api_key_here")
        print("\n範例將無法實際呼叫 Gemini API，但可以展示流程")
    
    # 執行範例 1
    try:
        example_direct_consultant()
    except Exception as e:
        print(f"範例 1 執行錯誤: {e}")
    
    # 執行範例 2 (需要實際影像檔案)
    # 取消註解以下程式碼並提供影像路徑以執行
    # example_integrated_workflow("path/to/your/image.jpg", confidence_threshold=0.8)
    
    # 執行範例 3
    example_error_handling()
    
    print("\n" + "=" * 60)
    print("範例執行完成")
    print("=" * 60)
