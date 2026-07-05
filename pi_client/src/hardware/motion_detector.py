# -*- coding: utf-8 -*-
"""
AIOT 智慧垃圾桶 - 影像動態偵測器模組 (Frame Differencing Motion Detector)
"""
import os
import sys
import numpy as np

# pyrefly: ignore [missing-import]
import cv2

# 匯入系統設定
try:
    from config import DETECTION_RESOLUTION, FRAME_DIFF_THRESHOLD, PIXEL_DIFF_THRESHOLD
except ImportError:
    parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    from config import DETECTION_RESOLUTION, FRAME_DIFF_THRESHOLD, PIXEL_DIFF_THRESHOLD


class MotionDetector:
    """
    使用幀差法 (Frame Differencing) 進行超輕量動態偵測。

    原理:
      將連續兩幀影像轉灰階 → 相減取絕對值 → 二值化 →
      計算白色(有變化)像素佔比 → 若超過門檻則判定為「有動靜」

    限制:
      - 靜止的物體不會被偵測 (因為幀差為零)
      - 光線劇烈變化會誤判 (建議搭配重量感測器確認)
    """

    def __init__(self, resolution=DETECTION_RESOLUTION):
        """
        Args:
            resolution: 幀差計算用的降採樣解析度 (寬, 高)
                        越小越快，但太小會失去細節
        """
        # 前一幀的灰階影像 (初始為 None，第一幀不做偵測)
        self.prev_gray = None

        # 降採樣的目標解析度
        self.resolution = resolution

        # 總像素數 (用於計算變化佔比)
        self.total_pixels = resolution[0] * resolution[1]

    def reset(self):
        """
        重置前一幀基準。
        當狀態機重回 IDLE 時呼叫此函式，使下一次影像比較重新建立基準，
        避免因為冷卻時間（COOLDOWN）期間的光影變化或舵機關蓋動作造成瞬間差值過大而誤觸發。
        """
        self.prev_gray = None

    def detect(self, frame: np.ndarray) -> tuple:
        """
        輸入一幀彩色影像，回傳是否偵測到動態以及變化比例。

        處理流程:
          1. 將輸入影像縮小到 detection_resolution (降低計算量)
          2. 轉換為灰階 (因為我們只關心亮度變化，不關心顏色)
          3. 與前一幀做差分 → 取絕對值 → 得到「差異圖」
          4. 對差異圖做二值化 (超過 PIXEL_DIFF_THRESHOLD 的像素 = 白色)
          5. 計算白色像素佔總像素的比例
          6. 比例 > FRAME_DIFF_THRESHOLD → 判定為「有動靜」

        Args:
            frame: BGR 格式的彩色影像 (直接從相機取得)

        Returns:
            (is_motion: bool, change_ratio: float)
            is_motion:    是否偵測到動態
            change_ratio: 變化像素佔比 (0.0 ~ 1.0)，可用於 debug 調參
        """
        # Step 1: 降採樣到偵測解析度
        small = cv2.resize(frame, self.resolution)

        # Step 2: 轉灰階
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

        # Step 3: 高斯模糊去除相機感測器的隨機雜訊
        # (21, 21) 是模糊核大小，越大去噪越強但也越糊
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        # 第一幀: 只儲存，不做偵測 (因為沒有前一幀可以比較)
        if self.prev_gray is None:
            self.prev_gray = gray
            return (False, 0.0)

        # Step 4: 計算兩幀的絕對差異
        diff = cv2.absdiff(self.prev_gray, gray)

        # Step 5: 二值化
        # 差異值 > PIXEL_DIFF_THRESHOLD → 白色 (255，有變化)
        # 差異值 ≤ PIXEL_DIFF_THRESHOLD → 黑色 (0，無變化)
        _, thresh = cv2.threshold(diff, PIXEL_DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)

        # Step 6: 計算變化像素佔比
        changed_pixels = cv2.countNonZero(thresh)
        change_ratio = changed_pixels / self.total_pixels

        # Step 7: 更新前一幀 (為下次偵測做準備)
        self.prev_gray = gray

        # Step 8: 判定是否超過門檻
        is_motion = change_ratio > FRAME_DIFF_THRESHOLD

        return (is_motion, change_ratio)
