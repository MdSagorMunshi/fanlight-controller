"""
ui.py - Ultra-Modern Next-Gen Studio GUI for FanLight Controller
Hardware: MSI B650M GAMING WIFI (MS-7E30) & ENE DRAM DDR5
Designed with luxury enthusiast aesthetic (NZXT CAM / Corsair iCUE style),
photorealistic 3D visualizer, precision 2D color canvas, and refined typography.
"""

import sys
import os
from typing import Optional, Dict

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QGridLayout, QColorDialog,
    QMessageBox, QSystemTrayIcon, QMenu, QSizePolicy
)
from PyQt6.QtGui import (
    QColor, QIcon, QPixmap, QPainter, QFont, QCursor, QAction
)
from PyQt6.QtCore import (
    Qt, QSize, pyqtSignal, QTimer
)

from backend import MotherboardInfo, FanLightBackend
from widgets import (
    Chassis3DViewer, SaturationValuePicker, HueSlider, ModernGlowSlider
)


STYLESHEET = """
QMainWindow {
    background-color: #0b0e14;
}

QWidget {
    color: #e2e8f0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Inter", "Ubuntu", sans-serif;
    font-size: 13px;
}

/* Studio Glass Cards */
QFrame.studio-card {
    background-color: #111622;
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 14px;
}

QFrame.studio-card:hover {
    border-color: rgba(255, 255, 255, 0.12);
}

/* Top Segmented Zone Capsule */
QFrame.capsule-frame {
    background-color: #0e121a;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 20px;
    padding: 2px;
}

QPushButton.capsule-tab {
    background: transparent;
    color: #8b99ad;
    border: none;
    border-radius: 16px;
    padding: 6px 16px;
    font-size: 11px;
    font-weight: 600;
}

QPushButton.capsule-tab:hover {
    color: #ffffff;
    background-color: rgba(255, 255, 255, 0.04);
}

QPushButton.capsule-tab.active {
    background-color: #1e2638;
    color: #00f0ff;
    font-weight: 700;
    border: 1px solid rgba(0, 240, 255, 0.35);
}

/* Master Power Button */
QPushButton.power-toggle {
    background-color: #141a26;
    color: #00f0ff;
    border: 1px solid rgba(0, 240, 255, 0.3);
    border-radius: 18px;
    padding: 6px 18px;
    font-size: 11px;
    font-weight: 700;
}

QPushButton.power-toggle:hover {
    background-color: #1a2233;
    border-color: #00f0ff;
}

QPushButton.power-toggle.off {
    color: #8892a0;
    border-color: rgba(255, 255, 255, 0.1);
    background-color: #0f131a;
}

/* Modern Effect Tiles */
QPushButton.effect-tile {
    background-color: #141a26;
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 10px;
    padding: 8px 10px;
    text-align: left;
    color: #cbd5e1;
    font-size: 11px;
    font-weight: 600;
}

QPushButton.effect-tile:hover {
    background-color: #1a2333;
    border-color: rgba(255, 255, 255, 0.16);
    color: #ffffff;
}

QPushButton.effect-tile.active {
    background-color: #122336;
    border: 1.5px solid #00f0ff;
    color: #ffffff;
}

/* Circular Color Bubbles */
QPushButton.color-bubble {
    border-radius: 14px;
    border: 2px solid rgba(255, 255, 255, 0.15);
}

QPushButton.color-bubble:hover {
    border: 2px solid #ffffff;
}

/* Atmosphere Preset Chips */
QPushButton.preset-chip {
    background-color: #141a26;
    color: #94a3b8;
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 11px;
    font-weight: 600;
}

QPushButton.preset-chip:hover {
    background-color: #1c2436;
    color: #ffffff;
    border-color: rgba(255, 255, 255, 0.18);
}
"""


class FanLightApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.backend = FanLightBackend()
        self.mb_info = MotherboardInfo.get_info()

        # Connect to backend and query live physical state
        self.backend.connect()
        live_state = self.backend.sync_hardware_state()

        # State synchronized from live hardware registers & persistent storage
        self.selected_target_idx = live_state.get("target_idx", -1)
        self.is_powered = live_state["is_powered"]
        self.active_mode = live_state["mode"] if self.is_powered else live_state.get("last_active_mode", "Static")
        c_rgb = live_state["color"]
        self.current_color = QColor(c_rgb[0], c_rgb[1], c_rgb[2])
        self.brightness = live_state["brightness"]
        self.speed = live_state["speed"]

        self.mode_buttons: Dict[str, QPushButton] = {}
        self.zone_buttons: Dict[int, QPushButton] = {}

        self.init_ui()
        self.apply_live_state_to_ui(live_state)
        self.setup_tray()
        self.setup_telemetry_poll()

    def init_ui(self):
        self.setWindowTitle("FanLight Studio // MSI AM5 Hardware ARGB Deck")
        self.setMinimumSize(1240, 800)
        self.resize(1260, 820)
        self.setStyleSheet(STYLESHEET)

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(20, 16, 20, 16)
        root_layout.setSpacing(14)

        # 1. Top Sleek Navigation Bar
        top_bar = self.create_nav_bar()
        root_layout.addWidget(top_bar)

        # 2. Workspace Body (Left: 3D Hardware Rig | Right: Studio Control Deck)
        body_layout = QHBoxLayout()
        body_layout.setSpacing(16)

        # Left Column: Photorealistic 3D Rig Visualizer
        left_stage = self.create_hardware_stage()
        body_layout.addWidget(left_stage, 5)

        # Right Column: Refined Control Studio
        right_deck = self.create_studio_deck()
        body_layout.addWidget(right_deck, 6)

        root_layout.addLayout(body_layout, 1)

        # 3. Bottom Minimalist Telemetry Bar
        bottom_bar = self.create_telemetry_bar()
        root_layout.addWidget(bottom_bar)

    # -------------------------------------------------------------------------
    # Top Navigation Bar
    # -------------------------------------------------------------------------
    def create_nav_bar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        # Left: App Brand & Subtitle
        brand_box = QHBoxLayout()
        brand_box.setSpacing(10)

        icon_lbl = QLabel()
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.png")
        if os.path.exists(icon_path):
            icon_lbl.setPixmap(QPixmap(icon_path).scaled(30, 30, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        brand_box.addWidget(icon_lbl)

        v_brand = QVBoxLayout()
        v_brand.setSpacing(0)
        t_main = QLabel("FANLIGHT STUDIO")
        t_main.setStyleSheet("font-size: 14px; font-weight: 800; color: #ffffff; letter-spacing: 1.5px;")
        v_brand.addWidget(t_main)

        t_sub = QLabel("MSI B650M AM5 • MYSTIC LIGHT + ENE DRAM")
        t_sub.setStyleSheet("font-size: 9px; font-weight: 600; color: #64748b; letter-spacing: 0.5px;")
        v_brand.addWidget(t_sub)

        brand_box.addLayout(v_brand)
        layout.addLayout(brand_box)
        layout.addStretch()

        # Center: Segmented Capsule Zone Switcher
        capsule = QFrame()
        capsule.setProperty("class", "capsule-frame")
        c_layout = QHBoxLayout(capsule)
        c_layout.setContentsMargins(4, 4, 4, 4)
        c_layout.setSpacing(4)

        zones = [
            (-1, "⚡ All Devices"),
            (1, "🌀 Case Fans (120 LEDs)"),
            (2, "💾 DDR5 RAM (8 LEDs)")
        ]

        for z_id, z_title in zones:
            btn = QPushButton(z_title)
            btn.setProperty("class", "capsule-tab active" if z_id == -1 else "capsule-tab")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, idx=z_id: self.select_target_zone(idx))
            self.zone_buttons[z_id] = btn
            c_layout.addWidget(btn)

        layout.addWidget(capsule)
        layout.addStretch()

        # Right: Master Power Toggle Button
        self.power_btn = QPushButton("● SYSTEM LIGHTS ON")
        self.power_btn.setProperty("class", "power-toggle")
        self.power_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.power_btn.clicked.connect(self.toggle_power)
        layout.addWidget(self.power_btn)

        return bar

    # -------------------------------------------------------------------------
    # Left Stage: Photorealistic 3D Hardware Rig
    # -------------------------------------------------------------------------
    def create_hardware_stage(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 3D Visualizer Canvas
        self.chassis_viewer = Chassis3DViewer()
        self.chassis_viewer.targetZoneChanged.connect(self.select_target_zone)
        layout.addWidget(self.chassis_viewer, 1)

        # Hardware Info Strip
        info_frame = QFrame()
        info_frame.setStyleSheet("""
            background-color: #0d111a;
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 10px;
            padding: 8px 14px;
        """)
        i_layout = QHBoxLayout(info_frame)
        i_layout.setContentsMargins(8, 4, 8, 4)
        i_layout.setSpacing(12)

        dot = QLabel("●")
        dot.setStyleSheet("color: #00f0ff; font-size: 11px;")
        i_layout.addWidget(dot)

        node = self.backend.mystic_direct.find_device_node() or "/dev/hidraw4"
        self.hw_info_lbl = QLabel(f"MSI B650M GAMING WIFI • {node} (JARGB_V2) • SMBus 0x72 (ENE DRAM)")
        self.hw_info_lbl.setStyleSheet("font-size: 11px; font-weight: 600; color: #8899aa;")
        i_layout.addWidget(self.hw_info_lbl)
        i_layout.addStretch()

        layout.addWidget(info_frame)
        return panel

    # -------------------------------------------------------------------------
    # Right Stage: The Lighting Studio Deck
    # -------------------------------------------------------------------------
    def create_studio_deck(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Card 1: Precision Color Studio
        color_card = self.create_color_studio_card()
        layout.addWidget(color_card)

        # Card 2: Lighting Effects Grid
        effects_card = self.create_effects_grid_card()
        layout.addWidget(effects_card)

        # Card 3: Precision Sliders & Atmosphere Profiles
        controls_card = self.create_controls_card()
        layout.addWidget(controls_card)

        return panel

    # -------------------------------------------------------------------------
    # Card 1: Precision Color Studio
    # -------------------------------------------------------------------------
    def create_color_studio_card(self) -> QFrame:
        card = QFrame()
        card.setProperty("class", "studio-card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(10)

        # Header with Hex & Custom button
        header_row = QHBoxLayout()
        lbl = QLabel("COLOR PALETTE & SPECTRUM")
        lbl.setStyleSheet("font-size: 10px; font-weight: 700; color: #64748b; letter-spacing: 1px;")
        header_row.addWidget(lbl)
        header_row.addStretch()

        # Hex pill readout
        self.hex_badge = QLabel(self.current_color.name().upper())
        self.hex_badge.setStyleSheet("""
            background-color: #171d2b; color: #00f0ff;
            border: 1px solid rgba(0, 240, 255, 0.3);
            border-radius: 6px; padding: 2px 8px;
            font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 700;
        """)
        header_row.addWidget(self.hex_badge)

        btn_palette = QPushButton("RGB Dialog...")
        btn_palette.setStyleSheet("""
            background: transparent; color: #94a3b8; border: none; font-size: 11px; font-weight: 600;
        """)
        btn_palette.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_palette.clicked.connect(self.open_system_color_picker)
        header_row.addWidget(btn_palette)
        layout.addLayout(header_row)

        # 2D Saturation/Value Canvas
        self.sv_picker = SaturationValuePicker()
        self.sv_picker.colorSelected.connect(self.on_canvas_color_changed)
        layout.addWidget(self.sv_picker)

        # Horizontal 360° Rainbow Hue Slider
        self.hue_slider = HueSlider()
        self.hue_slider.hueChanged.connect(self.on_hue_slider_changed)
        layout.addWidget(self.hue_slider)

        # 12 Circular Color Bubbles
        swatch_row = QHBoxLayout()
        swatch_row.setSpacing(8)

        swatches = [
            ("Cyan", "#00f0ff"),
            ("Violet", "#9900ff"),
            ("Crimson", "#ff003c"),
            ("Lime", "#00ff66"),
            ("Ice", "#66d9ff"),
            ("Gold", "#ffd700"),
            ("Magenta", "#ff007f"),
            ("Amber", "#ff8800"),
            ("Royal", "#0066ff"),
            ("Toxic", "#39ff14"),
            ("Coral", "#ff4500"),
            ("White", "#ffffff"),
        ]

        for name, hex_code in swatches:
            btn = QPushButton()
            btn.setProperty("class", "color-bubble")
            btn.setFixedSize(26, 26)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {hex_code};
                    border-radius: 13px;
                    border: 2px solid rgba(255, 255, 255, 0.15);
                }}
                QPushButton:hover {{
                    border: 2px solid #ffffff;
                }}
            """)
            btn.setToolTip(f"{name} ({hex_code})")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, col=hex_code: self.apply_swatch_color(col))
            swatch_row.addWidget(btn)

        layout.addLayout(swatch_row)
        return card

    # -------------------------------------------------------------------------
    # Card 2: Modern Effects Grid
    # -------------------------------------------------------------------------
    def create_effects_grid_card(self) -> QFrame:
        card = QFrame()
        card.setProperty("class", "studio-card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(10)

        lbl = QLabel("LIGHTING EFFECTS")
        lbl.setStyleSheet("font-size: 10px; font-weight: 700; color: #64748b; letter-spacing: 1px;")
        layout.addWidget(lbl)

        grid = QGridLayout()
        grid.setSpacing(8)

        effects = [
            ("Static", "🔆 Static Glow", "Solid luminous tone"),
            ("Rainbow", "🌈 Rainbow Wave", "360° chromatic flow"),
            ("Breathing", "💨 Breathing Pulse", "Smooth cyclic fade"),
            ("Spectrum Cycle", "🔄 Spectrum Loop", "Full spectrum shift"),
            ("Chase Fade", "⚡ Wave Cascade", "Dynamic light stream"),
            ("Random Flicker", "✨ Starry Twinkle", "Organic sparkle pulse"),
            ("Fire", "🔥 Fire Ember", "Warm dynamic flame"),
            ("Off", "⛔ Stealth Off", "Zero lumen blackout"),
        ]

        for i, (m_key, title, desc) in enumerate(effects):
            btn = QPushButton(f"{title}\n{desc}")
            btn.setProperty("class", "effect-tile active" if m_key == "Static" else "effect-tile")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, m=m_key: self.apply_mode(m))
            self.mode_buttons[m_key] = btn
            grid.addWidget(btn, i // 4, i % 4)

        layout.addLayout(grid)
        return card

    # -------------------------------------------------------------------------
    # Card 3: Precision Sliders & Atmosphere Profiles
    # -------------------------------------------------------------------------
    def create_controls_card(self) -> QFrame:
        card = QFrame()
        card.setProperty("class", "studio-card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(12)

        # Sliders Row
        sliders_row = QHBoxLayout()
        sliders_row.setSpacing(16)

        self.brightness_slider = ModernGlowSlider(title="Brightness", min_val=0, max_val=100, default_val=100)
        self.brightness_slider.set_accent_color(self.current_color)
        self.brightness_slider.valueChanged.connect(self.on_brightness_changed)
        sliders_row.addWidget(self.brightness_slider)

        self.speed_slider = ModernGlowSlider(title="Animation Speed", min_val=0, max_val=100, default_val=50)
        self.speed_slider.set_accent_color(self.current_color)
        self.speed_slider.valueChanged.connect(self.on_speed_changed)
        sliders_row.addWidget(self.speed_slider)

        layout.addLayout(sliders_row)

        # Atmosphere Presets Row
        p_row = QHBoxLayout()
        p_row.setSpacing(8)

        lbl_p = QLabel("Profiles:")
        lbl_p.setStyleSheet("font-size: 11px; font-weight: 700; color: #64748b;")
        p_row.addWidget(lbl_p)

        presets = [
            ("Cyberpunk 2077", "#00f0ff", "Breathing"),
            ("Blood Dragon", "#ff003c", "Breathing"),
            ("Arctic Frost", "#66d9ff", "Static"),
            ("Matrix Terminal", "#00ff66", "Chase Fade"),
            ("Sunset Glow", "#ff8800", "Rainbow"),
        ]

        for title, hex_col, mode in presets:
            btn = QPushButton(title)
            btn.setProperty("class", "preset-chip")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, c=hex_col, m=mode: self.apply_preset(c, m))
            p_row.addWidget(btn)

        layout.addLayout(p_row)
        return card

    # -------------------------------------------------------------------------
    # Bottom Telemetry Bar
    # -------------------------------------------------------------------------
    def create_telemetry_bar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.telemetry_lbl = QLabel("READY • HARDWARE BUS CONNECTED")
        self.telemetry_lbl.setStyleSheet("font-size: 11px; font-weight: 600; color: #64748b;")
        layout.addWidget(self.telemetry_lbl)

        layout.addStretch()

        fps_lbl = QLabel("60 FPS ENGINE • HARDWARE SYNC ACTIVE")
        fps_lbl.setStyleSheet("font-size: 11px; font-weight: 600; color: #00f0ff;")
        layout.addWidget(fps_lbl)

        return bar

    # -------------------------------------------------------------------------
    # Controller Interactions
    # -------------------------------------------------------------------------
    def apply_live_state_to_ui(self, live_state: Dict[str, Any]):
        node = self.backend.mystic_direct.find_device_node() or "/dev/hidraw4"
        status = "ONLINE" if self.backend.is_connected else "CONNECTING..."
        self.telemetry_lbl.setText(f"{status} • Node: {node} (MSI Mystic Light 185B) • SMBus: 0x72 (ENE DRAM)")

        # 1. Power button state
        if self.is_powered:
            self.power_btn.setText("● SYSTEM LIGHTS ON")
            self.power_btn.setProperty("class", "power-toggle")
        else:
            self.power_btn.setText("○ SYSTEM LIGHTS OFF")
            self.power_btn.setProperty("class", "power-toggle off")
        self.power_btn.style().unpolish(self.power_btn)
        self.power_btn.style().polish(self.power_btn)

        # 2. Zone Capsule buttons
        for z_id, btn in self.zone_buttons.items():
            if z_id == self.selected_target_idx:
                btn.setProperty("class", "capsule-tab active")
            else:
                btn.setProperty("class", "capsule-tab")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        # 3. Active Mode Buttons
        if not self.is_powered:
            self.highlight_mode_btn("Off")
        else:
            self.highlight_mode_btn(self.active_mode)

        # 4. Color Palette & Sliders
        h = self.current_color.hue()
        if h < 0:
            h = 180
        s = self.current_color.saturation()
        v = self.current_color.value()
        self.sv_picker.set_hsv(h, s, v)
        self.hue_slider.set_hue(h)
        self.hex_badge.setText(self.current_color.name().upper())
        self.brightness_slider.set_accent_color(self.current_color)
        self.speed_slider.set_accent_color(self.current_color)
        self.brightness_slider.set_value(self.brightness)
        self.speed_slider.set_value(self.speed)

        # 5. Visualizer
        self.update_hardware_visualizer()

    def setup_telemetry_poll(self):
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll_hardware_telemetry)
        self.poll_timer.start(3000)

    def poll_hardware_telemetry(self):
        node = self.backend.mystic_direct.find_device_node()
        if node and node != self.backend.mystic_direct.device_path:
            self.backend.mystic_direct.device_path = node
            self.telemetry_lbl.setText(f"ONLINE • Node: {node} (MSI Mystic Light 185B) • SMBus: 0x72 (ENE DRAM)")

    def closeEvent(self, event):
        self.backend.selected_target_idx = self.selected_target_idx
        self.backend.save_state()
        super().closeEvent(event)

    def select_target_zone(self, target_idx: int):
        self.selected_target_idx = target_idx
        self.backend.selected_target_idx = target_idx
        self.backend.save_state()

        # Update Zone Tabs
        for z_id, btn in self.zone_buttons.items():
            if z_id == target_idx:
                btn.setProperty("class", "capsule-tab active")
            else:
                btn.setProperty("class", "capsule-tab")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        self.update_hardware_visualizer()

    def toggle_power(self):
        self.is_powered = not self.is_powered
        if self.is_powered:
            self.power_btn.setText("● SYSTEM LIGHTS ON")
            self.power_btn.setProperty("class", "power-toggle")
            target_mode = self.active_mode if self.active_mode != "Off" else "Static"
            self.highlight_mode_btn(target_mode)
            self.backend.set_power(True, self.selected_target_idx)
        else:
            self.power_btn.setText("○ SYSTEM LIGHTS OFF")
            self.power_btn.setProperty("class", "power-toggle off")
            self.highlight_mode_btn("Off")
            self.backend.set_power(False, self.selected_target_idx)

        self.power_btn.style().unpolish(self.power_btn)
        self.power_btn.style().polish(self.power_btn)
        self.update_hardware_visualizer()

    def on_hue_slider_changed(self, hue: int):
        self.sv_picker.set_hue(hue)

    def on_canvas_color_changed(self, color: QColor):
        self.apply_color(color)

    def apply_color(self, color: QColor):
        if not color.isValid():
            return

        self.current_color = color
        self.hex_badge.setText(color.name().upper())

        # Update slider accents
        self.brightness_slider.set_accent_color(color)
        self.speed_slider.set_accent_color(color)

        # Switch to Static mode
        self.highlight_mode_btn("Static")
        self.active_mode = "Static"

        if not self.is_powered:
            self.is_powered = True
            self.power_btn.setText("● SYSTEM LIGHTS ON")
            self.power_btn.setProperty("class", "power-toggle")
            self.power_btn.style().unpolish(self.power_btn)
            self.power_btn.style().polish(self.power_btn)

        self.backend.set_color(color.red(), color.green(), color.blue(), self.selected_target_idx)
        self.update_hardware_visualizer()

    def apply_swatch_color(self, hex_code: str):
        color = QColor(hex_code)
        h, s, v, _ = color.getHsv()
        if h >= 0:
            self.hue_slider.set_hue(h)
            self.sv_picker.set_hsv(h, s, v)
        self.apply_color(color)

    def open_system_color_picker(self):
        col = QColorDialog.getColor(self.current_color, self, "Select ARGB Color")
        if col.isValid():
            self.apply_swatch_color(col.name())

    def apply_mode(self, mode_name: str):
        self.active_mode = mode_name
        self.highlight_mode_btn(mode_name)

        if mode_name == "Off":
            self.is_powered = False
            self.power_btn.setText("○ SYSTEM LIGHTS OFF")
            self.power_btn.setProperty("class", "power-toggle off")
            self.power_btn.style().unpolish(self.power_btn)
            self.power_btn.style().polish(self.power_btn)
            self.backend.set_power(False, self.selected_target_idx)
        else:
            if not self.is_powered:
                self.is_powered = True
                self.power_btn.setText("● SYSTEM LIGHTS ON")
                self.power_btn.setProperty("class", "power-toggle")
                self.power_btn.style().unpolish(self.power_btn)
                self.power_btn.style().polish(self.power_btn)

            self.backend.set_mode(mode_name, self.selected_target_idx, speed=self.speed)

        self.update_hardware_visualizer()

    def highlight_mode_btn(self, mode_name: str):
        for k, btn in self.mode_buttons.items():
            if k.lower() == mode_name.lower():
                btn.setProperty("class", "effect-tile active")
            else:
                btn.setProperty("class", "effect-tile")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def on_brightness_changed(self, value: int):
        self.brightness = value
        self.backend.set_brightness(value, self.selected_target_idx)
        self.update_hardware_visualizer()

    def on_speed_changed(self, value: int):
        self.speed = value
        self.backend.set_speed(value, self.selected_target_idx)
        self.update_hardware_visualizer()

    def apply_preset(self, hex_col: str, mode: str):
        if mode == "Off":
            self.apply_mode("Off")
            return

        self.apply_swatch_color(hex_col)
        if mode != "Static":
            self.apply_mode(mode)

    def update_hardware_visualizer(self):
        self.chassis_viewer.set_hardware_state(
            color=self.current_color,
            mode=self.active_mode,
            brightness=self.brightness,
            speed=self.speed,
            is_powered=self.is_powered,
            target_zone=self.selected_target_idx
        )

    # -------------------------------------------------------------------------
    # System Tray
    # -------------------------------------------------------------------------
    def setup_tray(self):
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.png")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else self.windowIcon()

        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("FanLight Studio")

        menu = QMenu()
        act_toggle = menu.addAction("Show / Hide Studio")
        act_toggle.triggered.connect(self.toggle_window)
        menu.addSeparator()

        act_on = menu.addAction("💡 Lights ON")
        act_on.triggered.connect(lambda: self.toggle_power() if not self.is_powered else None)

        act_off = menu.addAction("⛔ Lights OFF")
        act_off.triggered.connect(lambda: self.toggle_power() if self.is_powered else None)

        menu.addSeparator()
        act_cyber = menu.addAction("🌆 Cyberpunk 2077")
        act_cyber.triggered.connect(lambda: self.apply_preset("#00f0ff", "Breathing"))

        act_rainbow = menu.addAction("🌈 Rainbow Wave")
        act_rainbow.triggered.connect(lambda: self.apply_mode("Rainbow"))

        menu.addSeparator()
        act_exit = menu.addAction("Quit FanLight Studio")
        act_exit.triggered.connect(QApplication.instance().quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

    def toggle_window(self):
        if self.isVisible():
            self.hide()
        else:
            self.showNormal()
            self.activateWindow()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_window()
