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
#include "HX711.h"
#include "servo_config.h"

// ==================== 全域變數 ====================
Servo servo_pitch;  // Pitch 軸伺服馬達
Servo servo_yaw;    // Yaw 軸伺服馬達

// 新增: 紅外線感測器狀態與 FreeRTOS 句柄 (由 Core 0 獨立驅動)
volatile bool ir_in_blocked = false;
TaskHandle_t irTaskHandle = NULL;

// 新增: 可透過 UART 動態調校的紅外線消抖參數
volatile unsigned long ir_gap_threshold_ms = IR_GAP_THRESHOLD_MS;
volatile unsigned long ir_block_debounce_ms = IR_BLOCK_DEBOUNCE_MS;
volatile unsigned long ir_clear_debounce_ms = IR_CLEAR_DEBOUNCE_MS;

float pitch_neutral = PITCH_NEUTRAL;
float current_pitch = pitch_neutral;
float current_yaw = YAW_NEUTRAL;

unsigned long last_command_time = 0;
bool is_moving = false;

// HX711 重量感測器
HX711 scale;

// ==================== 函數宣告 ====================
void setup();
void loop();
void parse_uart_command(String command);
void move_servo(float pitch, float yaw);
bool validate_angles(float pitch, float yaw);
void return_to_neutral();
void send_response(String response);
int get_error_code(String error_msg);
void irSensorTask(void *pvParameters);

