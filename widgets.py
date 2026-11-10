"""
widgets.py - Modern High-End UI Components for FanLight Studio
Features:
- Chassis3DViewer: Photorealistic 3D hardware visualizer with multi-zone ARGB lighting,
  per-fan targeting hotspots, thermal reactive gradients, and 60 FPS live animation.
- SaturationValuePicker: Figma/macOS-style 2D color canvas
- HueSlider: Smooth 360° spectrum slider
- ModernGlowSlider: Precision linear slider with colored glowing track
- SecondaryColorSwatch: Dedicated dual-tone secondary accent color selector
"""

import os
import math
from typing import Optional, Tuple, Dict, Any
from PIL import Image
import numpy as np

from PyQt6.QtWidgets import QWidget, QSizePolicy, QColorDialog
from PyQt6.QtGui import (
    QPainter, QColor, QLinearGradient, QRadialGradient,
    QPainterPath, QPen, QBrush, QFont, QFontMetrics,
    QPixmap, QImage, QMouseEvent, QWheelEvent
)
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal, QTimer


class Chassis3DViewer(QWidget):
    """
    Photorealistic 3D Gaming Chassis Visualizer.
    Renders 3D compositing of the PC rig with independent per-zone ARGB lighting:
    - Zone 1: Front Intake Fans (JARGB_V2_1)
    - Zone 2: Top Radiator & Rear Exhaust Fans (JARGB_V2_2)
    - Zone 3: Motherboard Traces & AIO Cooler Pump (ONBOARD / JRGB1)
    - Zone 4: DDR5 RAM Modules (ENE DRAM over SMBus)
    """
    targetZoneChanged = pyqtSignal(int)  # -1 = All, 1 = Front, 2 = Exhaust, 3 = MB, 4 = RAM

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumSize(440, 480)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

        self.target_zone = -1
        self.is_powered = True
        self.active_mode = "Static"

        # Per-Zone Visual States
        self.zone_colors: Dict[int, Tuple[int, int, int]] = {
            1: (0, 240, 255),
            2: (0, 255, 120),
            3: (180, 50, 255),
            4: (0, 240, 255),
        }
        self.zone_brightness: Dict[int, int] = {1: 100, 2: 100, 3: 90, 4: 100}
        self.zone_modes: Dict[int, str] = {1: "Static", 2: "Static", 3: "Static", 4: "Static"}
        self.zone_powered: Dict[int, bool] = {1: True, 2: True, 3: True, 4: True}
        self.zone_speed: Dict[int, int] = {1: 50, 2: 50, 3: 50, 4: 50}

        self._hover_zone: Optional[int] = None
        self._hover_label: str = ""
        self._anim_phase = 0.0
        self._rainbow_hue = 0.0

        # Assets
        self.neutral_arr: Optional[np.ndarray] = None
        self.mask_arr: Optional[np.ndarray] = None
        self.m_front: Optional[np.ndarray] = None
        self.m_exhaust: Optional[np.ndarray] = None
        self.m_ram: Optional[np.ndarray] = None
        self.m_mb: Optional[np.ndarray] = None

        self.current_pixmap: Optional[QPixmap] = None
        self._last_tint_key: Optional[Tuple] = None

        self._load_assets()

        # 60 FPS animation timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_tick)
        self.timer.start(16)

    def _load_assets(self):
        assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
        neutral_path = os.path.join(assets_dir, "chassis_neutral.jpg")
        mask_path = os.path.join(assets_dir, "chassis_light_mask.png")

        if os.path.exists(neutral_path) and os.path.exists(mask_path):
            try:
                self.neutral_arr = np.array(Image.open(neutral_path), dtype=np.float32)
                raw_mask = np.array(Image.open(mask_path), dtype=np.float32) / 255.0
                self.mask_arr = raw_mask
                h, w = raw_mask.shape
                y_coords, x_coords = np.indices((h, w))

                # Partition lighting regions
                self.m_front = (raw_mask > 0.08) & (x_coords > 600)
                self.m_ram = (raw_mask > 0.08) & (x_coords >= 460) & (x_coords <= 580) & (y_coords >= 270) & (y_coords <= 530)
                self.m_exhaust = (raw_mask > 0.08) & ((x_coords < 340) | ((x_coords >= 340) & (x_coords <= 600) & (y_coords < 270)))
                self.m_mb = (raw_mask > 0.08) & ~(self.m_front | self.m_ram | self.m_exhaust)
            except Exception as e:
                print(f"[Chassis3DViewer] Error loading assets: {e}")

    def set_zone_data(self, zones: Dict[int, Any], target_zone: int, is_powered: bool):
        self.target_zone = target_zone
        self.is_powered = is_powered
        for zid, z in zones.items():
            if zid in self.zone_colors:
                self.zone_colors[zid] = tuple(getattr(z, "color", (0, 240, 255)))
                self.zone_brightness[zid] = int(getattr(z, "brightness", 100))
                self.zone_modes[zid] = str(getattr(z, "mode", "Static"))
                self.zone_powered[zid] = bool(getattr(z, "is_powered", True))
                self.zone_speed[zid] = int(getattr(z, "speed", 50))
        self._update_composite()
        self.update()

    def set_streamed_colors(self, frame_colors: Dict[int, Tuple[int, int, int]]):
        """Called by background 30FPS animation streamer."""
        for zid, col in frame_colors.items():
            if zid in self.zone_colors:
                self.zone_colors[zid] = col
        self._update_composite(is_streamed=True)
        self.update()

    def _on_tick(self):
        if not self.is_powered:
            return

        has_anim = any("breathing" in m.lower() or "rainbow" in m.lower() or "spectrum" in m.lower() for m in self.zone_modes.values())
        if not has_anim:
            return

        self._anim_phase = (self._anim_phase + 0.05) % (math.pi * 20.0)
        self._rainbow_hue = (self._rainbow_hue + 1.8) % 360.0
        self._update_composite()
        self.update()

    def _update_composite(self, is_streamed: bool = False):
        if self.neutral_arr is None or self.mask_arr is None:
            return

        # Build tint hash key
        key = (
            self.is_powered,
            tuple(self.zone_colors[i] for i in [1, 2, 3, 4]),
            tuple(self.zone_brightness[i] for i in [1, 2, 3, 4]),
            tuple(self.zone_powered[i] for i in [1, 2, 3, 4]),
            int(self._rainbow_hue) if any("rainbow" in m.lower() for m in self.zone_modes.values()) else 0
        )
        if key == self._last_tint_key and not is_streamed:
            return
        self._last_tint_key = key

        tinted = self.neutral_arr.copy()
        mask = self.mask_arr

        # Helper to tint an isolated zone mask
        def apply_zone_tint(zone_mask: Optional[np.ndarray], target_id: int):
            if zone_mask is None:
                return
            z_on = self.is_powered and self.zone_powered.get(target_id, True)
            mode = self.zone_modes.get(target_id, "Static").lower()

            if not z_on or mode == "off":
                m = mask * zone_mask.astype(np.float32)
                for c in range(3):
                    tinted[:, :, c] = tinted[:, :, c] * (1.0 - m) + (self.neutral_arr[:, :, c] * 0.2) * m
                return

            # Determine color
            if "rainbow" in mode or "spectrum" in mode:
                col_rgb = QColor.fromHsv(int(self._rainbow_hue) % 360, 255, 255)
                rgb = (col_rgb.red(), col_rgb.green(), col_rgb.blue())
            else:
                rgb = self.zone_colors.get(target_id, (0, 240, 255))

            b_mult = max(0.05, self.zone_brightness.get(target_id, 100) / 100.0)
            if "breathing" in mode:
                b_mult *= (math.sin(self._anim_phase) + 1.0) * 0.45 + 0.1

            scale = (np.array(rgb, dtype=np.float32) / 255.0) * 1.6 * b_mult
            m = mask * zone_mask.astype(np.float32)

            for c in range(3):
                tinted[:, :, c] = tinted[:, :, c] * (1.0 - m) + (self.neutral_arr[:, :, c] * scale[c]) * m

        apply_zone_tint(self.m_front, 1)
        apply_zone_tint(self.m_exhaust, 2)
        apply_zone_tint(self.m_mb, 3)
        apply_zone_tint(self.m_ram, 4)

        tinted = np.clip(tinted, 0, 255).astype(np.uint8)
        h, w, _ = tinted.shape
        qimg = QImage(tinted.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        self.current_pixmap = QPixmap.fromImage(qimg)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            z, _ = self._hit_test(event.position().x(), event.position().y())
            if z is not None:
                self.target_zone = z
                self.targetZoneChanged.emit(z)
                self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        old_zone = self._hover_zone
        self._hover_zone, self._hover_label = self._hit_test(event.position().x(), event.position().y())
        if old_zone != self._hover_zone:
            self.update()

    def leaveEvent(self, event):
        self._hover_zone = None
        self._hover_label = ""
        self.update()

    def _hit_test(self, x: float, y: float) -> Tuple[Optional[int], str]:
        """Maps click and hover coords inside 3D viewport to hardware targets."""
        w, h = self.width(), self.height()
        side = min(w, h) - 40
        ox = (w - side) / 2.0
        oy = (h - side) / 2.0
        if not (ox <= x <= ox + side and oy <= y <= oy + side):
            return (None, "")

        nx = (x - ox) / float(side) * 1024.0
        ny = (y - oy) / float(side) * 1024.0

        # Front Fans (right side of chassis)
        if 620 <= nx <= 860 and 240 <= ny <= 760:
            return (1, "Front Intake Fans • JARGB_V2_1")
        # Rear & Top Exhaust Fans (left upper and top)
        if (150 <= nx <= 320 and 260 <= ny <= 500) or (340 <= nx <= 600 and 130 <= ny <= 260):
            return (2, "Top & Rear Exhaust Fans • JARGB_V2_2")
        # DDR5 RAM (center-right)
        if 470 <= nx <= 560 and 270 <= ny <= 520:
            return (4, "DDR5 Memory • ENE DRAM (SMBus 0x72)")
        # CPU Cooler & Motherboard
        if 330 <= nx <= 460 and 330 <= ny <= 580:
            return (3, "Motherboard & 12V RGB • Onboard / JRGB1")
        # Chassis general
        if 100 <= nx <= 900 and 70 <= ny <= 940:
            return (-1, "All Hardware • Synchronized Rig")

        return (None, "")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()

        # 1. Dark Studio Showcase Chamber Background
        chamber_rect = QRectF(10, 10, w - 20, h - 20)
        p.setPen(QPen(QColor(255, 255, 255, 12), 1))
        chamber_grad = QLinearGradient(0, 0, 0, h)
        chamber_grad.setColorAt(0.0, QColor(13, 16, 23))
        chamber_grad.setColorAt(1.0, QColor(8, 10, 15))
        p.setBrush(chamber_grad)
        p.drawRoundedRect(chamber_rect, 16, 16)

        # 2. Ambient Colored Light Bleed behind Rig
        if self.is_powered:
            # Active zone color
            active_col = self.zone_colors.get(self.target_zone, (0, 240, 255))
            glow_grad = QRadialGradient(w / 2.0, h / 2.0, min(w, h) * 0.6)
            glow_grad.setColorAt(0.0, QColor(active_col[0], active_col[1], active_col[2], 30))
            glow_grad.setColorAt(0.7, QColor(active_col[0], active_col[1], active_col[2], 8))
            glow_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setBrush(glow_grad)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(chamber_rect, 16, 16)

        # 3. Render 3D Chassis Image
        side = min(w, h) - 36
        ox = (w - side) / 2.0
        oy = (h - side) / 2.0 + 4
        target_img_rect = QRectF(ox, oy, side, side)

        if self.current_pixmap and not self.current_pixmap.isNull():
            p.drawPixmap(target_img_rect.toRect(), self.current_pixmap)

        # 4. Interactive Target HUD Overlays
        f_hud = QFont("-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif", 9, QFont.Weight.Bold)
        p.setFont(f_hud)

        # Floating Hover Pill
        if self._hover_label:
            fm = QFontMetrics(f_hud)
            txt_w = fm.horizontalAdvance(self._hover_label) + 24
            pill_rect = QRectF((w - txt_w) / 2.0, 24, txt_w, 28)

            p.setPen(QPen(QColor(0, 240, 255, 180), 1))
            p.setBrush(QColor(10, 15, 24, 230))
            p.drawRoundedRect(pill_rect, 14, 14)

            p.setPen(QColor(0, 240, 255))
            p.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, self._hover_label)

        # Active Target Badge at bottom
        if not self.is_powered:
            badge_text = "○ ALL LIGHTS OFF • STEALTH BLACKOUT"
            p.setPen(QColor(100, 116, 139))
        else:
            names = {
                -1: "ALL HARDWARE SYNCHRONIZED",
                1: "ZONE 1 • FRONT INTAKE FANS",
                2: "ZONE 2 • TOP RADIATOR & REAR FANS",
                3: "ZONE 3 • MOTHERBOARD & 12V RGB",
                4: "ZONE 4 • DDR5 MEMORY RGB",
            }
            active_name = names.get(self.target_zone, "ALL HARDWARE SYNCHRONIZED")
            badge_text = f"● ACTIVE TARGET: {active_name}"
            p.setPen(QColor(140, 155, 175))

        f_sub = QFont("-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif", 8, QFont.Weight.DemiBold)
        p.setFont(f_sub)
        p.drawText(24, int(h - 22), badge_text)


