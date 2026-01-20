# Python 虛擬環境 (Virtual Environment) 說明

## 什麼是 `.venv`？

`.venv` 是一個 **Python 虛擬環境 (Virtual Environment)** 的資料夾，用來隔離專案的 Python 套件依賴。

## 為什麼需要虛擬環境？

### 問題情境

假設你的電腦上有多個 Python 專案：
- 專案 A 需要 TensorFlow 2.10
- 專案 B 需要 TensorFlow 2.13
- 專案 C 需要 TensorFlow 1.15

如果所有專案共用同一個 Python 環境，就會發生**版本衝突**！

### 解決方案

虛擬環境讓每個專案有**獨立的 Python 環境**：
- 專案 A 的 `.venv/` → 安裝 TensorFlow 2.10
- 專案 B 的 `.venv/` → 安裝 TensorFlow 2.13
- 專案 C 的 `.venv/` → 安裝 TensorFlow 1.15

彼此互不干擾！

## 如何使用虛擬環境？

### 1. 建立虛擬環境

```bash
# 在專案根目錄執行
python -m venv .venv
```

這會建立一個 `.venv/` 資料夾，裡面包含：
- Python 直譯器副本
- pip (套件管理工具)
- 獨立的套件安裝目錄

### 2. 啟動虛擬環境

**Windows (PowerShell):**
```powershell
.venv\Scripts\Activate.ps1
```

**Windows (CMD):**
```cmd
.venv\Scripts\activate.bat
```

**Linux/macOS:**
```bash
source .venv/bin/activate
```

啟動後，命令提示字元前面會出現 `(.venv)` 標記：
```
(.venv) C:\Users\User\smart_trash_bin_pc>
```

### 3. 安裝套件

在虛擬環境啟動後，安裝的套件只會安裝到 `.venv/` 中：

```bash
pip install -r requirements.txt
```

### 4. 停用虛擬環境

```bash
deactivate
```

## 專案中的使用方式

### 建議工作流程

1. **建立虛擬環境** (只需要做一次)
   ```bash
   python -m venv .venv
   ```

2. **啟動虛擬環境** (每次開發前)
   ```powershell
   .venv\Scripts\Activate.ps1
   ```

3. **安裝依賴**
   ```bash
   pip install -r requirements.txt
   ```

4. **執行專案**
   ```bash
   python src/main_server.py
   ```

5. **停用虛擬環境** (結束開發時)
   ```bash
   deactivate
   ```

## 為什麼 `.venv/` 不應該上傳到 Git？

`.venv/` 資料夾通常很大 (可能幾百 MB 到幾 GB)，而且：
- 每個人的作業系統不同，虛擬環境內容也不同
- 可以透過 `requirements.txt` 重新建立
- 上傳到 Git 會讓 Repository 變得非常龐大

因此，`.venv/` 已經被加入 `.gitignore`，不會被 Git 追蹤。

## 常見問題

### Q: 如果刪除了 `.venv/` 怎麼辦？

A: 沒問題！重新建立即可：
```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Q: 如何確認虛擬環境已啟動？

A: 檢查命令提示字元前面是否有 `(.venv)` 標記，或執行：
```bash
which python  # Linux/macOS
where python   # Windows
```
應該會指向 `.venv/` 目錄中的 Python。

### Q: VS Code 如何自動使用虛擬環境？

A: VS Code 通常會自動偵測 `.venv/`，如果沒有：
1. 按 `Ctrl+Shift+P`
2. 輸入 "Python: Select Interpreter"
3. 選擇 `.venv\Scripts\python.exe`

## 總結

- ✅ `.venv/` = 專案的獨立 Python 環境
- ✅ 避免不同專案之間的套件衝突
- ✅ 已經加入 `.gitignore`，不會上傳到 Git
- ✅ 可以隨時刪除並重新建立