// ==================== 初始化 ====================
void setup() {
  // 初始化序列埠 (UART)
  Serial.begin(115200);
  Serial.setTimeout(100);  // 100ms 超時
  delay(1000);
  
  // ── HX711 重量感測器 (優先初始化，讓 ADC 有時間穩定) ──
  Serial.println("[ESP32] 正在初始化 HX711 重量感測器...");
  scale.begin(HX711_DOUT_PIN, HX711_SCK_PIN);
  if (scale.wait_ready_timeout(5000)) {  // 等待最多 5 秒
    delay(500);       // 額外等待 ADC 穩定
    scale.set_scale(); // 清除比例係數 (回傳原始值)
    scale.tare();      // 歸零
    Serial.println("[ESP32] HX711 已就緒並歸零");
  } else {
    Serial.println("[ESP32] 警告: HX711 未就緒，重量功能可能無法使用");
    Serial.println("[ESP32] 請檢查 HX711 接線 (DOUT=GPIO17, SCK=GPIO16)");
  }

  // 配置 PWM 頻率 (標準 Servo 為 50Hz) [Fix: Explicit Configuration]
  servo_pitch.setPeriodHertz(50);
  servo_yaw.setPeriodHertz(50);

  // 初始化伺服馬達 (使用標準脈寬 1000-2000us)
  servo_pitch.attach(SERVO_PITCH_PIN, 500, 2500);
  servo_yaw.attach(SERVO_YAW_PIN, 500, 2500);
  
  // 強制寫入中立角度以確保開機復位
  servo_pitch.write((int)pitch_neutral);
  servo_yaw.write((int)YAW_NEUTRAL);
  current_pitch = pitch_neutral;
  current_yaw = YAW_NEUTRAL;
  delay(500);
  
  // 發送就緒訊號
  send_response("READY");
  
  // ── 新增: 紅外線對射感測器任務 (建立在 Core 0 上) ──
  Serial.println("[ESP32] 正在啟動 Core 0 紅外線感測器任務...");
  xTaskCreatePinnedToCore(
    irSensorTask,
    "IRSensorTask",
    4096,
    NULL,
    1,
    &irTaskHandle,
    0
  );
  
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
        send_response("ACK");
        move_servo(pitch, yaw);
      } else {
        send_response("ERR:INVALID_ANGLE");
      }
    } else {
      send_response("ERR:PARSE_ERROR");
    }
  }
  else if (command.startsWith("SET_NEUTRAL:P:")) {
    int p_start = command.indexOf("P:") + 2;
    if (p_start > 1) {
      float new_neutral = command.substring(p_start).toFloat();
      if (new_neutral >= PITCH_MIN_ANGLE && new_neutral <= PITCH_MAX_ANGLE) {
        pitch_neutral = new_neutral;
        send_response("ACK");
        // 如果目前處於空閒，可自動微調到新水平面
        if (abs(current_pitch - pitch_neutral) > 0.5 && !is_moving) {
          move_servo(pitch_neutral, current_yaw);
        }
      } else {
        send_response("ERR:INVALID_ANGLE");
      }
    } else {
      send_response("ERR:PARSE_ERROR");
    }
  }
  else if (command == "RESET") {
    // 重置指令: 回歸中立姿態 [cite: 111, 151, 323]
    send_response("ACK");
    return_to_neutral();
  }
  else if (command == "GET_IR") {
    // 查詢紅外線感測器狀態
    String resp = "IR:IN:" + String(ir_in_blocked ? 1 : 0);
    send_response(resp);
  }
  else if (command == "STATUS") {
    // 狀態查詢
    String status = "STATUS:P:" + String(current_pitch) + ":Y:" + String(current_yaw);
    send_response(status);
  }
  else if (command == "GET_WEIGHT") {
    // 重量查詢: 讀取 HX711 原始值 (取 5 次平均)
    if (scale.is_ready()) {
      long reading = scale.get_units(5);
      String resp = "WEIGHT:" + String(reading);
      send_response(resp);
    } else {
      send_response("ERR:HX711_NOT_READY");
    }
  }
  else if (command == "TARE") {
    // 重量歸零: 重新校準零點
    if (scale.is_ready()) {
      scale.tare();
      send_response("ACK:TARE_DONE");
    } else {
      send_response("ERR:HX711_NOT_READY");
    }
  }
  else if (command.startsWith("SET_IR_PARAM:")) {
    int g_idx = command.indexOf("G:");
    int b_idx = command.indexOf(":B:");
    int c_idx = command.indexOf(":C:");
    
    if (g_idx >= 0 && b_idx > g_idx && c_idx > b_idx) {
      unsigned long gap = command.substring(g_idx + 2, b_idx).toInt();
      unsigned long block = command.substring(b_idx + 3, c_idx).toInt();
      unsigned long clear = command.substring(c_idx + 3).toInt();
      
      // 合理性驗證，避免極端參數鎖死或溢位
      if (gap >= 5 && gap <= 500 && block >= 10 && block <= 2000 && clear >= 10 && clear <= 2000) {
        ir_gap_threshold_ms = gap;
        ir_block_debounce_ms = block;
        ir_clear_debounce_ms = clear;
        send_response("ACK");
      } else {
        send_response("ERR:INVALID_PARAM");
      }
    } else {
      send_response("ERR:PARSE_ERROR");
    }
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
  
  is_moving = true;
  last_command_time = millis();
  
  // 計算每度移動所需延遲時間 (基於最大角速度)
  int step_delay = (int)(1000.0 / MAX_ANGULAR_VELOCITY);
  if (step_delay < 10) step_delay = 10; // 保證基本的 PWM 反應時間
  if (step_delay > 50) step_delay = 50; // 限制最大延遲避免過慢

  // 決定移動順序以防止卡住或垃圾潑灑：
  // 1. 如果目標是傾倒 (pitch != pitch_neutral)，先 Yaw 水平旋轉到定位，再 Pitch 頃倒
  // 2. 如果目標是歸位/復位 (pitch == pitch_neutral)，先 Pitch 復位回水平，再 Yaw 旋轉回中立
  if (pitch != pitch_neutral) {
    Serial.println("[Debug] Sequence: Yaw -> Pitch (Dumping)");
    
    // 1. Yaw smooth move
    int yaw_start = (int)current_yaw;
    int yaw_target = (int)yaw;
    int yaw_steps = abs(yaw_target - yaw_start);
    if (yaw_steps > 0) {
      for (int i = 1; i <= yaw_steps; i++) {
        float t = (float)i / yaw_steps;
        int val = yaw_start + (int)((yaw_target - yaw_start) * t);
        servo_yaw.write(val);
        delay(step_delay);
      }
      servo_yaw.write(yaw_target);
      delay(100);
    }
    current_yaw = yaw;

    // 2. Pitch smooth move
    int pitch_start = (int)current_pitch;
    int pitch_target = (int)pitch;
    int pitch_steps = abs(pitch_target - pitch_start);
    if (pitch_steps > 0) {
      for (int i = 1; i <= pitch_steps; i++) {
        float t = (float)i / pitch_steps;
        int val = pitch_start + (int)((pitch_target - pitch_start) * t);
        servo_pitch.write(val);
        delay(step_delay);
      }
      servo_pitch.write(pitch_target);
      delay(100);
    }
    current_pitch = pitch;
  } else {
    Serial.println("[Debug] Sequence: Pitch -> Yaw (Resetting)");
    
    // 1. Pitch smooth move
    int pitch_start = (int)current_pitch;
    int pitch_target = (int)pitch;
    int pitch_steps = abs(pitch_target - pitch_start);
    if (pitch_steps > 0) {
      for (int i = 1; i <= pitch_steps; i++) {
        float t = (float)i / pitch_steps;
        int val = pitch_start + (int)((pitch_target - pitch_start) * t);
        servo_pitch.write(val);
        delay(step_delay);
      }
      servo_pitch.write(pitch_target);
      delay(100);
    }
    current_pitch = pitch;

    // 2. Yaw smooth move
    int yaw_start = (int)current_yaw;
    int yaw_target = (int)yaw;
    int yaw_steps = abs(yaw_target - yaw_start);
    if (yaw_steps > 0) {
      for (int i = 1; i <= yaw_steps; i++) {
        float t = (float)i / yaw_steps;
        int val = yaw_start + (int)((yaw_target - yaw_start) * t);
        servo_yaw.write(val);
        delay(step_delay);
      }
      servo_yaw.write(yaw_target);
      delay(100);
    }
    current_yaw = yaw;
  }
  
  is_moving = false;
  
  // 發送完成訊號
  send_response("DONE");
}

