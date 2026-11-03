#!/usr/bin/env bash
set -e

# ==============================================================================
# FanLight Studio - Automated Installer & System Configurator
# Supports: MSI B650 / AM5 ARGB Controllers & DDR5 RAM RGB
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ICON_PATH="$SCRIPT_DIR/assets/icon.png"
DESKTOP_DIR="${XDG_DESKTOP_DIR:-$HOME/Desktop}"
APPS_DIR="$HOME/.local/share/applications"
BIN_DIR="$HOME/.local/bin"
UDEV_RULES_FILE="/etc/udev/rules.d/60-msi-mysticlight.rules"

echo "======================================================"
echo "          FanLight Studio - Linux Installer           "
echo "======================================================"

if [ "$1" == "--uninstall" ]; then
    echo "[*] Uninstalling FanLight Studio..."
    rm -f "$BIN_DIR/fanlight-studio"
    rm -f "$APPS_DIR/FanLightControl.desktop"
    rm -f "$DESKTOP_DIR/FanLightControl.desktop"
    if [ -f "$UDEV_RULES_FILE" ]; then
        echo "[*] Removing udev rules (requires sudo)..."
        sudo rm -f "$UDEV_RULES_FILE"
        sudo udevadm control --reload-rules && sudo udevadm trigger
    fi
    echo "[✓] FanLight Studio uninstalled successfully."
    exit 0
fi

# 1. Check Python 3 and Pip
echo "[1/4] Checking Python environment..."
if ! command -v python3 &>/dev/null; then
    echo "[!] Python 3 is required. Please install python3."
    exit 1
fi

python3 -m pip --version &>/dev/null || {
    echo "[!] pip is not installed. Installing pip or system packages is recommended."
}

# Install requirements
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    echo "[*] Installing Python dependencies..."
    pip3 install -q -r "$SCRIPT_DIR/requirements.txt" || pip install -q -r "$SCRIPT_DIR/requirements.txt" || true
fi

# 2. Configure udev rules for non-root hardware access
echo "[2/4] Configuring hardware udev rules for MSI Mystic Light & SMBus..."
TMP_RULES=$(mktemp)
cat << 'EOF' > "$TMP_RULES"
# MSI Mystic Light USB HID Controllers (AM5 B650/X670 & Intel series)
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0db0", ATTRS{idProduct}=="0076", MODE="0666", TAG+="uaccess"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0db0", ATTRS{idProduct}=="0080", MODE="0666", TAG+="uaccess"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0db0", ATTRS{idProduct}=="0083", MODE="0666", TAG+="uaccess"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0db0", ATTRS{idProduct}=="0087", MODE="0666", TAG+="uaccess"

# SMBus I2C access for DDR5/DDR4 RGB RAM
KERNEL=="i2c-[0-9]*", GROUP="i2c", MODE="0666"
EOF

if [ -w "/etc/udev/rules.d" ]; then
    cp "$TMP_RULES" "$UDEV_RULES_FILE"
    udevadm control --reload-rules && udevadm trigger
    rm -f "$TMP_RULES"
    echo "[✓] udev rules installed directly."
else
    echo "[*] Sudo required to place udev rules in $UDEV_RULES_FILE:"
    sudo cp "$TMP_RULES" "$UDEV_RULES_FILE"
    sudo udevadm control --reload-rules && sudo udevadm trigger
    rm -f "$TMP_RULES"
    echo "[✓] udev rules installed."
fi

# 3. Create CLI Wrapper in ~/.local/bin
echo "[3/4] Creating CLI shortcut..."
mkdir -p "$BIN_DIR"
cat << EOF > "$BIN_DIR/fanlight-studio"
#!/usr/bin/env bash
exec python3 "$SCRIPT_DIR/main.py" "\$@"
EOF
chmod +x "$BIN_DIR/fanlight-studio"

# 4. Create Desktop Shortcut
echo "[4/4] Creating Desktop application entry..."
mkdir -p "$APPS_DIR"
DESKTOP_ENTRY="$APPS_DIR/FanLightControl.desktop"

cat << EOF > "$DESKTOP_ENTRY"
[Desktop Entry]
Version=1.0
Type=Application
Name=FanLight Studio
GenericName=Fan & RGB Lighting Controller
Comment=Direct kernel ARGB controller for MSI AM5 & DDR5 RAM
Exec=python3 $SCRIPT_DIR/main.py
Icon=$ICON_PATH
Terminal=false
Categories=Utility;HardwareSettings;Settings;
StartupNotify=true
EOF

chmod +x "$DESKTOP_ENTRY"

# Copy to Desktop if directory exists
if [ -d "$DESKTOP_DIR" ]; then
    cp "$DESKTOP_ENTRY" "$DESKTOP_DIR/FanLightControl.desktop"
    chmod +x "$DESKTOP_DIR/FanLightControl.desktop"
fi

echo ""
echo "======================================================"
echo " [✓] FanLight Studio successfully installed!"
echo " Launch it via:"
echo "   - Application Launcher: FanLight Studio"
echo "   - Terminal: fanlight-studio"
echo "   - Direct: python3 $SCRIPT_DIR/main.py"
echo "======================================================"
