# SA Tools Menu (GTA SA Styled)

This project is a collection of web-based tools with a **GTA San Andreas (PC) inspired menu design**.  
It contains several main features:

---

## 🎮 Main Menu
- **Select Tools** → access the available tools.  
- **Options** → configure Audio (On/Off) and Volume.  
- **Credits** → developer & contributor information.  

Navigation uses sound effects `select.mp3` and `back.mp3`.  
All audio is synced with **Options** (saved in `localStorage` for toggle and volume).

---

## 🛠 Tools

### 1. Transparent Image
- Feature to **upload single images or batch archives**:  
  - `.zip`  
  - `.rar`  
  - `.7z`  
- Can handle hundreds of images at once.  
- The script extracts/reads archive contents and displays images with a **transparent layer effect**.  
- Background music **`transparant_image.mp3`** automatically plays (synced with Options).  

### 2. Crashlog Reader
- Feature to read **`aml_crashlog.txt`** (GTA SA Android crash logs).  
- The crashlog is parsed and compared with **Crash_List - 2.00.txt** or the Indonesian version.  
- Output displays categorized information:
  - **Error** → crash code.  
  - **Problem** → cause of the issue.  
  - **Solution** → suggested fix.  
  - **Note** → extra information.  
- Supports color highlighting, fade animations, back button, and rotating logo.  

---

## ⚙️ Options
- **Audio Toggle** → On/Off (stored in `localStorage`).  
- **Volume Control** → adjustable bar with 8 levels.  
- All audio (`select.mp3`, `back.mp3`, `transparant_image.mp3`) follow the Options settings.

---

## 🚀 Usage
1. Clone this repo.  
2. Open `index.html` in your browser.  
3. (Optional) Deploy with GitHub Pages for online access.  
4. Upload files depending on the tool:  
   - `Transparent Image` → upload images or archives (zip/rar/7z).  
   - `Crashlog Reader` → upload the **`aml_crashlog.txt`** file.  

---

## 📂 Structure

---

## 👨‍💻 Credits
- **TWSVN** → Main developer of this project.  
- **ARM** → Original Crashlist creator.  
- **TWSVN** → Crashlist Indonesian translation.  
- **Killman / RusJJ** → Android Mod Loader (AML).  

---