class SaturationValuePicker(QWidget):
    """
    Precision 2D Saturation/Value Canvas (Figma/macOS style).
    Horizontal = Saturation (0..255).
    Vertical = Value (255..0).
    """
    colorSelected = pyqtSignal(QColor)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumSize(220, 130)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self.hue = 185
        self.sat = 255
        self.val = 255
        self._dragging = False

    def set_hue(self, hue: int):
        self.hue = max(0, min(360, hue))
        self.update()
        self._emit_color()

    def set_hsv(self, h: int, s: int, v: int):
        self.hue = max(0, min(359, h))
        self.sat = max(0, min(255, s))
        self.val = max(0, min(255, v))
        self.update()

    def _emit_color(self):
        color = QColor.fromHsv(self.hue % 360, self.sat, self.val)
        self.colorSelected.emit(color)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._update_from_pos(event.position().x(), event.position().y())

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            self._update_from_pos(event.position().x(), event.position().y())

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    def _update_from_pos(self, x: float, y: float):
        w = max(1.0, float(self.width() - 4))
        h = max(1.0, float(self.height() - 4))
        nx = max(0.0, min(1.0, (x - 2) / w))
        ny = max(0.0, min(1.0, (y - 2) / h))

        self.sat = int(nx * 255)
        self.val = int((1.0 - ny) * 255)
        self.update()
        self._emit_color()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        rect = QRectF(2, 2, w - 4, h - 4)

        pure_hue = QColor.fromHsv(self.hue % 360, 255, 255)
        grad_h = QLinearGradient(rect.left(), 0, rect.right(), 0)
        grad_h.setColorAt(0.0, QColor(255, 255, 255))
        grad_h.setColorAt(1.0, pure_hue)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad_h)
        p.drawRoundedRect(rect, 8, 8)

        grad_v = QLinearGradient(0, rect.top(), 0, rect.bottom())
        grad_v.setColorAt(0.0, QColor(0, 0, 0, 0))
        grad_v.setColorAt(1.0, QColor(0, 0, 0, 255))

        p.setBrush(grad_v)
        p.drawRoundedRect(rect, 8, 8)

        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 8, 8)

        cx = rect.left() + (self.sat / 255.0) * rect.width()
        cy = rect.top() + (1.0 - (self.val / 255.0)) * rect.height()

        p.setPen(QPen(QColor(0, 0, 0, 160), 3))
        p.drawEllipse(QPointF(cx, cy), 7, 7)
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.setBrush(QColor.fromHsv(self.hue % 360, self.sat, self.val))
        p.drawEllipse(QPointF(cx, cy), 6, 6)


