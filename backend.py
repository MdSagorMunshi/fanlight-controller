"""
backend.py - Hardware detection and Hybrid Controller interface for FanLight Controller
Supports:
- MSI AM5 Motherboards (B650M GAMING WIFI MS-7E30, X670, etc.)
- Direct Kernel HID driver for MSI Mystic Light MCU (0db0:0076) via /dev/hidraw
- Multi-Zone independent ARGB control (JARGB_V2_1, JARGB_V2_2, JRGB1, ONBOARD)
- OpenRGB interface for DDR5 RAM RGB (ENE DRAM over SMBus i2c-1 0x72)
- Real-time Hardware Temperature Monitoring (CPU, GPU, RAM) via /sys/class/hwmon
- Real-time 30FPS Software Procedural Animation Engine (Volatile SRAM streaming)
"""

import os
import sys
import time
import math
import glob
import socket
import struct
import subprocess
import threading
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Callable

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    from openrgb import OpenRGBClient
    from openrgb.utils import RGBColor
except ImportError:
    OpenRGBClient = None
    RGBColor = None


# Linux HIDRAW IOCTL definitions
def HIDIOCGFEATURE(length: int) -> int:
    return 0xC0004807 | (length << 16)


def HIDIOCSFEATURE(length: int) -> int:
    return 0xC0004806 | (length << 16)


# Target Zone Constants
TARGET_ALL = -1
TARGET_FRONT_FANS = 1      # JARGB_V2_1
TARGET_EXHAUST_FANS = 2    # JARGB_V2_2
TARGET_MOTHERBOARD = 3     # ONBOARD & JRGB1
TARGET_RAM = 4             # DDR5 Memory SMBus

TARGET_NAMES = {
    TARGET_ALL: "All Hardware (Synchronized)",
    TARGET_FRONT_FANS: "Front Intake Fans (JARGB_V2_1)",
    TARGET_EXHAUST_FANS: "Top & Rear Fans (JARGB_V2_2)",
    TARGET_MOTHERBOARD: "Motherboard & 12V RGB",
    TARGET_RAM: "DDR5 Memory (ENE DRAM)",
}


class MotherboardInfo:
    @staticmethod
    def get_info() -> Dict[str, str]:
        def read_dmi(name: str) -> str:
            path = f"/sys/class/dmi/id/{name}"
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        return f.read().strip()
                except Exception:
                    pass
            return "Unknown"

        board_vendor = read_dmi("board_vendor")
        board_name = read_dmi("board_name")
        product_name = read_dmi("product_name")
        bios_version = read_dmi("bios_version")
        bios_date = read_dmi("bios_date")

        cpu_name = "Unknown CPU"
        try:
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if "model name" in line:
                        cpu_name = line.split(":", 1)[1].strip()
                        break
        except Exception:
            pass

        return {
            "vendor": board_vendor,
            "board_name": board_name,
            "product_name": product_name,
            "bios_version": bios_version,
            "bios_date": bios_date,
            "cpu": cpu_name,
            "platform": "AMD AM5 (B650)",
        }


class HardwareSensors:
    """
    Direct zero-dependency reader for CPU, GPU, and RAM temperatures
    via Linux kernel /sys/class/hwmon subsystem.
    """
    _cached_temps = {"cpu": 45.0, "gpu": 40.0, "ram": 35.0}
    _last_read_time = 0.0

    @classmethod
    def get_temperatures(cls) -> Dict[str, float]:
        now = time.time()
        if now - cls._last_read_time < 0.8:
            return dict(cls._cached_temps)

        temps = dict(cls._cached_temps)
        try:
            for p in glob.glob("/sys/class/hwmon/hwmon*"):
                name_path = os.path.join(p, "name")
                if not os.path.exists(name_path):
                    continue
                with open(name_path, "r") as f:
                    name = f.read().strip().lower()

                # CPU: k10temp (AMD) or coretemp (Intel)
                if "k10temp" in name or "coretemp" in name:
                    for t in sorted(glob.glob(os.path.join(p, "temp*_input"))):
                        lbl_file = t.replace("_input", "_label")
                        lbl = open(lbl_file).read().strip().lower() if os.path.exists(lbl_file) else ""
                        try:
                            val = int(open(t).read().strip()) / 1000.0
                            if "tctl" in lbl or "composite" in lbl or "package" in lbl or temps["cpu"] is None:
                                temps["cpu"] = val
                        except Exception:
                            pass
                # GPU: amdgpu, nvidia, nouveau
                elif any(k in name for k in ["amdgpu", "nouveau", "nvidia"]):
                    for t in glob.glob(os.path.join(p, "temp*_input")):
                        try:
                            val = int(open(t).read().strip()) / 1000.0
                            temps["gpu"] = val
                            break
                        except Exception:
                            pass
                # RAM: spd5118, dimm, dram
                elif any(k in name for k in ["spd5118", "dram", "dimm"]):
                    for t in glob.glob(os.path.join(p, "temp*_input")):
                        try:
                            val = int(open(t).read().strip()) / 1000.0
                            temps["ram"] = val
                            break
                        except Exception:
                            pass
        except Exception:
            pass

        cls._cached_temps = temps
        cls._last_read_time = now
        return temps

    @staticmethod
    def temp_to_color(temp: float) -> Tuple[int, int, int]:
        """
        Maps a temperature value to a smooth RGB gradient:
        <= 35°C : Cool Cyan (0, 240, 255)
           50°C : Spring Neon Green (0, 255, 120)
           65°C : Warm Amber (255, 180, 0)
           75°C : Hot Orange (255, 60, 0)
        >= 85°C : Blazing Crimson Red (255, 0, 30)
        """
        stops = [
            (35.0, (0, 240, 255)),
            (50.0, (0, 255, 120)),
            (65.0, (255, 180, 0)),
            (75.0, (255, 60, 0)),
            (85.0, (255, 0, 30)),
        ]
        if temp <= stops[0][0]:
            return stops[0][1]
        if temp >= stops[-1][0]:
            return stops[-1][1]
        for i in range(len(stops) - 1):
            t1, c1 = stops[i]
            t2, c2 = stops[i + 1]
            if t1 <= temp <= t2:
                frac = (temp - t1) / (t2 - t1)
                r = int(c1[0] + (c2[0] - c1[0]) * frac)
                g = int(c1[1] + (c2[1] - c1[1]) * frac)
                b = int(c1[2] + (c2[2] - c1[2]) * frac)
                return (r, g, b)
        return stops[0][1]


