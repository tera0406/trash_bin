/**
 * Servo & Sensor Configuration - 伺服馬達與感測器參數設定
 * 對應計畫書:
 * * 職責:
 * - 定義 2-DOF 雲台的 Pitch/Yaw 伺服馬達參數
 * - 定義 HX711 重量感測器與紅外線（IR）對射感測器接腳
 * - 設定角度範圍、速度限制、安全檢查
 */

#ifndef SERVO_CONFIG_H
#define SERVO_CONFIG_H

// ==================== 硬體接腳定義 ====================
#define SERVO_PITCH_PIN 18  // Pitch 軸伺服馬達 GPIO 接腳
#define SERVO_YAW_PIN 19     // Yaw 軸伺服馬達 GPIO 接腳

// HX711 重量感測器接腳
#define HX711_DOUT_PIN 17    // HX711 資料輸出 (DOUT)
#define HX711_SCK_PIN 16     // HX711 時脈輸入 (SCK)

// 紅外線對射感測器接腳 (新增：由 Core 0 獨立驅動)
#define IR_TX_PIN 25         // 紅外線發射端 SIG (38kHz 硬體載波)
#define IR_RX_PIN 14         // 紅外線接收端 SIG (高速中斷/輪詢)


// ==================== 角度範圍限制 ====================
// 對應計畫書:
#define PITCH_MIN_ANGLE 45.0   // Pitch 最小角度 (度) [-θp]
#define PITCH_MAX_ANGLE 135.0  // Pitch 最大角度 (度) [+θp]
#define PITCH_NEUTRAL 90.0     // Pitch 中立角度

#define YAW_MIN_ANGLE 0.0      // Yaw 最小角度 (度) [-θy]
#define YAW_MAX_ANGLE 180.0    // Yaw 最大角度 (度) [+θy] (270°Servo: write(180)=物理270°)
#define YAW_NEUTRAL 60.0       // Yaw 中立角度 (270°Servo: write(60)=物理90°)

// ==================== 速度限制 ====================
// 對應計畫書:
#define MAX_ANGULAR_VELOCITY 200.0  // 最大角速度 (度/秒)
#define MOVEMENT_TIMEOUT_MS 5000    // 移動超時時間 (毫秒)

// ==================== 安全檢查 ====================
// 對應計畫書:
#define ENABLE_SAFETY_CHECKS true   // 啟用安全檢查
#define AUTO_RETURN_TO_NEUTRAL true  // 自動回歸中立姿態

// ==================== 錯誤碼定義 ====================
// 對應計畫書:
#define ERR_CODE_OK 0
#define ERR_CODE_INVALID_ANGLE 1
#define ERR_CODE_TIMEOUT 2
#define ERR_CODE_SAFETY_LIMIT 3
#define ERR_CODE_UART_ERROR 4

// ==================== 紅外線對射消抖參數 ====================
#define IR_GAP_THRESHOLD_MS 30      // 單次無信號判定門檻 (毫秒)，大於此值視為瞬時中斷
#define IR_BLOCK_DEBOUNCE_MS 80     // 遮擋確認持續時間 (毫秒)，連續無信號超過此時間才判定為物理遮擋
#define IR_CLEAR_DEBOUNCE_MS 200    // 恢復確認持續時間 (毫秒)，連續穩定有信號超過此時間才判定為恢復

#endif // SERVO_CONFIG_H