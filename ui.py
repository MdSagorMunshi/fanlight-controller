"""
ui.py - Ultra-Modern Next-Gen Studio GUI for FanLight Controller
Hardware: MSI B650M GAMING WIFI (MS-7E30) & ENE DRAM DDR5
Designed with luxury enthusiast aesthetic (NZXT CAM / Corsair iCUE style),
photorealistic 3D visualizer, precision 2D color canvas, multi-zone per-fan targeting,
and real-time hardware temperature reactive lighting.
"""

import sys
import os
from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QGridLayout, QColorDialog,
    QMessageBox, QSystemTrayIcon, QMenu, QSizePolicy, QComboBox
)
from PyQt6.QtGui import (
    QColor, QIcon, QPixmap, QPainter, QFont, QCursor, QAction
)
from PyQt6.QtCore import (
    Qt, QSize, pyqtSignal, QTimer
)

from backend import (
    MotherboardInfo, FanLightBackend, HardwareSensors,
    TARGET_ALL, TARGET_FRONT_FANS, TARGET_EXHAUST_FANS,
    TARGET_MOTHERBOARD, TARGET_RAM, TARGET_NAMES
)
from widgets import (
    Chassis3DViewer, SaturationValuePicker, HueSlider, ModernGlowSlider, SecondaryColorSwatch
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
    padding: 6px 14px;
    font-size: 11px;
    font-weight: 600;
}

QPushButton.capsule-tab:hover {
    color: #ffffff;
    background-color: rgba(255, 255, 255, 0.05);
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
    border-radius: 9px;
    padding: 6px 8px;
    text-align: left;
    color: #cbd5e1;
    font-size: 11px;
    font-weight: 600;
    min-height: 38px;
}

QPushButton.effect-tile:hover {
    background-color: #1a2333;
    border-color: rgba(255, 255, 255, 0.16);
    color: #ffffff;
}

QPushButton.effect-tile.active {
    background-color: #1b263b;
    border: 1px solid #00f0ff;
    color: #00f0ff;
    font-weight: 700;
}

/* Atmosphere Preset Chips */
QPushButton.preset-chip {
    background-color: #141924;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 14px;
    padding: 5px 12px;
    color: #94a3b8;
    font-size: 11px;
    font-weight: 600;
}

QPushButton.preset-chip:hover {
    color: #ffffff;
    background-color: #1b2230;
    border-color: rgba(255, 255, 255, 0.2);
}