class HueSlider(QWidget):
    """Precision 360° Hue rainbow slider."""
    hueChanged = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(24)
        self.setMinimumWidth(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hue = 185
        self._dragging = False

    def set_hue(self, hue: int):
        self.hue = max(0, min(359, hue))
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._update_from_pos(event.position().x())

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            self._update_from_pos(event.position().x())

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    def _update_from_pos(self, x: float):
        w = max(1.0, float(self.width() - 20))
        nx = max(0.0, min(1.0, (x - 10) / w))
        self.hue = int(nx * 359)
        self.update()
        self.hueChanged.emit(self.hue)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        track_rect = QRectF(10, 7, w - 20, 10)

        grad = QLinearGradient(track_rect.left(), 0, track_rect.right(), 0)
        for i in range(7):
            h_val = int(i * 60) % 360
            grad.setColorAt(i / 6.0, QColor.fromHsv(h_val, 255, 255))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(track_rect, 5, 5)

        tx = track_rect.left() + (self.hue / 359.0) * track_rect.width()
        ty = h / 2.0

        p.setPen(QPen(QColor(0, 0, 0, 160), 2))
        p.setBrush(QColor.fromHsv(self.hue % 360, 255, 255))
        p.drawEllipse(QPointF(tx, ty), 7, 7)
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(tx, ty), 6, 6)


