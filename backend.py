"""
backend.py - Hardware detection and Hybrid Controller interface for FanLight Controller
Motherboard: MSI B650M GAMING WIFI (MS-7E30)
Case Fans & ARGB: Direct Kernel HID driver for MSI Mystic Light (0db0:0076) via /dev/hidraw4
RAM RGB: OpenRGB controller interface for ENE DRAM (I2C /dev/i2c-1, address 0x72)
"""

import os
import sys
import time
import socket
import struct
import subprocess
import threading
import json
from typing import Dict, List, Optional, Tuple, Any

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

        # CPU info
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


class MSIMysticLightDirect:
    """
    Direct hardware driver for MSI Mystic Light USB microcontroller (VID 0x0DB0, PID 0x0076).
    Communicates directly with the USB HID interface (/dev/hidraw4) via Linux kernel ioctls.
    Solves the case fans lighting issue by:
    1. Setting LED count on JRAINBOW1 and JRAINBOW2 to 120 (preventing OpenRGB zero-LED dark headers).
    2. Setting bit 7 (0x80) on speedAndBrightnessFlags to explicitly enable physical hardware outputs.
    3. Writing Report 0x52 with two-packet commit (volatile RAM + non-volatile flash).
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
    EFFECT_ENERGY = 0x0a
    EFFECT_BLINK = 0x0b
    EFFECT_CLOCK = 0x0c
    EFFECT_COLOR_PULSE = 0x0d
    EFFECT_COLOR_SHIFT = 0x0e
    EFFECT_COLOR_WAVE = 0x0f
    EFFECT_MARQUEE = 0x10
    EFFECT_RAINBOW = 0x1a
    EFFECT_VISOR = 0x1b
    EFFECT_RAINBOW_FLASHING = 0x1c
    EFFECT_COLOR_RING_DOUBLE_FLASHING = 0x1d
    EFFECT_STACK = 0x1e
    EFFECT_FIRE = 0x26

    MODE_MAP = {
        "off": EFFECT_OFF,
        "static": EFFECT_STATIC,
        "breathing": EFFECT_BREATHING,
        "flashing": EFFECT_FLASHING,
        "double flashing": EFFECT_DOUBLE_FLASHING,
        "lightning": EFFECT_LIGHTNING,
        "meteor": EFFECT_METEOR,
        "color ring": EFFECT_COLOR_RING,
        "planetary": EFFECT_PLANETARY,
        "double meteor": EFFECT_DOUBLE_METEOR,
        "energy": EFFECT_ENERGY,
        "blink": EFFECT_BLINK,
        "clock": EFFECT_CLOCK,
        "color pulse": EFFECT_COLOR_PULSE,
        "color shift": EFFECT_COLOR_SHIFT,
        "color wave": EFFECT_COLOR_WAVE,
        "marquee": EFFECT_MARQUEE,
        "rainbow": EFFECT_RAINBOW,
        "rainbow wave": EFFECT_RAINBOW,
        "spectrum cycle": EFFECT_RAINBOW,
        "visor": EFFECT_VISOR,
        "rainbow flashing": EFFECT_RAINBOW_FLASHING,
        "color ring double flashing": EFFECT_COLOR_RING_DOUBLE_FLASHING,
        "stack": EFFECT_STACK,
        "fire": EFFECT_FIRE,
        "chase fade": EFFECT_COLOR_WAVE,
        "random flicker": EFFECT_FLASHING,
    }

    REVERSE_MODE_MAP = {
        EFFECT_OFF: "Off",
        EFFECT_STATIC: "Static",
        EFFECT_BREATHING: "Breathing",
        EFFECT_FLASHING: "Random Flicker",
        EFFECT_COLOR_WAVE: "Chase Fade",
        EFFECT_RAINBOW: "Rainbow",
        EFFECT_FIRE: "Fire",
    }

    def __init__(self):
        self.device_path: Optional[str] = self.find_device_node()
        self.led_count = 120  # Sufficient for multiple daisy-chained ARGB case fans
        self.lock = threading.Lock()

    def find_device_node(self) -> Optional[str]:
        """Finds the hidraw character device matching MSI Mystic Light (0db0:0076)."""
        if os.path.exists("/sys/class/hidraw"):
            for dev_name in sorted(os.listdir("/sys/class/hidraw")):
                uevent_path = os.path.join("/sys/class/hidraw", dev_name, "device", "uevent")
                if os.path.exists(uevent_path):
                    try:
                        with open(uevent_path, "r") as f:
                            content = f.read().upper()
                            # Kernel reports HID_ID=0003:00000DB0:00000076 or HID_NAME=MSI MYSTIC LIGHT
                            if ("0DB0" in content and "0076" in content) or "MYSTIC LIGHT" in content:
                                node = f"/dev/{dev_name}"
                                if os.path.exists(node):
                                    self.device_path = node
                                    return node
                    except Exception:
                        pass

        # Fallback probe
        for fallback in ["/dev/hidraw6", "/dev/hidraw4", "/dev/hidraw5", "/dev/hidraw3", "/dev/hidraw7"]:
            if os.path.exists(fallback):
                try:
                    fd = os.open(fallback, os.O_RDWR)
                    buf = bytearray(185)
                    buf[0] = 0x52
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

    def apply(
        self,
        mode: str = "Static",
        r: int = 0,
        g: int = 255,
        b: int = 204,
        brightness: int = 100,
        speed: int = 50,
        power: bool = True
    ) -> bool:
        """
        Applies lighting effect and colors to JRAINBOW1, JRAINBOW2, JRGB1, and ONBOARD headers.
        """
        with self.lock:
            node = self.find_device_node() or self.device_path
            if not node or not os.path.exists(node):
                return False

            effect_id = self.MODE_MAP.get(mode.lower(), self.EFFECT_STATIC)
            if not power:
                effect_id = self.EFFECT_OFF

            # Scale brightness: 0..10
            b_val = max(0, min(10, int(round((brightness / 100.0) * 10)))) if power else 0
            # Speed: 0..3 (0=fastest/standard, 1=medium, 2=slow, 3=slowest)
            s_val = max(0, min(3, 3 - int(round((speed / 100.0) * 3))))

            # Hardware enable flag: bit 7 (0x80) is required on modern MSI boards to un-gate outputs!
            flags = (b_val << 2) | (s_val & 0x03) | 0x80 if power else 0x00

            # Color flag: 0x80 = custom color (static, breathing, etc.), 0x00 = spectrum / rainbow wave
            color_flag = 0x00 if effect_id in [self.EFFECT_RAINBOW, self.EFFECT_RAINBOW_FLASHING] else 0x80

            try:
                with open(node, "r+b", buffering=0) as f:
                    fd = f.fileno()
                    buf = self._read_packet(fd)

                    # 1. JRGB1 (4-pin 12V RGB Header, offset 1, 10 bytes)
                    buf[1] = effect_id
                    buf[2] = r; buf[3] = g; buf[4] = b
                    buf[5] = flags
                    buf[9] = color_flag

                    # 2. JRAINBOW1 (3-pin 5V ARGB Header 1 - Case Fans, offset 31, 11 bytes)
                    buf[31] = effect_id
                    buf[32] = r; buf[33] = g; buf[34] = b
                    buf[35] = flags
                    buf[39] = color_flag
                    buf[41] = self.led_count

                    # 3. JRAINBOW2 (3-pin 5V ARGB Header 2 - Case Fans, offset 42, 11 bytes)
                    buf[42] = effect_id
                    buf[43] = r; buf[44] = g; buf[45] = b
                    buf[46] = flags
                    buf[50] = color_flag
                    buf[52] = self.led_count

                    # 4. ONBOARD (Motherboard trace LEDs, offset 74, 10 bytes)
                    buf[74] = effect_id
                    buf[75] = r; buf[76] = g; buf[77] = b
                    buf[78] = flags
                    buf[82] = color_flag

                    self._write_packet(fd, buf, save=True)
                    return True
            except Exception as e:
                print(f"[MSIMysticLightDirect] Error writing to {node}: {e}", file=sys.stderr)
                return False

    def read_state(self) -> Optional[Dict[str, Any]]:
        """Reads live hardware registers from MSI Mystic Light MCU."""
        with self.lock:
            node = self.find_device_node() or self.device_path
            if not node or not os.path.exists(node):
                return None
            try:
                with open(node, "r+b", buffering=0) as f:
                    fd = f.fileno()
                    buf = self._read_packet(fd)
                    # Check JARGB_V2_1 zone (offset 31)
                    effect_id = buf[31]
                    r, g, b = buf[32], buf[33], buf[34]
                    flags = buf[35]
                    # Hardware effect 0x00 is Off, any non-zero effect is active/powered
                    is_powered = (effect_id != self.EFFECT_OFF)
                    b_val = (flags >> 2) & 0x1f
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
                print(f"[MSIMysticLightDirect] Error reading state from {node}: {e}", file=sys.stderr)
                return None


class FanLightBackend:
    """
    Hybrid RGB Backend orchestrating both:
    1. MSIMysticLightDirect: Case fan lights, ARGB headers, motherboard LEDs.
    2. OpenRGB SDK: ENE DRAM RAM RGB modules.
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
        self.last_color = (0, 240, 255)  # Cyan default
        self.last_mode = "Static"
        self.current_brightness = 100
        self.current_speed = 50
        self.selected_target_idx = -1
        self.lock = threading.Lock()

        # Load persisted settings immediately on instantiation
        self.load_saved_state()

    def save_state(self):
        """Persists current lighting configuration and power state to disk atomically."""
        try:
            os.makedirs(self.CONFIG_DIR, exist_ok=True)
            data = {
                "is_powered_on": self.is_powered_on,
                "last_mode": self.last_mode,
                "color": list(self.last_color),
                "brightness": self.current_brightness,
                "speed": self.current_speed,
                "target_idx": self.selected_target_idx,
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
                        if "last_mode" in data and data["last_mode"]:
                            self.last_mode = str(data["last_mode"])
                        if "color" in data and len(data["color"]) == 3:
                            self.last_color = tuple(data["color"])
                        if "brightness" in data:
                            self.current_brightness = int(data["brightness"])
                        if "speed" in data:
                            self.current_speed = int(data["speed"])
                        if "target_idx" in data:
                            self.selected_target_idx = int(data["target_idx"])
                        return data
            except Exception as e:
                print(f"[FanLightBackend] Load state error: {e}", file=sys.stderr)
        return {}

    def sync_hardware_state(self) -> Dict[str, Any]:
        """
        Interrogates physical hardware registers (MSI USB HID + OpenRGB DRAM)
        and reconciles with disk state.
        """
        saved = self.load_saved_state()
        msi_state = self.mystic_direct.read_state()

        dram_mode = None
        dram_color = None
        if self.client:
            try:
                for d in self.client.devices:
                    if any(k in d.name.lower() for k in ["dram", "ene", "memory"]):
                        if d.modes and 0 <= d.active_mode < len(d.modes):
                            dram_mode = d.modes[d.active_mode].name
                        if d.colors and len(d.colors) > 0:
                            dram_color = (d.colors[0].red, d.colors[0].green, d.colors[0].blue)
                        break
            except Exception:
                pass

        # Check if hardware physically reports powered off
        hw_powered = None
        if msi_state is not None:
            hw_powered = msi_state.get("is_powered", False)
            if hw_powered:
                if msi_state.get("mode") and msi_state["mode"] != "Off":
                    self.last_mode = msi_state["mode"]
                if msi_state.get("r") is not None and (msi_state["r"], msi_state["g"], msi_state["b"]) != (0, 0, 0):
                    self.last_color = (msi_state["r"], msi_state["g"], msi_state["b"])
                if msi_state.get("brightness"):
                    self.current_brightness = msi_state["brightness"]
                if msi_state.get("speed") is not None:
                    self.current_speed = msi_state["speed"]

        if dram_mode is not None:
            if dram_mode.lower() == "off":
                if hw_powered is None or not hw_powered:
                    hw_powered = False
            else:
                if hw_powered is None:
                    hw_powered = True

        if hw_powered is not None:
            self.is_powered_on = hw_powered
        elif "is_powered_on" in saved:
            self.is_powered_on = bool(saved["is_powered_on"])

        # Never let fallback last_mode be "Off" when turned on
        if self.last_mode.lower() == "off":
            if saved.get("last_mode") and saved["last_mode"].lower() != "off":
                self.last_mode = saved["last_mode"]
            else:
                self.last_mode = "Static"

        return {
            "is_powered": self.is_powered_on,
            "mode": "Off" if not self.is_powered_on else self.last_mode,
            "last_active_mode": self.last_mode,
            "color": self.last_color,
            "brightness": self.current_brightness,
            "speed": self.current_speed,
            "target_idx": self.selected_target_idx,
            "msi_raw": msi_state,
            "dram_mode": dram_mode,
        }

    def check_mystic_light_node(self) -> Tuple[bool, Optional[str]]:
        """
        Checks if the MSI Mystic Light hidraw node exists and whether it is writable.
        Returns (is_writable, node_path)
        """
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
        """Starts OpenRGB SDK server daemon for RAM control if not already listening."""
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
        """Initializes direct hardware controllers and connects to OpenRGB for DRAM."""
        with self.lock:
            # Check direct Mystic Light hardware
            mystic_ready = self.mystic_direct.is_available()

            # Connect to OpenRGB for RAM
            dram_ready = False
            if OpenRGBClient and self.ensure_server_running():
                try:
                    self.client = OpenRGBClient(port=self.port)
                    # Allow up to 3 seconds for OpenRGB daemon to finish I2C SMBus enumeration
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
            return self.is_connected

    def restart_server_and_reconnect(self) -> bool:
        """Restarts the OpenRGB server daemon and reconnects."""
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
        """
        Returns structured list of controllable hardware zones:
        - Index 0: Case Fans & ARGB Headers (MSI Mystic Light Direct Driver)
        - Index 1: RAM RGB (ENE DRAM via OpenRGB)
        """
        devs = []

        # 1. MSI Mystic Light (Direct hardware driver)
        is_w, node = self.check_mystic_light_node()
        devs.append({
            "index": 1,  # Target ID 1 for Case Fans
            "name": "MSI Mystic Light (Case Fans & ARGB Headers)",
            "type": "Motherboard / ARGB Controller",
            "node": node or "/dev/hidraw4",
            "status": "Active (Kernel Direct Driver)" if is_w else "Permission Locked",
            "zones": ["JARGB_V2_1 (Case Fans)", "JARGB_V2_2 (Case Fans)", "JRGB1 (12V RGB)", "ONBOARD"],
            "modes": ["Static", "Rainbow Wave", "Breathing", "Spectrum Cycle", "Chase Fade", "Random Flicker", "Fire", "Off"],
            "led_count": 120,
        })

        # 2. ENE DRAM (RAM RGB)
        with self.lock:
            if self.client:
                try:
                    for d in self.client.devices:
                        if "dram" in d.name.lower() or "ene" in d.name.lower() or "memory" in d.name.lower():
                            devs.append({
                                "index": 2,  # Target ID 2 for RAM
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

    def set_color(self, r: int, g: int, b: int, target_idx: int = -1):
        """
        Sets color.
        target_idx:
          -1 : All devices (Case Fans + RAM)
           1 : Case Fans & ARGB Headers only
           2 : RAM RGB only
        """
        self.last_color = (r, g, b)
        self.is_powered_on = True

        # 1. Update Case Fans / ARGB Headers via Direct Driver
        if target_idx in [-1, 1]:
            self.mystic_direct.apply(
                mode=self.last_mode if self.last_mode != "Off" else "Static",
                r=r, g=g, b=b,
                brightness=self.current_brightness,
                speed=self.current_speed,
                power=True,
            )

        # 2. Update RAM RGB via OpenRGB Client
        if target_idx in [-1, 2]:
            self._apply_ram_color(r, g, b)
        self.save_state()

    def set_mode(self, mode_name: str, target_idx: int = -1, speed: Optional[int] = None):
        """Sets lighting mode/effect."""
        self.last_mode = mode_name
        self.is_powered_on = (mode_name.lower() != "off")
        if speed is not None:
            self.current_speed = max(0, min(100, speed))

        r, g, b = self.last_color

        # 1. Update Case Fans / ARGB Headers
        if target_idx in [-1, 1]:
            self.mystic_direct.apply(
                mode=mode_name,
                r=r, g=g, b=b,
                brightness=self.current_brightness,
                speed=self.current_speed,
                power=self.is_powered_on,
            )

        # 2. Update RAM RGB
        if target_idx in [-1, 2]:
            self._apply_ram_mode(mode_name, speed=self.current_speed)
        self.save_state()

    def set_brightness(self, brightness: int, target_idx: int = -1):
        """Sets brightness (0 - 100%)."""
        self.current_brightness = max(0, min(100, brightness))
        if self.is_powered_on:
            r, g, b = self.last_color
            if target_idx in [-1, 1]:
                self.mystic_direct.apply(
                    mode=self.last_mode,
                    r=r, g=g, b=b,
                    brightness=self.current_brightness,
                    speed=self.current_speed,
                    power=True,
                )
            if target_idx in [-1, 2]:
                self._apply_ram_color(r, g, b)
        self.save_state()

    def set_speed(self, speed: int, target_idx: int = -1):
        """Sets animation speed (0 - 100%)."""
        self.current_speed = max(0, min(100, speed))
        self.set_mode(self.last_mode, target_idx, speed=self.current_speed)
        self.save_state()

    def set_power(self, power_on: bool, target_idx: int = -1):
        """Toggles power ON/OFF."""
        self.is_powered_on = power_on
        if not power_on:
            if target_idx in [-1, 1]:
                self.mystic_direct.apply(mode="Off", power=False)
            if target_idx in [-1, 2]:
                self._apply_ram_mode("Off")
        else:
            mode = self.last_mode if self.last_mode.lower() != "off" else "Static"
            r, g, b = self.last_color
            if target_idx in [-1, 1]:
                self.mystic_direct.apply(
                    mode=mode,
                    r=r, g=g, b=b,
                    brightness=self.current_brightness,
                    speed=self.current_speed,
                    power=True,
                )
            if target_idx in [-1, 2]:
                self._apply_ram_mode(mode)
                self._apply_ram_color(r, g, b)
        self.save_state()

    def _apply_ram_color(self, r: int, g: int, b: int):
        """Updates DRAM color via OpenRGB SDK with CLI fallback."""
        factor = self.current_brightness / 100.0
        ar = int(r * factor)
        ag = int(g * factor)
        ab = int(b * factor)
        hex_color = f"{ar:02X}{ag:02X}{ab:02X}"

        applied = False
        with self.lock:
            if self.client and RGBColor:
                color = RGBColor(ar, ag, ab)
                try:
                    for dev in self.client.devices:
                        if "dram" in dev.name.lower() or "ene" in dev.name.lower() or "memory" in dev.name.lower():
                            active_mode = dev.modes[dev.active_mode]
                            # If currently in a non-color mode (Off, Rainbow, Spectrum Cycle, etc.), switch to Static
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

    def _apply_ram_mode(self, mode_name: str, speed: Optional[int] = None):
        """Updates DRAM mode via OpenRGB SDK with CLI fallback."""
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

        factor = self.current_brightness / 100.0
        r, g, b = self.last_color
        ar = int(r * factor)
        ag = int(g * factor)
        ab = int(b * factor)
        hex_color = f"{ar:02X}{ag:02X}{ab:02X}"

        applied = False
        with self.lock:
            if self.client:
                try:
                    for dev in self.client.devices:
                        if "dram" in dev.name.lower() or "ene" in dev.name.lower() or "memory" in dev.name.lower():
                            matched = None
                            for m in dev.modes:
                                if m.name.lower() == target_mode.lower():
                                    matched = m
                                    break

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
        """Triggers pkexec to install udev rules if necessary."""
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
