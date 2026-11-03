# Contributing to FanLight Studio

Thank you for your interest in contributing to **FanLight Studio**! Whether you are adding support for new motherboard controllers, fixing driver quirks, designing new lighting animations, or refining the UI, your help makes Linux hardware control better for everyone.

---

## 📋 Table of Contents
1. [Code of Conduct](#code-of-conduct)
2. [How Can I Contribute?](#how-can-i-contribute)
   - [Reporting Bugs](#reporting-bugs)
   - [Adding Tested Hardware Profiles](#adding-tested-hardware-profiles)
   - [Requesting New Features](#requesting-new-features)
   - [Submitting Code Changes](#submitting-code-changes)
3. [Local Development Setup](#local-development-setup)
4. [Architecture & Guidelines](#architecture--guidelines)
5. [Testing & Hardware Verification](#testing--hardware-verification)
6. [Pull Request Process](#pull-request-process)

---

## 🤝 Code of Conduct
We are committed to providing a welcoming, respectful, and harassment-free environment for everyone. Please be considerate and respectful in all interactions across issues, pull requests, and discussions.

---

## 🛠️ How Can I Contribute?

### 1. Reporting Bugs
If you encounter hardware collisions, dark fans, RAM desync, or UI crashes:
- Check existing [GitHub Issues](https://github.com/MdSagorMunshi/fanlight-controller/issues) to see if it has already been reported.
- Open a new issue using our **Bug Report Template**.
- Include your **motherboard model**, **BIOS version**, **Linux distribution**, and kernel output from:
  ```bash
  cat /sys/class/dmi/id/board_name
  ls -l /dev/hidraw*
  dmesg | grep -iE "(hid|0db0|rgb)"
  ```

### 2. Adding Tested Hardware Profiles
Have you verified FanLight Studio on another MSI motherboard model, ARGB controller, or DDR5/DDR4 RAM kit?
- Open an issue using the **Hardware Compatibility Template** or submit a PR updating the tested hardware matrix in `README.md`.

### 3. Requesting New Features
Want a new dynamic effect, audio visualizer, or temperature-reactive lighting curve?
- Open a **Feature Request** with details on the concept, use case, and behavior.

---

## 💻 Local Development Setup

### 1. Clone the Repository
```bash
git clone https://github.com/MdSagorMunshi/fanlight-controller.git
cd fanlight-controller
```

### 2. Set Up a Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Run the Application in Development Mode
```bash
python3 main.py
```

### 4. Hardware Permissions
Ensure your user account can read/write to `/dev/hidraw*` and `/dev/i2c-*` without `sudo`:
```bash
./install.sh
```

---

## 🏗️ Architecture & Guidelines

FanLight Studio is architected into clean, decoupled layers:

| File | Component & Responsibility |
| :--- | :--- |
| **`main.py`** | Application bootstrap, CLI argument handling, and PyQt6 loop. |
| **`backend.py`** | Hybrid hardware engine. Contains `MSIMysticLightDirect` (direct kernel HID ioctls for Report `0x52`) and `FanLightBackend` (orchestrates Mystic Light MCU + OpenRGB DRAM client). |
| **`widgets.py`** | Custom UI widgets: `Chassis3DViewer` (60 FPS NumPy/QImage lighting compositor), `SaturationValuePicker`, `HueSlider`, and `ModernGlowSlider`. |
| **`ui.py`** | Liquid Obsidian Studio desktop interface, system tray manager, and telemetry polling. |

### Code Style Guidelines:
- Follow standard Python PEP 8 style conventions.
- Maintain strict typing with `typing` annotations (`Dict`, `List`, `Optional`, `Tuple`, `Any`).
- **Never commit personal paths or hardcoded home directories**: Always resolve paths dynamically using `os.path.dirname(os.path.abspath(__file__))` or `os.path.expanduser("~")`.
- Keep widgets self-contained and perform visual operations efficiently (e.g. vector operations in NumPy rather than pixel loops).

---

## 🧪 Testing & Hardware Verification

Before submitting a Pull Request, verify:

1. **Clean Execution**:
   ```bash
   python3 -c "import backend, ui, widgets; print('Modules imported cleanly!')"
   ```

2. **State Synchronization Test**:
   ```bash
   python3 -c "
   import sys
   from PyQt6.QtWidgets import QApplication
   from ui import FanLightApp

   app = QApplication(sys.argv)
   win = FanLightApp()
   print('Power state:', win.is_powered, 'Active mode:', win.active_mode)
   app.quit()
   "
   ```

3. **No Local Artifacts or Cache**:
   Ensure `__pycache__`, `.idea`, `.vscode`, `build/`, `dist/`, or temporary files are excluded.

---

## 🚀 Pull Request Process

1. Fork the repository and create your feature branch:
   ```bash
   git checkout -b feature/my-new-feature
   ```
2. Commit your changes with clear, descriptive commit messages:
   ```bash
   git commit -m "feat(driver): add support for MSI X670E Carbon WiFi ARGB MCU"
   ```
3. Push to your fork:
   ```bash
   git push origin feature/my-new-feature
   ```
4. Open a Pull Request on GitHub against the `main` branch.
5. Fill out the provided **Pull Request Template**.
6. Ensure any hardware changes specify the exact board model tested.

Thank you for helping make open-source hardware control on Linux amazing! 🎮✨