@dataclass
class ZoneConfig:
    target_id: int
    name: str
    color: Tuple[int, int, int] = (0, 240, 255)
    secondary_color: Tuple[int, int, int] = (255, 100, 0)
    mode: str = "Static"
    brightness: int = 100
    speed: int = 50
    is_powered: bool = True
    temp_source: str = "cpu"  # "cpu", "gpu", or "ram"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_id": self.target_id,
            "name": self.name,
            "color": list(self.color),
            "secondary_color": list(self.secondary_color),
            "mode": self.mode,
            "brightness": self.brightness,
            "speed": self.speed,
            "is_powered": self.is_powered,
            "temp_source": self.temp_source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], default_target: int = 1, default_name: str = "Zone") -> "ZoneConfig":
        return cls(
            target_id=int(data.get("target_id", default_target)),
            name=str(data.get("name", default_name)),
            color=tuple(data.get("color", [0, 240, 255])),
            secondary_color=tuple(data.get("secondary_color", [255, 100, 0])),
            mode=str(data.get("mode", "Static")),
            brightness=int(data.get("brightness", 100)),
            speed=int(data.get("speed", 50)),
            is_powered=bool(data.get("is_powered", True)),
            temp_source=str(data.get("temp_source", "cpu")),
        )


class MSIMysticLightDirect:
    """
    Direct hardware driver for MSI Mystic Light USB microcontroller (VID 0x0DB0, PID 0x0076).
    Communicates directly with the USB HID interface (/dev/hidraw*) via Linux kernel ioctls.
    Supports multi-zone independent control across:
    - JRAINBOW1 (Front Intake Fans - 120 LEDs)
    - JRAINBOW2 (Radiator & Rear Fans - 120 LEDs)
    - JRGB1 (4-pin 12V RGB)
    - ONBOARD (Motherboard trace LEDs)
    """

    EFFECT_OFF = 0x00
    EFFECT_STATIC = 0x01
    EFFECT_BREATHING = 0x02
    EFFECT_FLASHING = 0x03
    EFFECT_DOUBLE_FLASHING = 0x04
    EFFECT_LIGHTNING = 0x05
    EFFECT_METEOR = 0x06
    EFFECT_COLOR_RING = 0x07
    EFFECT_PLANETARY = 0x08
    EFFECT_DOUBLE_METEOR = 0x09
    EFFECT_ENERGY = 0x0A
    EFFECT_BLINK = 0x0B
    EFFECT_CLOCK = 0x0C
    EFFECT_COLOR_PULSE = 0x0D
    EFFECT_COLOR_SHIFT = 0x0E
    EFFECT_COLOR_WAVE = 0x0F
    EFFECT_MARQUEE = 0x10
    EFFECT_RAINBOW = 0x1A
    EFFECT_VISOR = 0x1B
    EFFECT_RAINBOW_FLASHING = 0x1C
    EFFECT_COLOR_RING_DOUBLE_FLASHING = 0x1D
    EFFECT_STACK = 0x1E
    EFFECT_FIRE = 0x26

    MODE_MAP = {
        "off": EFFECT_OFF,
        "static": EFFECT_STATIC,
        "rainbow": EFFECT_RAINBOW,
        "rainbow wave": EFFECT_RAINBOW,
        "spectrum cycle": EFFECT_RAINBOW,
        "breathing": EFFECT_BREATHING,
        "meteor": EFFECT_METEOR,
        "meteor shower": EFFECT_METEOR,
        "lightning": EFFECT_LIGHTNING,
        "lightning storm": EFFECT_LIGHTNING,
        "planetary": EFFECT_PLANETARY,
        "planetary orbit": EFFECT_PLANETARY,
        "double meteor": EFFECT_DOUBLE_METEOR,
        "visor": EFFECT_VISOR,
        "visor scanner": EFFECT_VISOR,
        "fire": EFFECT_FIRE,
        "fire ember": EFFECT_FIRE,
        "stack": EFFECT_STACK,
        "stack cascade": EFFECT_STACK,
        "wave": EFFECT_COLOR_WAVE,
        "wave cascade": EFFECT_COLOR_WAVE,
        "color pulse": EFFECT_COLOR_PULSE,
        "color ring": EFFECT_COLOR_RING,
        "energy": EFFECT_ENERGY,
        "clock": EFFECT_CLOCK,
        "random flicker": EFFECT_FLASHING,
        "flashing": EFFECT_FLASHING,
        "starry twinkle": EFFECT_COLOR_PULSE,
    }

    REVERSE_MODE_MAP = {
        EFFECT_OFF: "Off",
        EFFECT_STATIC: "Static",
        EFFECT_BREATHING: "Breathing",
        EFFECT_RAINBOW: "Rainbow Wave",
        EFFECT_METEOR: "Meteor Shower",
        EFFECT_LIGHTNING: "Lightning Storm",
        EFFECT_PLANETARY: "Planetary Orbit",
        EFFECT_DOUBLE_METEOR: "Double Meteor",
        EFFECT_VISOR: "Visor Scanner",
        EFFECT_FIRE: "Fire Ember",
        EFFECT_STACK: "Stack Cascade",
        EFFECT_COLOR_WAVE: "Wave Cascade",
        EFFECT_COLOR_PULSE: "Starry Twinkle",
        EFFECT_FLASHING: "Random Flicker",
    }

    def __init__(self):
        self.device_path: Optional[str] = self.find_device_node()
        self.led_count = 120
        self.lock = threading.Lock()

    def find_device_node(self) -> Optional[str]:
        if os.path.exists("/sys/class/hidraw"):
            for dev_name in sorted(os.listdir("/sys/class/hidraw")):
                uevent_path = os.path.join("/sys/class/hidraw", dev_name, "device", "uevent")
                if os.path.exists(uevent_path):
                    try:
                        with open(uevent_path, "r") as f:
                            content = f.read().upper()
                            if ("0DB0" in content and "0076" in content) or "MYSTIC LIGHT" in content:
                                node = f"/dev/{dev_name}"
                                if os.path.exists(node):
                                    self.device_path = node
                                    return node
                    except Exception:
                        pass

        for fallback in ["/dev/hidraw2", "/dev/hidraw4", "/dev/hidraw6", "/dev/hidraw5", "/dev/hidraw3", "/dev/hidraw7"]:
            if os.path.exists(fallback):
                try:
                    fd = os.open(fallback, os.O_RDWR)
                    buf = bytearray(185)
                    buf[0] = 0x52
                    if fcntl is not None:
                        fcntl.ioctl(fd, HIDIOCGFEATURE(185), buf)
                    os.close(fd)
                    self.device_path = fallback
                    return fallback
                except Exception:
                    pass
        return None

    def is_available(self) -> bool:
        if fcntl is None:
            return False
        node = self.find_device_node()
        if node and os.path.exists(node):
            self.device_path = node
            return os.access(node, os.R_OK | os.W_OK)
        return False

    def _read_packet(self, fd: int) -> bytearray:
        buf = bytearray(185)
        buf[0] = 0x52
        if fcntl is not None:
            fcntl.ioctl(fd, HIDIOCGFEATURE(185), buf)
        return buf

    def _write_packet(self, fd: int, buf: bytearray, save: bool = True):
        if fcntl is None:
            return
        # 1. Live volatile commit (save_data = 0)
        buf[184] = 0
        fcntl.ioctl(fd, HIDIOCSFEATURE(185), buf)
        if save:
            time.sleep(0.015)
            # 2. Non-volatile commit to microcontroller flash (save_data = 1)
            buf[184] = 1
            fcntl.ioctl(fd, HIDIOCSFEATURE(185), buf)

    def _resolve_flags(self, brightness: int, speed: int, is_powered: bool) -> int:
        if not is_powered:
            return 0x00
        b_val = max(0, min(10, int(round((brightness / 100.0) * 10))))
        s_val = max(0, min(3, 3 - int(round((speed / 100.0) * 3))))
        # Bit 7 (0x80) is hardware power enable
        return (b_val << 2) | (s_val & 0x03) | 0x80

    def apply_zones(self, zones: Dict[int, ZoneConfig], save: bool = True) -> bool:
        """
        Applies independent configurations to each MSI hardware zone in a single packet.
        - Zone 1: Front Intake Fans (JARGB_V2_1, offset 31)
        - Zone 2: Radiator & Rear Fans (JARGB_V2_2, offset 42)
        - Zone 3: Motherboard & 12V RGB (JRGB1 offset 1, ONBOARD offset 74)
        """
        with self.lock:
            node = self.find_device_node() or self.device_path
            if not node or not os.path.exists(node):
                return False

            z1 = zones.get(TARGET_FRONT_FANS, ZoneConfig(TARGET_FRONT_FANS, "Front Fans"))
            z2 = zones.get(TARGET_EXHAUST_FANS, ZoneConfig(TARGET_EXHAUST_FANS, "Exhaust Fans"))
            z3 = zones.get(TARGET_MOTHERBOARD, ZoneConfig(TARGET_MOTHERBOARD, "Motherboard"))

            try:
                with open(node, "r+b", buffering=0) as f:
                    fd = f.fileno()
                    buf = self._read_packet(fd)

                    # 1. JRGB1 (4-pin 12V Analog RGB Header, offset 1, 10 bytes)
                    eff_z3 = self.MODE_MAP.get(z3.mode.lower(), self.EFFECT_STATIC) if z3.is_powered else self.EFFECT_OFF
                    flags_z3 = self._resolve_flags(z3.brightness, z3.speed, z3.is_powered)
                    color_flag_z3 = 0x00 if eff_z3 in [self.EFFECT_RAINBOW, self.EFFECT_RAINBOW_FLASHING] else 0x80
                    buf[1] = eff_z3
                    buf[2], buf[3], buf[4] = z3.color[0], z3.color[1], z3.color[2]
                    buf[5] = flags_z3
                    buf[6], buf[7], buf[8] = z3.secondary_color[0], z3.secondary_color[1], z3.secondary_color[2]
                    buf[9] = color_flag_z3

                    # 2. JARGB_V2_1 (3-pin 5V ARGB Front Intake Fans, offset 31, 11 bytes)
                    eff_z1 = self.MODE_MAP.get(z1.mode.lower(), self.EFFECT_STATIC) if z1.is_powered else self.EFFECT_OFF
                    flags_z1 = self._resolve_flags(z1.brightness, z1.speed, z1.is_powered)
                    color_flag_z1 = 0x00 if eff_z1 in [self.EFFECT_RAINBOW, self.EFFECT_RAINBOW_FLASHING] else 0x80
                    buf[31] = eff_z1
                    buf[32], buf[33], buf[34] = z1.color[0], z1.color[1], z1.color[2]
                    buf[35] = flags_z1
                    buf[36], buf[37], buf[38] = z1.secondary_color[0], z1.secondary_color[1], z1.secondary_color[2]
                    buf[39] = color_flag_z1
                    buf[40] = 0
                    buf[41] = self.led_count

                    # 3. JARGB_V2_2 (3-pin 5V ARGB Top Radiator & Rear Exhaust, offset 42, 11 bytes)
                    eff_z2 = self.MODE_MAP.get(z2.mode.lower(), self.EFFECT_STATIC) if z2.is_powered else self.EFFECT_OFF
                    flags_z2 = self._resolve_flags(z2.brightness, z2.speed, z2.is_powered)
                    color_flag_z2 = 0x00 if eff_z2 in [self.EFFECT_RAINBOW, self.EFFECT_RAINBOW_FLASHING] else 0x80
                    buf[42] = eff_z2
                    buf[43], buf[44], buf[45] = z2.color[0], z2.color[1], z2.color[2]
                    buf[46] = flags_z2
                    buf[47], buf[48], buf[49] = z2.secondary_color[0], z2.secondary_color[1], z2.secondary_color[2]
                    buf[50] = color_flag_z2
                    buf[51] = 0
                    buf[52] = self.led_count

                    # 4. ONBOARD (Motherboard trace LEDs, offset 74, 10 bytes)
                    buf[74] = eff_z3
                    buf[75], buf[76], buf[77] = z3.color[0], z3.color[1], z3.color[2]
                    buf[78] = flags_z3
                    buf[79], buf[80], buf[81] = z3.secondary_color[0], z3.secondary_color[1], z3.secondary_color[2]
                    buf[82] = color_flag_z3

                    self._write_packet(fd, buf, save=save)
                    return True
            except Exception as e:
                print(f"[MSIMysticLightDirect] Error writing zones: {e}", file=sys.stderr)
                return False

    def apply(
        self,
        mode: str = "Static",
        r: int = 0,
        g: int = 255,
        b: int = 204,
        brightness: int = 100,
        speed: int = 50,
        power: bool = True,
        save: bool = True
    ) -> bool:
        """Synchronized global apply across all zones."""
        cfg = ZoneConfig(
            target_id=TARGET_ALL,
            name="All",
            color=(r, g, b),
            mode=mode,
            brightness=brightness,
            speed=speed,
            is_powered=power
        )
        return self.apply_zones({
            TARGET_FRONT_FANS: cfg,
            TARGET_EXHAUST_FANS: cfg,
            TARGET_MOTHERBOARD: cfg,
        }, save=save)

    def read_state(self) -> Optional[Dict[str, Any]]:
        with self.lock:
            node = self.find_device_node() or self.device_path
            if not node or not os.path.exists(node):
                return None
            try:
                with open(node, "r+b", buffering=0) as f:
                    fd = f.fileno()
                    buf = self._read_packet(fd)
                    effect_id = buf[31]
                    r, g, b = buf[32], buf[33], buf[34]
                    flags = buf[35]
                    is_powered = (effect_id != self.EFFECT_OFF)
                    b_val = (flags >> 2) & 0x1F
                    brightness = int(round((b_val / 10.0) * 100)) if is_powered else 100
                    s_raw = flags & 0x03
                    speed = int(round(((3 - s_raw) / 3.0) * 100))
                    mode_name = self.REVERSE_MODE_MAP.get(effect_id, "Static")
                    return {
                        "is_powered": is_powered,
                        "mode": mode_name,
                        "r": r, "g": g, "b": b,
                        "brightness": max(10, min(100, brightness)),
                        "speed": max(10, min(100, speed)),
                    }
            except Exception as e:
                print(f"[MSIMysticLightDirect] Error reading state: {e}", file=sys.stderr)
                return None


