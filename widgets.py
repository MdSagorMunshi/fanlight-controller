"""
widgets.py - Modern High-End UI Components for FanLight Studio
Features:
- Chassis3DViewer: Photorealistic 3D hardware visualizer with dynamic ARGB lighting and interactive zone hotspots
- SaturationValuePicker: Figma/macOS-style 2D color canvas
- HueSlider: Smooth 360° spectrum slider
- ModernGlowSlider: Precision linear slider with colored glowing track
"""

import os
import math
from typing import Optional, Tuple
from PIL import Image
import numpy as np

from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtGui import (
    QPainter, QColor, QLinearGradient, QRadialGradient,
    QPainterPath, QPen, QBrush, QFont, QFontMetrics,
    QPixmap, QImage, QMouseEvent, QWheelEvent
)
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal, QTimer


class Chassis3DViewer(QWidget):
    """
    Photorealistic 3D Gaming Chassis Visualizer.
    Renders high-resolution 3D render of the PC rig with dynamic real-time ARGB lighting,
    ambient light bleed, 60 FPS breathing/rainbow animation, and interactive component targeting.
    """
    targetZoneChanged = pyqtSignal(int)  # -1 = All, 1 = Case Fans, 2 = RAM

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumSize(440, 480)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

        self.target_zone = -1
        self.current_color = QColor(0, 240, 255)
        self.active_mode = "Static"
        self.brightness = 100
        self.speed = 50
        self.is_powered = True

        self._hover_zone: Optional[int] = None
        self._hover_label: str = ""
        self._anim_phase = 0.0
        self._rainbow_hue = 0.0

        # Load 3D assets in memory
        self.neutral_arr: Optional[np.ndarray] = None
        self.mask_arr: Optional[np.ndarray] = None
        self.current_pixmap: Optional[QPixmap] = None
        self._last_tint_key: Optional[Tuple] = None

        self._load_assets()

        # 60 FPS smooth animation timer
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
                self.mask_arr = np.array(Image.open(mask_path), dtype=np.float32) / 255.0
            except Exception as e:
                print(f"[Chassis3DViewer] Error loading assets: {e}")

    def set_hardware_state(self, color: QColor, mode: str, brightness: int, speed: int, is_powered: bool, target_zone: int):
        self.current_color = color
        self.active_mode = mode
        self.brightness = brightness
        self.speed = speed
        self.is_powered = is_powered
        self.target_zone = target_zone
        self._update_composite()
        self.update()

    def _on_tick(self):
        if not self.is_powered:
            return

        mode = self.active_mode.lower()
        if "breathing" in mode:
            speed_mult = 0.03 + (self.speed / 100.0) * 0.07
            self._anim_phase = (self._anim_phase + speed_mult) % (math.pi * 2)
            self.update()
        elif "rainbow" in mode or "spectrum" in mode:
            step = 0.8 + (self.speed / 100.0) * 3.5
            self._rainbow_hue = (self._rainbow_hue + step) % 360.0
            self._update_composite(hue_override=int(self._rainbow_hue))
            self.update()

    def _update_composite(self, hue_override: Optional[int] = None):
        if self.neutral_arr is None or self.mask_arr is None:
            return

        # Determine active color
        if hue_override is not None:
            active_col = QColor.fromHsv(hue_override % 360, 255, 255)
        else:
            active_col = self.current_color

        if not self.is_powered or self.active_mode.lower() == "off":
            target_rgb = np.array([0.0, 0.0, 0.0], dtype=np.float32)
            b_factor = 0.0
            col_scale = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        else:
            b_factor = max(0.05, self.brightness / 100.0)
            target_rgb = np.array([float(active_col.red()), float(active_col.green()), float(active_col.blue())], dtype=np.float32)
            col_scale = (target_rgb / 255.0) * 1.5 * b_factor

        key = (int(target_rgb[0]), int(target_rgb[1]), int(target_rgb[2]), round(b_factor, 2), self.is_powered, self.active_mode)
        if key == self._last_tint_key and hue_override is None:
            return
        self._last_tint_key = key

        # Tint the glowing regions using vector NumPy
        tinted = self.neutral_arr.copy()
        mask = self.mask_arr

        for c in range(3):
            if not self.is_powered or self.active_mode.lower() == "off":
                unlit_dim = self.neutral_arr[:, :, c] * 0.22
                tinted[:, :, c] = tinted[:, :, c] * (1.0 - mask) + unlit_dim * mask
            else:
                tinted[:, :, c] = tinted[:, :, c] * (1.0 - mask) + (self.neutral_arr[:, :, c] * col_scale[c]) * mask

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
        # Normalize to 1024x1024
        side = min(w, h) - 40
        ox = (w - side) / 2.0
        oy = (h - side) / 2.0
        if not (ox <= x <= ox + side and oy <= y <= oy + side):
            return (None, "")

        nx = (x - ox) / float(side) * 1024.0
        ny = (y - oy) / float(side) * 1024.0

        # Front Fans (right side of chassis)
        if 680 <= nx <= 850 and 260 <= ny <= 740:
            return (1, "Case Fans • Front ARGB (JARGB_V2_1)")
        # Rear Fan (left upper)
        if 160 <= nx <= 300 and 270 <= ny <= 480:
            return (1, "Case Fans • Rear Exhaust (JARGB_V2_2)")
        # DDR5 RAM (center-right of motherboard)
        if 480 <= nx <= 550 and 280 <= ny <= 520:
            return (2, "DDR5 Memory • ENE DRAM (SMBus 0x72)")
        # CPU Cooler (center pump)
        if 360 <= nx <= 470 and 340 <= ny <= 460:
            return (-1, "CPU AIO Cooler • Liquid Block")
        # Chassis general
        if 120 <= nx <= 880 and 80 <= ny <= 920:
            return (-1, "All Hardware • Synchronized Bus")

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
            mode = self.active_mode.lower()
            breath = (math.sin(self._anim_phase) + 1.0) * 0.5 if "breathing" in mode else 1.0
            col = self.current_color
            alpha = int(35 * (self.brightness / 100.0) * breath)
            glow_grad = QRadialGradient(w / 2.0, h / 2.0, min(w, h) * 0.6)
            glow_grad.setColorAt(0.0, QColor(col.red(), col.green(), col.blue(), alpha))
            glow_grad.setColorAt(0.7, QColor(col.red(), col.green(), col.blue(), int(alpha * 0.3)))
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
            # Breathing pulse modulation on the canvas
            if "breathing" in self.active_mode.lower() and self.is_powered:
                p.setOpacity(0.4 + 0.6 * ((math.sin(self._anim_phase) + 1.0) * 0.5))
            else:
                p.setOpacity(1.0)

            p.drawPixmap(target_img_rect.toRect(), self.current_pixmap)
            p.setOpacity(1.0)

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
        if not self.is_powered or self.active_mode.lower() == "off":
            badge_text = "○ ALL LIGHTS OFF • STEALTH BLACKOUT"
            p.setPen(QColor(100, 116, 139))
        else:
            active_name = "ALL HARDWARE SYNCHRONIZED" if self.target_zone == -1 else ("CASE FANS (JARGB)" if self.target_zone == 1 else "DDR5 MEMORY (ENE DRAM)")
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
        self.setMinimumSize(220, 140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self.hue = 185  # Cyan default
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
        r = QRectF(2, 2, w - 4, h - 4)

        # 1. Base pure hue layer
        pure_hue = QColor.fromHsv(self.hue % 360, 255, 255)
        grad_h = QLinearGradient(r.left(), 0, r.right(), 0)
        grad_h.setColorAt(0.0, QColor(255, 255, 255))
        grad_h.setColorAt(1.0, pure_hue)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad_h)
        p.drawRoundedRect(r, 8, 8)

        # 2. Vertical Black Value overlay (transparent to black)
        grad_v = QLinearGradient(0, r.top(), 0, r.bottom())
        grad_v.setColorAt(0.0, QColor(0, 0, 0, 0))
        grad_v.setColorAt(1.0, QColor(0, 0, 0, 255))
        p.setBrush(grad_v)
        p.drawRoundedRect(r, 8, 8)

        # Subtle border
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 8, 8)

        # 3. Interactive Precision Ring Cursor
        cx = r.left() + (self.sat / 255.0) * r.width()
        cy = r.bottom() - (self.val / 255.0) * r.height()

        p.setPen(QPen(QColor(0, 0, 0, 180), 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), 6, 6)

        p.setPen(QPen(QColor(255, 255, 255), 1.5))
        p.drawEllipse(QPointF(cx, cy), 5, 5)


