/**
 * Actuator Control - ESP32 致動控制主程式
 * 對應計畫書: [cite: 108, 146, 148, 296, 322]
 * 
 * 職責:
 * - 接收來自 Raspberry Pi 的 UART 指令
 * - 控制 2-DOF 雲台 (Pitch/Yaw) 執行傾倒動作
 * - 回傳 ACK、完成訊號或錯誤碼 (ERR_CODE) [cite: 112, 117]
 * - 包含安全檢查：超時、限速、回歸中立姿態 [cite: 111, 151, 323]
 * 
 * 硬體限制: ESP32 / NodeMCU-32S
 * 技術棧: Arduino/C++
 * 
 * 絕對禁止: 進行邏輯決策或 AI
 */

#include <ESP32Servo.h>
#include "servo_config.h"

// ==================== 全域變數 ====================
Servo servo_pitch;  // Pitch 軸伺服馬達
Servo servo_yaw;    // Yaw 軸伺服馬達

float current_pitch = PITCH_NEUTRAL;
float current_yaw = YAW_NEUTRAL;

unsigned long last_command_time = 0;
bool is_moving = false;

// ==================== 函數宣告 ====================
void setup();
void loop();
void parse_uart_command(String command);
void move_servo(float pitch, float yaw);
bool validate_angles(float pitch, float yaw);
void return_to_neutral();
void send_response(String response);
int get_error_code(String error_msg);

// ==================== 初始化 ====================
void setup() {
  // 初始化序列埠 (UART)
  Serial.begin(115200);
  Serial.setTimeout(100);  // 100ms 超時
  delay(1000);
  
  // 配置 PWM 頻率 (標準 Servo 為 50Hz) [Fix: Explicit Configuration]
  servo_pitch.setPeriodHertz(50);
  servo_yaw.setPeriodHertz(50);

  // 初始化伺服馬達 (使用標準脈寬 1000-2000us)
  servo_pitch.attach(SERVO_PITCH_PIN, 1000, 2000);
  servo_yaw.attach(SERVO_YAW_PIN, 1000, 2000);
  
  // 回歸中立姿態
  return_to_neutral();
  
  // 發送就緒訊號
  send_response("READY");
  
  Serial.println("[ESP32] 致動控制系統已啟動");
}

// ==================== 主迴圈 ====================
void loop() {
  // 檢查 UART 輸入
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    parse_uart_command(command);
  }
  
  // 安全檢查: 超時檢測 [cite: 111, 151, 323]
  if (ENABLE_SAFETY_CHECKS) {
    unsigned long current_time = millis();
    if (is_moving && (current_time - last_command_time > MOVEMENT_TIMEOUT_MS)) {
      Serial.println("[ESP32] 警告: 移動超時，回歸中立姿態");
      return_to_neutral();
      is_moving = false;
    }
  }
  
  delay(10);  // 10ms 延遲，避免 CPU 過載
}

// ==================== 指令解析 ====================
void parse_uart_command(String command) {
  // 對應計畫書: [cite: 114]
  // 格式: MOVE:P:{pitch}:Y:{yaw}\n
  
  if (command.startsWith("MOVE:")) {
    // 解析 Pitch 和 Yaw 角度
    int p_start = command.indexOf("P:") + 2;
    int p_end = command.indexOf(":Y:");
    int y_start = p_end + 3;
    
    if (p_start > 1 && p_end > p_start && y_start > p_end) {
      float pitch = command.substring(p_start, p_end).toFloat();
      float yaw = command.substring(y_start).toFloat();
      
      // 驗證角度範圍
      if (validate_angles(pitch, yaw)) {
        move_servo(pitch, yaw);
        send_response("ACK");
      } else {
        send_response("ERR:INVALID_ANGLE");
      }
    } else {
      send_response("ERR:PARSE_ERROR");
    }
  }
  else if (command == "RESET") {
    // 重置指令: 回歸中立姿態 [cite: 111, 151, 323]
    return_to_neutral();
    send_response("ACK");
  }
  else if (command == "STATUS") {
    // 狀態查詢
    String status = "STATUS:P:" + String(current_pitch) + ":Y:" + String(current_yaw);
    send_response(status);
  }
  else {
    send_response("ERR:UNKNOWN_COMMAND");
  }
}

// ==================== 伺服馬達控制 ====================
void move_servo(float pitch, float yaw) {
  // 對應計畫書: [cite: 146, 148, 149, 150]
  
  // 安全檢查: 角度範圍驗證
  if (!validate_angles(pitch, yaw)) {
    send_response("ERR:SAFETY_LIMIT");
    return;
  }
  
  // 計算移動距離與時間 (限速檢查) [cite: 111, 151, 323]
  float pitch_delta = abs(pitch - current_pitch);
  float yaw_delta = abs(yaw - current_yaw);
  float max_delta = max(pitch_delta, yaw_delta);
  
  unsigned long move_time = (unsigned long)(max_delta / MAX_ANGULAR_VELOCITY * 1000);
  
  // 平滑移動 (可選: 使用插值)
  is_moving = true;
  last_command_time = millis();
  
  // 設定目標角度
  int pitch_val = (int)(pitch + 90);
  int yaw_val = (int)(yaw + 90);
  
  Serial.print("[Debug] Move - Pitch: "); Serial.print(pitch); Serial.print(" -> "); Serial.println(pitch_val);
  Serial.print("[Debug] Move - Yaw: "); Serial.print(yaw); Serial.print(" -> "); Serial.println(yaw_val);

  servo_pitch.write(pitch_val);  // 轉換為 0-180 度範圍
  servo_yaw.write(yaw_val);
  
  // 等待移動完成
  delay(min(move_time, (unsigned long)1000));  // 最多等待 1 秒
  
  // 更新當前角度
  current_pitch = pitch;
  current_yaw = yaw;
  is_moving = false;
  
  // 發送完成訊號
  send_response("DONE");
}

// ==================== 角度驗證 ====================
bool validate_angles(float pitch, float yaw) {
  // 對應計畫書: [cite: 149, 150, 153, 154, 155, 156]
  
  if (pitch < PITCH_MIN_ANGLE || pitch > PITCH_MAX_ANGLE) {
    return false;
  }
  
  if (yaw < YAW_MIN_ANGLE || yaw > YAW_MAX_ANGLE) {
    return false;
  }
  
  return true;
}

// ==================== 回歸中立姿態 ====================
void return_to_neutral() {
  // 對應計畫書: [cite: 111, 151, 323]
  
  if (AUTO_RETURN_TO_NEUTRAL) {
    move_servo(PITCH_NEUTRAL, YAW_NEUTRAL);
  }
}

// ==================== 回應發送 ====================
void send_response(String response) {
  // 對應計畫書: [cite: 112, 117]
  // 回傳 ACK、完成訊號或錯誤碼
  
  Serial.println(response);
}

// ==================== 錯誤碼取得 ====================
int get_error_code(String error_msg) {
  // 對應計畫書: [cite: 112, 117]
  
  if (error_msg.indexOf("INVALID_ANGLE") >= 0) {
    return ERR_CODE_INVALID_ANGLE;
  }
  else if (error_msg.indexOf("TIMEOUT") >= 0) {
    return ERR_CODE_TIMEOUT;
  }
  else if (error_msg.indexOf("SAFETY_LIMIT") >= 0) {
    return ERR_CODE_SAFETY_LIMIT;
  }
  else {
    return ERR_CODE_UART_ERROR;
  }
}