// ==================== 角度驗證 ====================
bool validate_angles(float pitch, float yaw) {
  // 對應計畫書: [cite: 149, 150, 153, 154, 155, 156]
  
  // 動態調整 Pitch 的極限值以配合 dynamic pitch_neutral 偏置
  float dynamic_pitch_min = PITCH_MIN_ANGLE + (pitch_neutral - PITCH_NEUTRAL);
  float dynamic_pitch_max = PITCH_MAX_ANGLE + (pitch_neutral - PITCH_NEUTRAL);
  
  if (pitch < dynamic_pitch_min || pitch > dynamic_pitch_max) {
    return false;
  }
  
  // 伺服馬達硬體物理限制 (0-180)
  if (pitch < 0.0 || pitch > 180.0) {
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
    move_servo(pitch_neutral, YAW_NEUTRAL);
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

// ==================== Core 0 獨立紅外線驅動任務 ====================
void irSensorTask(void *pvParameters) {
  (void) pvParameters;
  
  // 設定接收端為上拉輸入
  pinMode(IR_RX_PIN, INPUT_PULLUP);
  
  // 設置晶片硬體 PWM 產生 38000 Hz 載波
  ledcAttach(IR_TX_PIN, 38000, 8);
  
  unsigned long lastLowTimeIn = millis();
  unsigned long lastGapTime = millis();
  unsigned long lastToggleTime = 0;
  bool txState = false;
  
  Serial.println("[IR Core 0] 任務啟動，硬體雙向消抖載波已就緒");
  
  while (true) {
    unsigned long currentMillis = millis();
    
    // 1. 產生 2ms 間歇脈衝以防止接收端 AGC 自適應濾除
    if (currentMillis - lastToggleTime >= 2) {
      lastToggleTime = currentMillis;
      txState = !txState;
      if (txState) {
        ledcWrite(IR_TX_PIN, 127); // 50% 佔空比
      } else {
        ledcWrite(IR_TX_PIN, 0);
      }
    }
    
    // 2. 檢測接收端電平 (對射對齊無遮擋時會隨發射脈衝頻繁出現 LOW)
    if (digitalRead(IR_RX_PIN) == LOW) {
      lastLowTimeIn = currentMillis;
    }
    
    // 3. 紀錄上一次出現訊號中斷 (大於設定門檻無訊號) 的時間
    if (currentMillis - lastLowTimeIn > ir_gap_threshold_ms) {
      lastGapTime = currentMillis;
    }
    
    // 4. 垃圾輸入紅外線雙向狀態消抖判斷
    if (!ir_in_blocked) {
      // 當前為未遮擋狀態：需要「持續無信號達 Block 門檻」才判定為物理遮擋
      if (currentMillis - lastLowTimeIn > ir_block_debounce_ms) {
        ir_in_blocked = true;
        Serial.println("EVENT:INPUT_BLOCKED");
      }
    } else {
      // 當前為遮擋狀態：需要「信號回歸穩定持續達 Clear 門檻 (期間無任何 Gap)」才判定為恢復未遮擋
      if (currentMillis - lastGapTime > ir_clear_debounce_ms) {
        ir_in_blocked = false;
        Serial.println("EVENT:INPUT_CLEARED");
      }
    }
    
    // 釋放執行時間並餵狗
    delay(1);
  }
}