class HueSlider(QWidget):
    """
    Horizontal 360° Rainbow Hue Slider with smooth draggable thumb.
    """
    hueChanged = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setMinimumWidth(200)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hue = 185
        self._dragging = False

    def set_hue(self, hue: int):
        self.hue = max(0, min(360, hue))
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
        w = max(1.0, float(self.width() - 16))
        nx = max(0.0, min(1.0, (x - 8) / w))
        self.hue = min(359, max(0, int(nx * 360)))
        self.update()
        self.hueChanged.emit(self.hue)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = QRectF(4, 5, w - 8, h - 10)

        # 360 Spectrum Gradient Track
        grad = QLinearGradient(r.left(), 0, r.right(), 0)
        for i in range(7):
            grad.setColorAt(i / 6.0, QColor.fromHsv(int(i * 60) % 360, 255, 255))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(r, 6, 6)

        # Subtle border
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 6, 6)

        # Thumb
        tx = r.left() + (self.hue / 360.0) * r.width()
        ty = h / 2.0

        p.setPen(QPen(QColor(0, 0, 0, 160), 2))
        p.setBrush(QColor.fromHsv(self.hue % 360, 255, 255))
        p.drawEllipse(QPointF(tx, ty), 6, 6)

        p.setPen(QPen(QColor(255, 255, 255), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(tx, ty), 6, 6)


class ModernGlowSlider(QWidget):
    """
    Sleek modern linear slider with colored glowing track fill and numeric pill tag.
    """
    valueChanged = pyqtSignal(int)

    def __init__(self, title: str, min_val: int = 0, max_val: int = 100, default_val: int = 100, unit: str = "%", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.title = title
        self.min_val = min_val
        self.max_val = max_val
        self.value = default_val
        self.unit = unit
        self.accent_color = QColor(0, 240, 255)

        self.setFixedHeight(38)
        self.setMinimumWidth(180)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dragging = False

    def set_value(self, val: int):
        val = max(self.min_val, min(self.max_val, val))
        if val != self.value:
            self.value = val
            self.update()
            self.valueChanged.emit(val)

    def set_accent_color(self, color: QColor):
        self.accent_color = color
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

    def wheelEvent(self, event: QWheelEvent):
        delta = 2 if event.angleDelta().y() > 0 else -2
        self.set_value(self.value + delta)

    def _update_from_pos(self, x: float):
        track_left = 10.0
        track_right = float(self.width() - 60)
        w = max(1.0, track_right - track_left)
        nx = max(0.0, min(1.0, (x - track_left) / w))
        val = int(round(self.min_val + nx * (self.max_val - self.min_val)))
        self.set_value(val)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Labels
        f_label = QFont("-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif", 9, QFont.Weight.DemiBold)
        p.setFont(f_label)
        p.setPen(QColor(140, 155, 175))
        p.drawText(10, 14, self.title)

        # Value pill at right
        val_str = f"{self.value}{self.unit}"
        p.setPen(QColor(255, 255, 255))
        f_val = QFont("JetBrains Mono", 9, QFont.Weight.Bold)
        p.setFont(f_val)
        p.drawText(int(w - 48), 14, val_str)

        # Track
        track_y = 26.0
        track_left = 10.0
        track_right = float(w - 60)
        track_w = track_right - track_left

        # Inactive background groove
        p.setPen(QPen(QColor(22, 28, 38), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(track_left, track_y), QPointF(track_right, track_y))

        # Active glowing fill
        norm = (self.value - self.min_val) / float(self.max_val - self.min_val)
        fill_x = track_left + norm * track_w

        if norm > 0.01:
            p.setPen(QPen(self.accent_color, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(track_left, track_y), QPointF(fill_x, track_y))

        # Circular Thumb
        p.setPen(QPen(QColor(10, 15, 22), 2))
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QPointF(fill_x, track_y), 6.5, 6.5)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.accent_color)
        p.drawEllipse(QPointF(fill_x, track_y), 3.5, 3.5)