/* Thermal Sensor Badges */
QFrame.sensor-badge {
    background-color: #0f1420;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 10px;
    padding: 4px 10px;
}
"""


class FanLightStudioWindow(QMainWindow):
    def __init__(self, backend: Optional[FanLightBackend] = None):
        super().__init__()
        self.setWindowTitle("FanLight Studio • Next-Gen RGB & Multi-Zone Deck")
        self.resize(1220, 820)
        self.setMinimumSize(1080, 720)
        self.setStyleSheet(STYLESHEET)

        self.backend = backend or FanLightBackend()
        self.selected_target_idx = self.backend.selected_target_idx

        # Current Zone State pointers
        current_cfg = self.backend.get_zone(self.selected_target_idx)
        self.current_color = QColor(*current_cfg.color)
        self.secondary_color = QColor(*current_cfg.secondary_color)
        self.active_mode = current_cfg.mode
        self.brightness = current_cfg.brightness
        self.speed = current_cfg.speed
        self.is_powered = self.backend.is_powered_on

        # UI References
        self.zone_buttons: Dict[int, QPushButton] = {}
        self.mode_buttons: Dict[str, QPushButton] = {}
        self.sensor_labels: Dict[str, QLabel] = {}

        self.init_ui()
        self.setup_tray()

        # Connect to Hardware
        self.backend.connect()

        # Register animation streamer callback for live visualizer
        self.backend.anim_engine.add_callback(self.on_streamed_animation_frame)

        # Sync live state
        live_state = self.backend.sync_hardware_state()
        self.apply_live_state_to_ui(live_state)

        # Setup telemetry & sensor polling
        self.setup_telemetry_poll()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(18, 14, 18, 14)
        root_layout.setSpacing(12)

        # 1. Top Navigation Bar & Zone Capsule
        nav_bar = self.create_nav_bar()
        root_layout.addWidget(nav_bar)

        # 2. Workspace Body (Left: 3D Hardware Rig | Right: Studio Control Deck)
        body_layout = QHBoxLayout()
        body_layout.setSpacing(14)

        # Left Column: Photorealistic 3D Rig Visualizer & Telemetry
        left_stage = self.create_hardware_stage()
        body_layout.addWidget(left_stage, 5)

        # Right Column: Refined Multi-Zone Control Studio
        right_deck = self.create_studio_deck()
        body_layout.addWidget(right_deck, 6)

        root_layout.addLayout(body_layout, 1)

        # 3. Bottom Status Bar
        bottom_bar = self.create_telemetry_bar()
        root_layout.addWidget(bottom_bar)

    def create_nav_bar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # App Brand & Subtitle
        brand_box = QHBoxLayout()
        brand_box.setSpacing(10)

        icon_lbl = QLabel()
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.png")
        if os.path.exists(icon_path):
            icon_lbl.setPixmap(QPixmap(icon_path).scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        brand_box.addWidget(icon_lbl)

        v_brand = QVBoxLayout()
        v_brand.setSpacing(0)
        t_main = QLabel("FANLIGHT STUDIO")
        t_main.setStyleSheet("font-size: 14px; font-weight: 800; color: #ffffff; letter-spacing: 1.5px;")
        v_brand.addWidget(t_main)

        t_sub = QLabel("MULTI-ZONE ARGB • MSI AM5 + DDR5 SMBUS")
        t_sub.setStyleSheet("font-size: 9px; font-weight: 600; color: #64748b; letter-spacing: 0.5px;")
        v_brand.addWidget(t_sub)

        brand_box.addLayout(v_brand)
        layout.addLayout(brand_box)
        layout.addStretch()

        # Center: Segmented Capsule Multi-Zone Switcher
        capsule = QFrame()
        capsule.setProperty("class", "capsule-frame")
        c_layout = QHBoxLayout(capsule)
        c_layout.setContentsMargins(3, 3, 3, 3)
        c_layout.setSpacing(3)

        zones = [
            (TARGET_ALL, "🌟 All Hardware"),
            (TARGET_FRONT_FANS, "🌀 Front Fans"),
            (TARGET_EXHAUST_FANS, "🌪️ Top & Rear"),
            (TARGET_MOTHERBOARD, "💡 Motherboard"),
            (TARGET_RAM, "⚡ DDR5 RAM"),
        ]

        for z_id, z_title in zones:
            btn = QPushButton(z_title)
            btn.setProperty("class", "capsule-tab active" if z_id == self.selected_target_idx else "capsule-tab")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, idx=z_id: self.select_target_zone(idx))
            self.zone_buttons[z_id] = btn
            c_layout.addWidget(btn)

        layout.addWidget(capsule)
        layout.addStretch()

        # Right: Master Power Toggle Button
        self.power_btn = QPushButton("● LIGHTS ON")
        self.power_btn.setProperty("class", "power-toggle")
        self.power_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.power_btn.clicked.connect(self.toggle_power)
        layout.addWidget(self.power_btn)

        return bar

    def create_hardware_stage(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 3D Visualizer Canvas
        self.chassis_viewer = Chassis3DViewer()
        self.chassis_viewer.targetZoneChanged.connect(self.select_target_zone)
        layout.addWidget(self.chassis_viewer, 1)

        # Thermal Hardware Sensors Strip
        sensor_frame = QFrame()
        sensor_frame.setStyleSheet("""
            background-color: #0d111a;
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 10px;
            padding: 6px 12px;
        """)
        s_layout = QHBoxLayout(sensor_frame)
        s_layout.setContentsMargins(6, 4, 6, 4)
        s_layout.setSpacing(14)

        t_title = QLabel("HARDWARE SENSORS:")
        t_title.setStyleSheet("font-size: 9px; font-weight: 800; color: #64748b; letter-spacing: 0.8px;")
        s_layout.addWidget(t_title)

        self.sensor_labels["cpu"] = QLabel("🔥 CPU: --°C")
        self.sensor_labels["cpu"].setStyleSheet("font-size: 11px; font-weight: 700; color: #00f0ff;")
        s_layout.addWidget(self.sensor_labels["cpu"])

        self.sensor_labels["gpu"] = QLabel("🎮 GPU: --°C")
        self.sensor_labels["gpu"].setStyleSheet("font-size: 11px; font-weight: 700; color: #00ff88;")
        s_layout.addWidget(self.sensor_labels["gpu"])

        self.sensor_labels["ram"] = QLabel("💾 RAM: --°C")
        self.sensor_labels["ram"].setStyleSheet("font-size: 11px; font-weight: 700; color: #ffaa00;")
        s_layout.addWidget(self.sensor_labels["ram"])

        s_layout.addStretch()

        # Thermal source selector dropdown
        s_layout.addWidget(QLabel("Sync Source:"))
        self.temp_source_box = QComboBox()
        self.temp_source_box.addItems(["CPU", "GPU", "RAM"])
        self.temp_source_box.setStyleSheet("""
            QComboBox {
                background-color: #161c28; color: #e2e8f0;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px; padding: 2px 8px; font-size: 11px; font-weight: 600;
            }
        """)
        self.temp_source_box.currentTextChanged.connect(self.on_temp_source_changed)
        s_layout.addWidget(self.temp_source_box)

        layout.addWidget(sensor_frame)
        return panel

    def create_studio_deck(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Card 1: Precision Dual-Color Studio
        color_card = self.create_color_studio_card()
        layout.addWidget(color_card)

        # Card 2: Lighting Effects Matrix (Hardware + Software Procedural)
        effects_card = self.create_effects_grid_card()
        layout.addWidget(effects_card)

        # Card 3: Sliders & Atmosphere Profiles
        controls_card = self.create_controls_card()
        layout.addWidget(controls_card)

        return panel

    def create_color_studio_card(self) -> QFrame:
        card = QFrame()
        card.setProperty("class", "studio-card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(8)

        # Header Row
        header_row = QHBoxLayout()
        self.zone_title_lbl = QLabel("ALL HARDWARE • COLOR & ACCENTS")
        self.zone_title_lbl.setStyleSheet("font-size: 10px; font-weight: 800; color: #64748b; letter-spacing: 1px;")
        header_row.addWidget(self.zone_title_lbl)
        header_row.addStretch()

        # Primary Hex readout
        self.hex_badge = QLabel(self.current_color.name().upper())
        self.hex_badge.setStyleSheet("""
            background-color: #171d2b; color: #00f0ff;
            border: 1px solid rgba(0, 240, 255, 0.3);
            border-radius: 6px; padding: 2px 8px;
            font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 700;
        """)
        header_row.addWidget(self.hex_badge)

        btn_palette = QPushButton("RGB Dialog...")
        btn_palette.setStyleSheet("background: transparent; color: #94a3b8; border: none; font-size: 11px; font-weight: 600;")
        btn_palette.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_palette.clicked.connect(self.open_system_color_picker)
        header_row.addWidget(btn_palette)
        layout.addLayout(header_row)

        # 2D Saturation/Value Canvas & Hue Slider
        self.sv_picker = SaturationValuePicker()
        self.sv_picker.colorSelected.connect(self.on_canvas_color_changed)
        layout.addWidget(self.sv_picker)

        self.hue_slider = HueSlider()
        self.hue_slider.hueChanged.connect(self.on_hue_slider_changed)
        layout.addWidget(self.hue_slider)

        # Dual-Color Row (Quick Bubbles + Secondary Accent Swatch)
        dual_row = QHBoxLayout()
        dual_row.setSpacing(10)

        # Quick Palette Bubbles
        swatch_layout = QHBoxLayout()
        swatch_layout.setSpacing(6)
        swatches = [
            ("Cyan", "#00f0ff"),
            ("Lime", "#00ff66"),
            ("Violet", "#9900ff"),
            ("Crimson", "#ff003c"),
            ("Gold", "#ffd700"),
            ("Magenta", "#ff007f"),
            ("Amber", "#ff8800"),
            ("White", "#ffffff"),
        ]
        for name, hex_code in swatches:
            btn = QPushButton()
            btn.setFixedSize(22, 22)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {hex_code};
                    border-radius: 11px;
                    border: 2px solid rgba(255, 255, 255, 0.15);
                }}
                QPushButton:hover {{
                    border: 2px solid #ffffff;
                }}
            """)
            btn.setToolTip(f"{name} ({hex_code})")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, col=hex_code: self.apply_swatch_color(col))
            swatch_layout.addWidget(btn)

        dual_row.addLayout(swatch_layout)
        dual_row.addStretch()

        # Secondary Color Selector Swatch (for Meteor, Cyberpunk, Lightning)
        self.secondary_swatch = SecondaryColorSwatch(color=self.secondary_color)
        self.secondary_swatch.colorChanged.connect(self.on_secondary_color_changed)
        dual_row.addWidget(self.secondary_swatch)

        layout.addLayout(dual_row)
        return card

    def create_effects_grid_card(self) -> QFrame:
        card = QFrame()
        card.setProperty("class", "studio-card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(8)

        lbl = QLabel("LIGHTING EFFECTS & ANIMATIONS")
        lbl.setStyleSheet("font-size: 10px; font-weight: 800; color: #64748b; letter-spacing: 1px;")
        layout.addWidget(lbl)

        grid = QGridLayout()
        grid.setSpacing(6)

        # 16 High-Performance Modes (Hardware MCU + Procedural)
        effects = [
            # Row 0: Fundamentals
            ("Static", "🔆 Static Glow", "Solid luminous tone"),
            ("Rainbow Wave", "🌈 Rainbow Wave", "360° chromatic flow"),
            ("Breathing", "💨 Breathing Pulse", "Smooth cyclic fade"),
            ("Meteor Shower", "☄️ Meteor Shower", "Dual-tone comet tail"),
            # Row 1: Unlocked Hardware Modes
            ("Lightning Storm", "⚡ Lightning Storm", "Violent dual-tone arcs"),
            ("Planetary Orbit", "🪐 Planetary Orbit", "Celestial ring orbit"),
            ("Visor Scanner", "🛸 Visor Scanner", "Cylon bouncing wave"),
            ("Fire Ember", "🔥 Fire Ember", "Warm dynamic flame"),
            # Row 2: Procedural Real-time Animations
            ("Thermal Reactive", "🌡️ Thermal Sync", "Live hardware heatmap"),
            ("Cyberpunk Wave", "🌆 Cyberpunk Wave", "Dual sinusoidal sweep"),
            ("Heartbeat Pulse", "💓 Heartbeat Pulse", "Cardiac double-thump"),
            ("Aurora Borealis", "🌌 Aurora Borealis", "Polar harmonic wave"),
            # Row 3: Specialty & blackouts
            ("Police Flasher", "🚨 Police Flasher", "Alternating strobe"),
            ("Stack Cascade", "🧱 Stack Cascade", "Segment fill animation"),
            ("Starry Twinkle", "✨ Starry Twinkle", "Organic sparkle pulse"),
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

    def create_controls_card(self) -> QFrame:
        card = QFrame()
        card.setProperty("class", "studio-card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(10)

        # Sliders Row
        sliders_row = QHBoxLayout()
        sliders_row.setSpacing(14)

        self.brightness_slider = ModernGlowSlider(label="Brightness", value=100)
        self.brightness_slider.set_accent_color(self.current_color)
        self.brightness_slider.valueChanged.connect(self.on_brightness_changed)
        sliders_row.addWidget(self.brightness_slider)

        self.speed_slider = ModernGlowSlider(label="Animation Speed", value=50)
        self.speed_slider.set_accent_color(self.current_color)
        self.speed_slider.valueChanged.connect(self.on_speed_changed)
        sliders_row.addWidget(self.speed_slider)

        layout.addLayout(sliders_row)

        # Atmosphere Presets Row
        p_row = QHBoxLayout()
        p_row.setSpacing(6)

        lbl_p = QLabel("ATMOSPHERES:")
        lbl_p.setStyleSheet("font-size: 9px; font-weight: 800; color: #64748b;")
        p_row.addWidget(lbl_p)

        presets = [
            ("Cyberpunk", "#00f0ff", "#ff007f", "Cyberpunk Wave"),
            ("Deep Fire", "#ff3300", "#ffaa00", "Fire Ember"),
            ("Lightning", "#00f0ff", "#ffffff", "Lightning Storm"),
            ("Comet", "#00ff88", "#0088ff", "Meteor Shower"),
            ("Arctic", "#66d9ff", "#002244", "Breathing"),
            ("Cardiac", "#ff003c", "#33000a", "Heartbeat Pulse"),
        ]

        for title, p_col, s_col, mode in presets:
            btn = QPushButton(title)
            btn.setProperty("class", "preset-chip")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, p=p_col, s=s_col, m=mode: self.apply_dual_preset(p, s, m))
            p_row.addWidget(btn)

        layout.addLayout(p_row)
        return card

    def create_telemetry_bar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.telemetry_lbl = QLabel("READY • MULTI-ZONE BUS CONNECTED")
        self.telemetry_lbl.setStyleSheet("font-size: 11px; font-weight: 600; color: #64748b;")
        layout.addWidget(self.telemetry_lbl)
        layout.addStretch()

        fps_lbl = QLabel("30 FPS VOLATILE ENGINE • ZERO FLASH WEAR • KERNEL DIRECT")
        fps_lbl.setStyleSheet("font-size: 11px; font-weight: 600; color: #00f0ff;")
        layout.addWidget(fps_lbl)

        return bar

    # -------------------------------------------------------------------------
    # State Synchronization & UI Refresh
    # -------------------------------------------------------------------------
    def apply_live_state_to_ui(self, live_state: Dict[str, Any]):
        node = self.backend.mystic_direct.find_device_node() or "/dev/hidraw2"
        status = "ONLINE" if self.backend.is_connected else "CONNECTING..."
        self.telemetry_lbl.setText(f"{status} • Node: {node} • ENE DRAM SMBus: 0x72")

        self._refresh_zone_ui()

    def _refresh_zone_ui(self):
        """Reflects current zone's parameters into the studio deck."""
        cfg = self.backend.get_zone(self.selected_target_idx)
        self.current_color = QColor(*cfg.color)
        self.secondary_color = QColor(*cfg.secondary_color)
        self.active_mode = cfg.mode
        self.brightness = cfg.brightness
        self.speed = cfg.speed
        self.is_powered = cfg.is_powered

        # 1. Zone title
        z_name = TARGET_NAMES.get(self.selected_target_idx, "Zone")
        self.zone_title_lbl.setText(f"{z_name.upper()} • COLOR & ACCENTS")

        # 2. Power button
        if self.is_powered:
            self.power_btn.setText("● LIGHTS ON")
            self.power_btn.setProperty("class", "power-toggle")
        else:
            self.power_btn.setText("○ LIGHTS OFF")
            self.power_btn.setProperty("class", "power-toggle off")
        self.power_btn.style().unpolish(self.power_btn)
        self.power_btn.style().polish(self.power_btn)

        # 3. Zone capsule buttons
        for z_id, btn in self.zone_buttons.items():
            if z_id == self.selected_target_idx:
                btn.setProperty("class", "capsule-tab active")
            else:
                btn.setProperty("class", "capsule-tab")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        # 4. Mode buttons
        self.highlight_mode_btn("Off" if not self.is_powered else self.active_mode)

        # 5. Color picker & Sliders
        h = self.current_color.hue()
        if h < 0:
            h = 180
        self.sv_picker.set_hsv(h, self.current_color.saturation(), self.current_color.value())
        self.hue_slider.set_hue(h)
        self.hex_badge.setText(self.current_color.name().upper())
        self.secondary_swatch.set_color(self.secondary_color)

        self.brightness_slider.set_accent_color(self.current_color)
        self.speed_slider.set_accent_color(self.current_color)
        self.brightness_slider.set_value(self.brightness)
        self.speed_slider.set_value(self.speed)

        # 6. Thermal source box
        idx = self.temp_source_box.findText(cfg.temp_source.upper())
        if idx >= 0:
            self.temp_source_box.setCurrentIndex(idx)

        # 7. Update 3D visualizer
        self.update_hardware_visualizer()

    def select_target_zone(self, target_idx: int):
        self.selected_target_idx = target_idx
        self.backend.selected_target_idx = target_idx
        self.backend.save_state()
        self._refresh_zone_ui()

    def toggle_power(self):
        new_power = not self.is_powered
        self.is_powered = new_power
        self.backend.set_power(new_power, self.selected_target_idx)
        self._refresh_zone_ui()

    def on_hue_slider_changed(self, hue: int):
        self.sv_picker.set_hue(hue)

    def on_canvas_color_changed(self, color: QColor):
        if not color.isValid():
            return
        self.current_color = color
        self.hex_badge.setText(color.name().upper())
        self.brightness_slider.set_accent_color(color)
        self.speed_slider.set_accent_color(color)

        self.backend.set_color(color.red(), color.green(), color.blue(), self.selected_target_idx)
        self.update_hardware_visualizer()

    def on_secondary_color_changed(self, color: QColor):
        if not color.isValid():
            return
        self.secondary_color = color
        self.backend.set_secondary_color(color.red(), color.green(), color.blue(), self.selected_target_idx)
        self.update_hardware_visualizer()

    def apply_swatch_color(self, hex_code: str):
        color = QColor(hex_code)
        h, s, v, _ = color.getHsv()
        if h >= 0:
            self.hue_slider.set_hue(h)
            self.sv_picker.set_hsv(h, s, v)
        self.on_canvas_color_changed(color)

    def open_system_color_picker(self):
        col = QColorDialog.getColor(self.current_color, self, "Select Primary ARGB Color")
        if col.isValid():
            self.apply_swatch_color(col.name())

    def apply_mode(self, mode_name: str):
        self.active_mode = mode_name
        self.highlight_mode_btn(mode_name)

        if mode_name.lower() == "off":
            self.backend.set_power(False, self.selected_target_idx)
        else:
            self.backend.set_mode(mode_name, self.selected_target_idx, speed=self.speed)

        self._refresh_zone_ui()

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

    def on_temp_source_changed(self, text: str):
        self.backend.set_temp_source(text.lower(), self.selected_target_idx)

    def apply_dual_preset(self, primary_hex: str, secondary_hex: str, mode: str):
        p_col = QColor(primary_hex)
        s_col = QColor(secondary_hex)
        self.backend.set_color(p_col.red(), p_col.green(), p_col.blue(), self.selected_target_idx)
        self.backend.set_secondary_color(s_col.red(), s_col.green(), s_col.blue(), self.selected_target_idx)
        self.backend.set_mode(mode, self.selected_target_idx, speed=self.speed)
        self._refresh_zone_ui()

    def update_hardware_visualizer(self):
        self.chassis_viewer.set_zone_data(
            zones=self.backend.zones,
            target_zone=self.selected_target_idx,
            is_powered=self.is_powered
        )

    def on_streamed_animation_frame(self, frame_colors: Dict[int, Tuple[int, int, int]]):
        """Real-time 30FPS callback from SoftwareAnimationEngine."""
        self.chassis_viewer.set_streamed_colors(frame_colors)

    def setup_telemetry_poll(self):
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll_telemetry)
        self.poll_timer.start(1000)

    def poll_telemetry(self):
        temps = self.backend.get_temperatures()
        if "cpu" in temps and temps["cpu"]:
            self.sensor_labels["cpu"].setText(f"🔥 CPU: {temps['cpu']:.1f}°C")
        if "gpu" in temps and temps["gpu"]:
            self.sensor_labels["gpu"].setText(f"🎮 GPU: {temps['gpu']:.1f}°C")
        if "ram" in temps and temps["ram"]:
            self.sensor_labels["ram"].setText(f"💾 RAM: {temps['ram']:.1f}°C")

    def closeEvent(self, event):
        self.backend.anim_engine.stop()
        self.backend.selected_target_idx = self.selected_target_idx
        self.backend.save_state()
        super().closeEvent(event)

    def setup_tray(self):
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.png")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else self.windowIcon()

        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("FanLight Studio")

        menu = QMenu()
        act_toggle = menu.addAction("Show / Hide Studio")
        act_toggle.triggered.connect(self.toggle_window)
        menu.addSeparator()

        act_on = menu.addAction("💡 All Lights ON")
        act_on.triggered.connect(lambda: self.backend.set_power(True, TARGET_ALL))

        act_off = menu.addAction("⛔ All Lights OFF")
        act_off.triggered.connect(lambda: self.backend.set_power(False, TARGET_ALL))

        menu.addSeparator()
        act_cyber = menu.addAction("🌆 Cyberpunk Wave")
        act_cyber.triggered.connect(lambda: self.apply_dual_preset("#00f0ff", "#ff007f", "Cyberpunk Wave"))

        act_meteor = menu.addAction("☄️ Meteor Shower")
        act_meteor.triggered.connect(lambda: self.apply_dual_preset("#00ff88", "#0088ff", "Meteor Shower"))

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
