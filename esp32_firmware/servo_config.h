/**
 * Servo Configuration - 伺服馬達參數設定
 * 對應計畫書: [cite: 146, 148, 149, 150, 153, 154, 155, 156]
 * 
 * 職責:
 * - 定義 2-DOF 雲台的 Pitch/Yaw 伺服馬達參數
 * - 設定角度範圍、速度限制、安全檢查
 */

#ifndef SERVO_CONFIG_H
#define SERVO_CONFIG_H

// ==================== 硬體接腳定義 ====================
#define SERVO_PITCH_PIN 18  // Pitch 軸伺服馬達 GPIO 接腳
#define SERVO_YAW_PIN 19     // Yaw 軸伺服馬達 GPIO 接腳

// ==================== 角度範圍限制 ====================
// 對應計畫書: [cite: 149, 150, 153, 154, 155, 156]
#define PITCH_MIN_ANGLE -45.0   // Pitch 最小角度 (度) [-θp]
#define PITCH_MAX_ANGLE 45.0    // Pitch 最大角度 (度) [+θp]
#define PITCH_NEUTRAL 0.0       // Pitch 中立角度

#define YAW_MIN_ANGLE -90.0     // Yaw 最小角度 (度) [-θy]
#define YAW_MAX_ANGLE 90.0      // Yaw 最大角度 (度) [+θy]
#define YAW_NEUTRAL 0.0         // Yaw 中立角度

// ==================== 速度限制 ====================
// 對應計畫書: [cite: 111, 151, 323]
#define MAX_ANGULAR_VELOCITY 30.0  // 最大角速度 (度/秒)
#define MOVEMENT_TIMEOUT_MS 5000    // 移動超時時間 (毫秒)

// ==================== 安全檢查 ====================
// 對應計畫書: [cite: 111, 151, 323]
#define ENABLE_SAFETY_CHECKS true   // 啟用安全檢查
#define AUTO_RETURN_TO_NEUTRAL true  // 自動回歸中立姿態

// ==================== 傾倒動作參數 ====================
// 對應計畫書: [cite: 157, 394]
#define DUMP_ANGLE_PITCH 45.0        // 傾倒時的 Pitch 角度
#define DUMP_ANGLE_YAW 0.0           // 傾倒時的 Yaw 角度
#define DUMP_HOLD_TIME_MS 2000      // 傾倒保持時間 (毫秒)

// ==================== 錯誤碼定義 ====================
// 對應計畫書: [cite: 112, 117]
#define ERR_CODE_OK 0
#define ERR_CODE_INVALID_ANGLE 1
#define ERR_CODE_TIMEOUT 2
#define ERR_CODE_SAFETY_LIMIT 3
#define ERR_CODE_UART_ERROR 4

#endif // SERVO_CONFIG_H