class SoftwareAnimationEngine:
    """
    Real-time 30FPS background procedural animation engine.
    Computes frame-by-frame RGB outputs for dynamic modes:
    - Thermal Reactive (Hardware temperature heatmap)
    - Cyberpunk Dual Wave (Sinusoidal gradient sweep)
    - Heartbeat Pulse (Cardiac double-thump rhythm)
    - Aurora Borealis (Harmonic polar light wave)
    - Police Flasher (Emergency alternating strobe)
    """

    SOFTWARE_MODES = {
        "thermal reactive",
        "cyberpunk wave",
        "heartbeat pulse",
        "heartbeat",
        "aurora borealis",
        "aurora",
        "police flasher",
    }

    def __init__(self, backend: "FanLightBackend"):
        self.backend = backend
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._frame_callbacks: List[Callable[[Dict[int, Tuple[int, int, int]]], None]] = []
        self._phase = 0.0
        self._lock = threading.Lock()

    def add_callback(self, cb: Callable[[Dict[int, Tuple[int, int, int]]], None]):
        with self._lock:
            if cb not in self._frame_callbacks:
                self._frame_callbacks.append(cb)

    def is_needed(self) -> bool:
        if not self.backend.is_powered_on:
            return False
        for z in self.backend.zones.values():
            if z.is_powered and z.mode.lower() in self.SOFTWARE_MODES:
                return True
        return False

    def start(self):
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="FanLight-AnimationEngine")
            self._thread.start()

    def stop(self):
        with self._lock:
            self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
            self._thread = None

    def trigger_check(self):
        if self.is_needed():
            self.start()
        else:
            self.stop()

    def _run_loop(self):
        last_mcu_stream = 0.0
        last_temp_query = 0.0
        cached_temps = {"cpu": 45.0, "gpu": 40.0, "ram": 35.0}

        while self._running:
            start_t = time.perf_counter()
            now = time.time()

            if not self.is_needed():
                time.sleep(0.1)
                continue

            # Query temps once every 0.8s
            if now - last_temp_query > 0.8:
                cached_temps = HardwareSensors.get_temperatures()
                last_temp_query = now

            self._phase = (self._phase + 0.08) % (math.pi * 200.0)

            # Compute current frame colors for all zones
            frame_colors: Dict[int, Tuple[int, int, int]] = {}
            mcu_zones_to_update: Dict[int, ZoneConfig] = {}
            ram_color: Optional[Tuple[int, int, int]] = None

            for target_id, z in self.backend.zones.items():
                if not z.is_powered:
                    frame_colors[target_id] = (0, 0, 0)
                    continue

                mode_l = z.mode.lower()
                speed_scale = max(0.2, (z.speed / 50.0))
                p = self._phase * speed_scale

                col: Tuple[int, int, int] = z.color

                if "thermal reactive" in mode_l:
                    temp_val = cached_temps.get(z.temp_source, cached_temps.get("cpu", 50.0))
                    col = HardwareSensors.temp_to_color(temp_val)
                elif "cyberpunk" in mode_l:
                    # Sinusoidal blend between color and secondary_color
                    blend = (math.sin(p) + 1.0) / 2.0
                    r1, g1, b1 = z.color
                    r2, g2, b2 = z.secondary_color
                    col = (
                        int(r1 * (1.0 - blend) + r2 * blend),
                        int(g1 * (1.0 - blend) + g2 * blend),
                        int(b1 * (1.0 - blend) + b2 * blend),
                    )
                elif "heartbeat" in mode_l:
                    # Cardiac lub-dub pulse
                    t_cycle = (p * 0.5) % (math.pi * 2)
                    pulse1 = math.exp(-((t_cycle - 1.0) ** 2) / 0.12)
                    pulse2 = math.exp(-((t_cycle - 1.8) ** 2) / 0.16)
                    intensity = min(1.0, (pulse1 * 1.0 + pulse2 * 0.75) * 1.1 + 0.08)
                    r, g, b = z.color
                    col = (int(r * intensity), int(g * intensity), int(b * intensity))
                elif "aurora" in mode_l:
                    # Multi-harmonic polar wave (Cyan -> Emerald -> Purple)
                    w1 = (math.sin(p * 0.8) + 1.0) / 2.0
                    w2 = (math.cos(p * 1.1 + 1.2) + 1.0) / 2.0
                    r = int(20 * w1 + 160 * w2)
                    g = int(240 * w1 + 60 * w2)
                    b = int(200 * (1.0 - w1) + 240 * w2)
                    col = (min(255, r), min(255, g), min(255, b))
                elif "police" in mode_l:
                    # High contrast alternating strobe
                    strobe = int(p * 4.0) % 2
                    col = (255, 0, 10) if strobe == 0 else (0, 80, 255)
                else:
                    col = z.color

                # Apply zone brightness
                bfactor = z.brightness / 100.0
                col = (int(col[0] * bfactor), int(col[1] * bfactor), int(col[2] * bfactor))
                frame_colors[target_id] = col

                if target_id in [TARGET_FRONT_FANS, TARGET_EXHAUST_FANS, TARGET_MOTHERBOARD]:
                    mcu_zones_to_update[target_id] = ZoneConfig(
                        target_id=target_id,
                        name=z.name,
                        color=col,
                        mode="Static",
                        brightness=100,
                        speed=z.speed,
                        is_powered=True,
                    )
                elif target_id == TARGET_RAM:
                    ram_color = col

            # Stream volatile packet to MSI MCU (~30 FPS, save=False)
            if mcu_zones_to_update and (now - last_mcu_stream > 0.03):
                self.backend.mystic_direct.apply_zones(mcu_zones_to_update, save=False)
                last_mcu_stream = now

            # Stream to RAM
            if ram_color is not None:
                self.backend._stream_ram_color(ram_color[0], ram_color[1], ram_color[2])

            # Notify UI callbacks for 3D visualizer
            with self._lock:
                cbs = list(self._frame_callbacks)
            for cb in cbs:
                try:
                    cb(frame_colors)
                except Exception:
                    pass

            elapsed = time.perf_counter() - start_t
            sleep_time = max(0.005, 0.033 - elapsed)
            time.sleep(sleep_time)