class ModernGlowSlider(QWidget):
    """Linear glowing slider with integrated value readout."""
    valueChanged = pyqtSignal(int)

    def __init__(self, label: str, value: int = 100, min_v: int = 0, max_v: int = 100, unit: str = "%", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.label_title = label
        self.val = value
        self.min_v = min_v
        self.max_v = max_v
        self.unit = unit
        self.accent_color = QColor(0, 240, 255)
        self._dragging = False

    def set_value(self, v: int):
        self.val = max(self.min_v, min(self.max_v, v))
        self.update()

    def set_accent_color(self, c: QColor):
        self.accent_color = c
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._update_from_pos(event.position().x())

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            self._update_from_pos(event.position().x())

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    def _update_from_pos(self, x: float):
        w = max(1.0, float(self.width() - 20))
        nx = max(0.0, min(1.0, (x - 10) / w))
        self.val = int(self.min_v + nx * (self.max_v - self.min_v))
        self.update()
        self.valueChanged.emit(self.val)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        f_txt = QFont("-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif", 9, QFont.Weight.Bold)
        p.setFont(f_txt)
        p.setPen(QColor(160, 175, 195))
        p.drawText(10, 13, self.label_title.upper())

        val_txt = f"{self.val}{self.unit}"
        p.setPen(self.accent_color)
        fm = QFontMetrics(f_txt)
        vw = fm.horizontalAdvance(val_txt)
        p.drawText(w - 10 - vw, 13, val_txt)

        track_rect = QRectF(10, 22, w - 20, 6)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 14))
        p.drawRoundedRect(track_rect, 3, 3)

        frac = (self.val - self.min_v) / float(self.max_v - self.min_v)
        fill_w = max(6.0, track_rect.width() * frac)
        fill_rect = QRectF(10, 22, fill_w, 6)

        glow_grad = QLinearGradient(10, 0, 10 + fill_w, 0)
        glow_grad.setColorAt(0.0, QColor(self.accent_color.red(), self.accent_color.green(), self.accent_color.blue(), 140))
        glow_grad.setColorAt(1.0, self.accent_color)
        p.setBrush(glow_grad)
        p.drawRoundedRect(fill_rect, 3, 3)

        tx = 10 + fill_w
        ty = 25
        p.setPen(QPen(QColor(0, 0, 0, 140), 2))
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QPointF(tx, ty), 6, 6)


class SecondaryColorSwatch(QWidget):
    """Clickable dual-tone secondary accent color swatch."""
    colorChanged = pyqtSignal(QColor)

    def __init__(self, color: QColor = QColor(255, 100, 0), parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.color = color

    def set_color(self, c: QColor):
        self.color = c
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            chosen = QColorDialog.getColor(self.color, self, "Select Secondary Accent Color")
            if chosen.isValid():
                self.color = chosen
                self.update()
                self.colorChanged.emit(chosen)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        rect = QRectF(2, 2, w - 4, h - 4)

        p.setPen(QPen(QColor(255, 255, 255, 20), 1))
        p.setBrush(QColor(16, 22, 32))
        p.drawRoundedRect(rect, 8, 8)

        # Draw color circle
        p.setPen(QPen(QColor(255, 255, 255, 160), 1))
        p.setBrush(self.color)
        p.drawEllipse(QPointF(20, h / 2.0), 8, 8)

        # Draw label
        p.setFont(QFont("-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif", 9, QFont.Weight.DemiBold))
        p.setPen(QColor(200, 215, 235))
        hex_text = f"Secondary Color: {self.color.name().upper()}"
        p.drawText(QRectF(36, 0, w - 46, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, hex_text)