class FanLightBackend:
    """
    Hybrid RGB Backend orchestrating:
    1. MSIMysticLightDirect: Case Fans & ARGB headers (Multi-Zone independent control).
    2. OpenRGB SDK: ENE DRAM RAM RGB modules over SMBus.
    3. HardwareSensors: Real-time CPU, GPU, RAM temperature reading.
    4. SoftwareAnimationEngine: 30FPS real-time streaming for procedural modes.
    """

    CONFIG_DIR = os.path.expanduser("~/.config/fanlight-controller")
    STATE_FILE = os.path.join(CONFIG_DIR, "state.json")

    def __init__(self, appimage_path: Optional[str] = None, port: int = 6742):
        if appimage_path and os.path.exists(appimage_path):
            self.appimage_path = appimage_path
        else:
            candidates = [
                os.path.expanduser("~/.local/share/fanlight-controller/OpenRGB.AppImage"),
                "/usr/bin/openrgb",
                "/usr/local/bin/openrgb",
            ]
            self.appimage_path = next((p for p in candidates if os.path.exists(p)), candidates[0])

        self.port = port
        self.server_proc: Optional[subprocess.Popen] = None
        self.client: Optional[OpenRGBClient] = None
        self.mystic_direct = MSIMysticLightDirect()
        self.is_connected = False
        self.is_powered_on = True
        self.selected_target_idx = TARGET_ALL
        self.lock = threading.Lock()

        # Initialize Default Zone Configurations
        self.zones: Dict[int, ZoneConfig] = {
            TARGET_FRONT_FANS: ZoneConfig(
                target_id=TARGET_FRONT_FANS,
                name="Front Intake Fans",
                color=(0, 240, 255),
                secondary_color=(255, 100, 0),
                mode="Static",
                brightness=100,
                speed=50,
                is_powered=True,
                temp_source="gpu"
            ),
            TARGET_EXHAUST_FANS: ZoneConfig(
                target_id=TARGET_EXHAUST_FANS,
                name="Top & Rear Fans",
                color=(0, 255, 120),
                secondary_color=(0, 150, 255),
                mode="Static",
                brightness=100,
                speed=50,
                is_powered=True,
                temp_source="cpu"
            ),
            TARGET_MOTHERBOARD: ZoneConfig(
                target_id=TARGET_MOTHERBOARD,
                name="Motherboard & 12V RGB",
                color=(180, 50, 255),
                secondary_color=(255, 0, 120),
                mode="Static",
                brightness=90,
                speed=50,
                is_powered=True,
                temp_source="cpu"
            ),
            TARGET_RAM: ZoneConfig(
                target_id=TARGET_RAM,
                name="DDR5 Memory",
                color=(0, 240, 255),
                secondary_color=(255, 0, 150),
                mode="Static",
                brightness=100,
                speed=50,
                is_powered=True,
                temp_source="ram"
            ),
        }

        # Shared global state for TARGET_ALL
        self.global_color = (0, 240, 255)
        self.global_secondary_color = (255, 100, 0)
        self.global_mode = "Static"
        self.global_brightness = 100
        self.global_speed = 50

        # Animation Streamer
        self.anim_engine = SoftwareAnimationEngine(self)

        # Load persisted settings
        self.load_saved_state()

    def get_temperatures(self) -> Dict[str, float]:
        return HardwareSensors.get_temperatures()

    def get_zone(self, target_idx: int) -> ZoneConfig:
        if target_idx == TARGET_ALL:
            return ZoneConfig(
                target_id=TARGET_ALL,
                name="All Hardware (Synchronized)",
                color=self.global_color,
                secondary_color=self.global_secondary_color,
                mode=self.global_mode,
                brightness=self.global_brightness,
                speed=self.global_speed,
                is_powered=self.is_powered_on,
            )
        return self.zones.get(target_idx, self.zones[TARGET_FRONT_FANS])

    def save_state(self):
        """Persists multi-zone and global lighting configuration to disk atomically."""
        try:
            os.makedirs(self.CONFIG_DIR, exist_ok=True)
            data = {
                "is_powered_on": self.is_powered_on,
                "global_mode": self.global_mode,
                "global_color": list(self.global_color),
                "global_secondary_color": list(self.global_secondary_color),
                "global_brightness": self.global_brightness,
                "global_speed": self.global_speed,
                "selected_target_idx": self.selected_target_idx,
                "zones": {str(k): v.to_dict() for k, v in self.zones.items()},
            }
            tmp_path = self.STATE_FILE + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.STATE_FILE)
        except Exception as e:
            print(f"[FanLightBackend] Save state error: {e}", file=sys.stderr)

    def load_saved_state(self) -> Dict[str, Any]:
        """Loads persisted state from disk if available."""
        if os.path.exists(self.STATE_FILE):
            try:
                if os.path.getsize(self.STATE_FILE) > 0:
                    with open(self.STATE_FILE, "r") as f:
                        data = json.load(f)
                        if "is_powered_on" in data:
                            self.is_powered_on = bool(data["is_powered_on"])
                        if "global_mode" in data:
                            self.global_mode = str(data["global_mode"])
                        elif "last_mode" in data:
                            self.global_mode = str(data["last_mode"])
                        if "global_color" in data and len(data["global_color"]) == 3:
                            self.global_color = tuple(data["global_color"])
                        elif "color" in data and len(data["color"]) == 3:
                            self.global_color = tuple(data["color"])
                        if "global_secondary_color" in data and len(data["global_secondary_color"]) == 3:
                            self.global_secondary_color = tuple(data["global_secondary_color"])
                        if "global_brightness" in data:
                            self.global_brightness = int(data["global_brightness"])
                        elif "brightness" in data:
                            self.global_brightness = int(data["brightness"])
                        if "global_speed" in data:
                            self.global_speed = int(data["global_speed"])
                        elif "speed" in data:
                            self.global_speed = int(data["speed"])
                        if "selected_target_idx" in data:
                            self.selected_target_idx = int(data["selected_target_idx"])
                        elif "target_idx" in data:
                            self.selected_target_idx = int(data["target_idx"])

                        if "zones" in data and isinstance(data["zones"], dict):
                            for k_str, z_dict in data["zones"].items():
                                try:
                                    k = int(k_str)
                                    if k in self.zones:
                                        self.zones[k] = ZoneConfig.from_dict(z_dict, k, self.zones[k].name)
                                except Exception:
                                    pass
                        return data
            except Exception as e:
                print(f"[FanLightBackend] Load state error: {e}", file=sys.stderr)
        return {}

    def sync_hardware_state(self) -> Dict[str, Any]:
        """Interrogates hardware registers and reconciles with state."""
        saved = self.load_saved_state()
        msi_state = self.mystic_direct.read_state()

        if msi_state is not None:
            hw_powered = msi_state.get("is_powered", False)
            if hw_powered:
                if msi_state.get("mode") and msi_state["mode"] != "Off":
                    self.global_mode = msi_state["mode"]
                if msi_state.get("r") is not None and (msi_state["r"], msi_state["g"], msi_state["b"]) != (0, 0, 0):
                    self.global_color = (msi_state["r"], msi_state["g"], msi_state["b"])
                if msi_state.get("brightness"):
                    self.global_brightness = msi_state["brightness"]
                if msi_state.get("speed") is not None:
                    self.global_speed = msi_state["speed"]
                self.is_powered_on = True
            else:
                self.is_powered_on = False

        self.apply_all_zones(save=False)
        self.anim_engine.trigger_check()

        return {
            "is_powered": self.is_powered_on,
            "mode": "Off" if not self.is_powered_on else self.global_mode,
            "color": self.global_color,
            "brightness": self.global_brightness,
            "speed": self.global_speed,
            "target_idx": self.selected_target_idx,
            "zones": {k: v.to_dict() for k, v in self.zones.items()},
        }

    def check_mystic_light_node(self) -> Tuple[bool, Optional[str]]:
        node = self.mystic_direct.find_device_node()
        if node and os.path.exists(node):
            return (os.access(node, os.W_OK), node)
        return (False, None)

    def is_port_open(self, host: str = "127.0.0.1", port: int = 6742) -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect((host, port))
            s.close()
            return True
        except Exception:
            return False

    def ensure_server_running(self) -> bool:
        if self.is_port_open("127.0.0.1", self.port):
            return True
        if not os.path.exists(self.appimage_path):
            return False

        try:
            popen_kwargs: Dict[str, Any] = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            if sys.platform != "win32" and hasattr(os, "setpgrp"):
                popen_kwargs["preexec_fn"] = os.setpgrp
            elif sys.platform == "win32":
                popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            self.server_proc = subprocess.Popen(
                [self.appimage_path, "--server", "--server-port", str(self.port), "--startminimized"],
                **popen_kwargs
            )
            for _ in range(10):
                time.sleep(0.5)
                if self.is_port_open("127.0.0.1", self.port):
                    return True
        except Exception as e:
            print(f"Error starting OpenRGB daemon: {e}", file=sys.stderr)
        return False

    def connect(self) -> bool:
        with self.lock:
            mystic_ready = self.mystic_direct.is_available()
            dram_ready = False
            if OpenRGBClient and self.ensure_server_running():
                try:
                    self.client = OpenRGBClient(port=self.port)
                    for _ in range(6):
                        if any("dram" in d.name.lower() or "ene" in d.name.lower() or "memory" in d.name.lower() for d in self.client.devices):
                            dram_ready = True
                            break
                        time.sleep(0.5)
                        try:
                            self.client.update()
                        except Exception:
                            pass
                    else:
                        dram_ready = len(self.client.devices) > 0
                except Exception as e:
                    print(f"OpenRGB connection notice: {e}", file=sys.stderr)
                    self.client = None

            self.is_connected = mystic_ready or dram_ready
            self.anim_engine.trigger_check()
            return self.is_connected

    def restart_server_and_reconnect(self) -> bool:
        with self.lock:
            self.is_connected = False
            self.client = None
            if self.server_proc:
                try:
                    self.server_proc.terminate()
                    self.server_proc.wait(timeout=2)
                except Exception:
                    pass
                self.server_proc = None

            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/IM", "OpenRGB.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.run(["pkill", "-f", "OpenRGB.*--server"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1)
        return self.connect()

    def get_devices(self) -> List[Dict[str, Any]]:
        devs = []
        is_w, node = self.check_mystic_light_node()
        devs.append({
            "index": TARGET_FRONT_FANS,
            "name": "MSI Mystic Light (Case Fans & Motherboard)",
            "type": "Motherboard / ARGB Controller",
            "node": node or "/dev/hidraw2",
            "status": "Active (Kernel Direct Driver)" if is_w else "Permission Locked",
            "zones": [
                "JARGB_V2_1 (Front Intake Fans)",
                "JARGB_V2_2 (Top Radiator & Rear Fans)",
                "JRGB1 (12V RGB)",
                "ONBOARD (Motherboard Traces)"
            ],
            "modes": list(self.mystic_direct.REVERSE_MODE_MAP.values()) + list(SoftwareAnimationEngine.SOFTWARE_MODES),
            "led_count": 120,
        })
        with self.lock:
            if self.client:
                try:
                    for d in self.client.devices:
                        if "dram" in d.name.lower() or "ene" in d.name.lower() or "memory" in d.name.lower():
                            devs.append({
                                "index": TARGET_RAM,
                                "name": f"{d.name} (RAM RGB)",
                                "type": "Memory RGB",
                                "node": "/dev/i2c-1 (0x72)",
                                "status": "Active (SMBus)",
                                "zones": [z.name for z in d.zones],
                                "modes": [m.name for m in d.modes],
                                "led_count": len(d.leds),
                            })
                            break
                except Exception:
                    pass
        return devs

    def apply_all_zones(self, save: bool = True):
        """Applies hardware configurations for all zones."""
        # 1. Apply MSI Mystic Light headers (Front fans, Rear fans, Motherboard)
        mcu_zones = {
            TARGET_FRONT_FANS: self.zones[TARGET_FRONT_FANS],
            TARGET_EXHAUST_FANS: self.zones[TARGET_EXHAUST_FANS],
            TARGET_MOTHERBOARD: self.zones[TARGET_MOTHERBOARD],
        }
        self.mystic_direct.apply_zones(mcu_zones, save=save)

        # 2. Apply RAM
        z_ram = self.zones[TARGET_RAM]
        if z_ram.is_powered and self.is_powered_on:
            self._apply_ram_mode(z_ram.mode, speed=z_ram.speed)
            self._apply_ram_color(z_ram.color[0], z_ram.color[1], z_ram.color[2])
        else:
            self._apply_ram_mode("Off")

        self.anim_engine.trigger_check()

    def set_color(self, r: int, g: int, b: int, target_idx: int = TARGET_ALL):
        """Sets primary color for a specific zone or all zones."""
        self.is_powered_on = True
        if target_idx == TARGET_ALL:
            self.global_color = (r, g, b)
            for z in self.zones.values():
                z.color = (r, g, b)
                z.is_powered = True
        elif target_idx in self.zones:
            self.zones[target_idx].color = (r, g, b)
            self.zones[target_idx].is_powered = True

        self.apply_all_zones(save=True)
        self.save_state()

    def set_secondary_color(self, r: int, g: int, b: int, target_idx: int = TARGET_ALL):
        """Sets secondary accent color (for dual-tone modes: Meteor, Cyberpunk, Lightning)."""
        if target_idx == TARGET_ALL:
            self.global_secondary_color = (r, g, b)
            for z in self.zones.values():
                z.secondary_color = (r, g, b)
        elif target_idx in self.zones:
            self.zones[target_idx].secondary_color = (r, g, b)

        self.apply_all_zones(save=True)
        self.save_state()

    def set_mode(self, mode_name: str, target_idx: int = TARGET_ALL, speed: Optional[int] = None):
        """Sets animation mode/effect for a specific zone or all zones."""
        is_off = (mode_name.lower() == "off")
        if target_idx == TARGET_ALL:
            self.global_mode = mode_name
            self.is_powered_on = not is_off
            if speed is not None:
                self.global_speed = speed
            for z in self.zones.values():
                z.mode = mode_name
                z.is_powered = not is_off
                if speed is not None:
                    z.speed = speed
        elif target_idx in self.zones:
            self.zones[target_idx].mode = mode_name
            self.zones[target_idx].is_powered = not is_off
            if speed is not None:
                self.zones[target_idx].speed = speed

        self.apply_all_zones(save=True)
        self.save_state()

    def set_brightness(self, brightness: int, target_idx: int = TARGET_ALL):
        """Sets brightness (0 - 100%)."""
        val = max(0, min(100, brightness))
        if target_idx == TARGET_ALL:
            self.global_brightness = val
            for z in self.zones.values():
                z.brightness = val
        elif target_idx in self.zones:
            self.zones[target_idx].brightness = val

        self.apply_all_zones(save=True)
        self.save_state()

    def set_speed(self, speed: int, target_idx: int = TARGET_ALL):
        """Sets animation speed (0 - 100%)."""
        val = max(0, min(100, speed))
        if target_idx == TARGET_ALL:
            self.global_speed = val
            for z in self.zones.values():
                z.speed = val
        elif target_idx in self.zones:
            self.zones[target_idx].speed = val

        self.apply_all_zones(save=True)
        self.save_state()

    def set_power(self, power_on: bool, target_idx: int = TARGET_ALL):
        """Toggles power ON/OFF for target zone or all hardware."""
        if target_idx == TARGET_ALL:
            self.is_powered_on = power_on
            for z in self.zones.values():
                z.is_powered = power_on
        elif target_idx in self.zones:
            self.zones[target_idx].is_powered = power_on
            # If any zone is powered, main power is on
            self.is_powered_on = any(z.is_powered for z in self.zones.values())

        self.apply_all_zones(save=True)
        self.save_state()

    def set_temp_source(self, source: str, target_idx: int = TARGET_ALL):
        """Configures which temperature sensor ('cpu', 'gpu', 'ram') drives thermal lighting."""
        if target_idx == TARGET_ALL:
            for z in self.zones.values():
                z.temp_source = source
        elif target_idx in self.zones:
            self.zones[target_idx].temp_source = source
        self.save_state()

    def _apply_ram_color(self, r: int, g: int, b: int):
        factor = self.zones[TARGET_RAM].brightness / 100.0 if self.zones[TARGET_RAM].is_powered else 0.0
        ar, ag, ab = int(r * factor), int(g * factor), int(b * factor)
        hex_color = f"{ar:02X}{ag:02X}{ab:02X}"

        applied = False
        with self.lock:
            if self.client and RGBColor:
                color = RGBColor(ar, ag, ab)
                try:
                    for dev in self.client.devices:
                        if any(k in dev.name.lower() for k in ["dram", "ene", "memory"]):
                            active_mode = dev.modes[dev.active_mode]
                            if active_mode.name.lower() in ["off", "rainbow", "spectrum cycle", "random flicker"]:
                                static_mode = next((m for m in dev.modes if m.name.lower() == "static"), None)
                                if static_mode:
                                    dev.set_mode(static_mode, save=True)
                            dev.set_color(color)
                            applied = True
                except Exception as e:
                    print(f"[RAM Controller] Color client error: {e}", file=sys.stderr)
                    applied = False

        if not applied and os.path.exists(self.appimage_path):
            try:
                subprocess.run(
                    [self.appimage_path, "--device", "0", "--mode", "Static", "--color", hex_color],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=4,
                )
            except Exception as e:
                print(f"[RAM Controller] CLI color fallback error: {e}", file=sys.stderr)

    def _stream_ram_color(self, r: int, g: int, b: int):
        """Fast volatile RAM color update for animation streaming without disk write."""
        if self.client and RGBColor:
            try:
                color = RGBColor(r, g, b)
                for dev in self.client.devices:
                    if any(k in dev.name.lower() for k in ["dram", "ene", "memory"]):
                        dev.set_color(color)
            except Exception:
                pass

    def _apply_ram_mode(self, mode_name: str, speed: Optional[int] = None):
        openrgb_mode_map = {
            "rainbow": "Rainbow",
            "rainbow wave": "Rainbow",
            "spectrum cycle": "Spectrum Cycle",
            "breathing": "Breathing",
            "static": "Static",
            "off": "Off",
            "random flicker": "Random Flicker",
            "chase fade": "Chase Fade",
            "chase": "Chase",
            "flashing": "Flashing",
        }
        target_mode = openrgb_mode_map.get(mode_name.lower(), "Static")
        z_ram = self.zones[TARGET_RAM]
        factor = z_ram.brightness / 100.0 if z_ram.is_powered else 0.0
        ar, ag, ab = int(z_ram.color[0] * factor), int(z_ram.color[1] * factor), int(z_ram.color[2] * factor)
        hex_color = f"{ar:02X}{ag:02X}{ab:02X}"

        applied = False
        with self.lock:
            if self.client:
                try:
                    for dev in self.client.devices:
                        if any(k in dev.name.lower() for k in ["dram", "ene", "memory"]):
                            matched = next((m for m in dev.modes if m.name.lower() == target_mode.lower()), None)
                            if matched:
                                if speed is not None and matched.speed_min is not None and matched.speed_max is not None:
                                    s_min = matched.speed_min
                                    s_max = matched.speed_max
                                    mapped = int(s_min + (s_max - s_min) * (speed / 100.0))
                                    matched.speed = mapped

                                dev.set_mode(matched, save=True)
                                if matched.name == "Off" and RGBColor:
                                    dev.set_color(RGBColor(0, 0, 0))
                                elif matched.name in ["Static", "Breathing", "Direct", "Flashing", "Chase Fade", "Chase"] and RGBColor:
                                    dev.set_color(RGBColor(ar, ag, ab))
                                applied = True
                except Exception as e:
                    print(f"[RAM Controller] Mode client error: {e}", file=sys.stderr)
                    applied = False

        if not applied and os.path.exists(self.appimage_path):
            try:
                cmd = [self.appimage_path, "--device", "0", "--mode", target_mode]
                if target_mode == "Off":
                    cmd.extend(["--color", "000000"])
                elif target_mode in ["Static", "Breathing"]:
                    cmd.extend(["--color", hex_color])
                subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=4,
                )
            except Exception as e:
                print(f"[RAM Controller] CLI mode fallback error: {e}", file=sys.stderr)

    def unlock_hardware_permissions(self) -> Tuple[bool, str]:
        script_path = os.path.expanduser("~/.config/openrgb_rules/install_rules.sh")
        if not os.path.exists(script_path):
            return False, f"Install script not found at {script_path}"

        try:
            env = os.environ.copy()
            if "DISPLAY" not in env:
                env["DISPLAY"] = ":0.0"
            if "XAUTHORITY" not in env:
                env["XAUTHORITY"] = os.path.expanduser("~/.Xauthority")

            res = subprocess.run(
                ["pkexec", script_path],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            if res.returncode == 0:
                self.restart_server_and_reconnect()
                return True, "Permissions successfully unlocked! Rescanning hardware..."
            else:
                return False, f"Permission authorization failed: {res.stderr.strip() or 'Request dismissed'}"
        except subprocess.TimeoutExpired:
            return False, "Authentication prompt timed out."
        except Exception as e:
            return False, f"Error running pkexec: {e}"
