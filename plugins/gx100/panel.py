# GX-100 Shifter Plugin for Foxblat
# Based on GX-100.html Chrome WebHID configuration page

from foxblat.plugin_base import PluginPanel, PluginContext, PluginDeviceInfo
from foxblat.widgets import (
    FoxblatSliderRow, FoxblatLabelRow, FoxblatSwitchRow,
    FoxblatButtonRow
)
from gi.repository import GLib
import evdev
from threading import Thread, Event
import os


class GX100Panel(PluginPanel):
    def __init__(self, title, button_callback, context):
        # Settings (matching GX-100.html defaults)
        self._h_sensitivity = 80
        self._seq_sensitivity = 80
        self._combo_switch1 = True
        self._combo_switch2 = False
        self._pull_button = False
        self._sequential_mode = False

        # Calibration state
        self._h_calibrating = False
        self._seq_calibrating = False

        # Device state
        self._device: evdev.InputDevice = None
        self._hidraw_path: str = None
        self._read_thread: Thread = None
        self._running = Event()

        super().__init__(title, button_callback, context)

    def prepare_ui(self):
        # --- Status Section ---
        self.add_preferences_group("Status")
        self._status_row = FoxblatLabelRow("Device")
        self._add_row(self._status_row)
        self._status_row.set_label("Disconnected")

        # H-pattern gear indicator
        self._h_gear_row = FoxblatLabelRow("H-Pattern Gear")
        self._add_row(self._h_gear_row)
        self._h_gear_row.set_label("N")

        # Sequential shift indicator
        self._seq_gear_row = FoxblatLabelRow("Sequential Shift")
        self._add_row(self._seq_gear_row)
        self._seq_gear_row.set_label("-")

        # --- H-Pattern Settings ---
        self.add_preferences_group("H-Pattern Shifter")

        self._h_sens_row = FoxblatSliderRow("Sensitivity", range_end=255)
        self._add_row(self._h_sens_row)
        self._h_sens_row.set_value(self._h_sensitivity)
        self._h_sens_row.subscribe(self._on_h_sens_changed)

        self._h_cal_row = FoxblatButtonRow("Calibration")
        self._h_cal_btn = self._h_cal_row.add_button("Start", self._toggle_h_calibration)
        self._add_row(self._h_cal_row)

        # --- Sequential Settings ---
        self.add_preferences_group("Sequential Shifter")

        self._seq_sens_row = FoxblatSliderRow("Sensitivity", range_end=255)
        self._add_row(self._seq_sens_row)
        self._seq_sens_row.set_value(self._seq_sensitivity)
        self._seq_sens_row.subscribe(self._on_seq_sens_changed)

        self._seq_cal_row = FoxblatButtonRow("Calibration")
        self._seq_cal_btn = self._seq_cal_row.add_button("Start", self._toggle_seq_calibration)
        self._add_row(self._seq_cal_row)

        # --- Configuration ---
        self.add_preferences_group("Configuration")

        self._combo1_row = FoxblatSwitchRow("Combination Switch 1")
        self._add_row(self._combo1_row)
        self._combo1_row.set_value(self._combo_switch1)
        self._combo1_row.subscribe(self._on_combo1_changed)

        self._combo2_row = FoxblatSwitchRow("Combination Switch 2")
        self._add_row(self._combo2_row)
        self._combo2_row.set_value(self._combo_switch2)
        self._combo2_row.subscribe(self._on_combo2_changed)

        self._pull_row = FoxblatSwitchRow("Pull Button")
        self._add_row(self._pull_row)
        self._pull_row.set_value(self._pull_button)
        self._pull_row.subscribe(self._on_pull_changed)

        self._seq_mode_row = FoxblatSwitchRow("Sequential Mode")
        self._add_row(self._seq_mode_row)
        self._seq_mode_row.set_value(self._sequential_mode)
        self._seq_mode_row.subscribe(self._on_seq_mode_changed)

        # Apply button
        self._apply_row = FoxblatButtonRow("Apply Settings", "Apply")
        self._add_row(self._apply_row)
        self._apply_row.subscribe(self._apply_config)

    # --- Device Connection ---

    def on_device_connected(self, device: PluginDeviceInfo):
        super().on_device_connected(device)
        try:
            self._device = evdev.InputDevice(device.path)
            self._find_hidraw(device)
            GLib.idle_add(self._status_row.set_label, f"Connected: {device.name}")

            # Start input reading thread
            self._running.set()
            self._read_thread = Thread(target=self._read_input_loop, daemon=True)
            self._read_thread.start()
        except Exception as e:
            GLib.idle_add(self._status_row.set_label, f"Error: {e}")

    def on_device_disconnected(self, device: PluginDeviceInfo):
        super().on_device_disconnected(device)
        self._running.clear()
        if self._device:
            self._device = None
        self._hidraw_path = None
        GLib.idle_add(self._status_row.set_label, "Disconnected")
        GLib.idle_add(self._h_gear_row.set_label, "N")
        GLib.idle_add(self._seq_gear_row.set_label, "-")

    def _find_hidraw(self, device: PluginDeviceInfo):
        """Find the hidraw device path for HID output reports."""
        # Look for hidraw device with matching VID/PID
        try:
            for entry in os.listdir("/sys/class/hidraw"):
                hidraw_path = f"/dev/{entry}"
                device_path = f"/sys/class/hidraw/{entry}/device"

                # Check if this hidraw belongs to our device
                uevent_path = os.path.join(device_path, "uevent")
                if os.path.exists(uevent_path):
                    with open(uevent_path, "r") as f:
                        uevent = f.read()
                        # HID uevent uses 8-digit hex: HID_ID=0003:0000XXXX:0000YYYY
                        vid_pid = f"{device.vendor_id:08X}:{device.product_id:08X}"
                        if vid_pid in uevent:
                            self._hidraw_path = hidraw_path
                            print(f"[GX100] Found hidraw: {hidraw_path}")
                            return
        except Exception as e:
            print(f"[GX100] Error finding hidraw: {e}")

    def _read_input_loop(self):
        """Read evdev events and update gear display."""
        h_pattern_gears = {
            1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6",
            7: "7", 8: "8", 11: "R",
            12: "B1", 13: "B2", 14: "B3", 15: "B4", 16: "B5"
        }
        seq_gears = {9: "Down", 10: "Up"}

        while self._running.is_set() and self._device:
            try:
                for event in self._device.read_loop():
                    if not self._running.is_set():
                        break
                    if event.type == evdev.ecodes.EV_KEY:
                        btn = event.code - evdev.ecodes.BTN_TRIGGER + 1
                        if event.value == 1:
                            if btn in h_pattern_gears:
                                GLib.idle_add(self._h_gear_row.set_label, h_pattern_gears[btn])
                            elif btn in seq_gears:
                                GLib.idle_add(self._seq_gear_row.set_label, seq_gears[btn])
                        elif event.value == 0:
                            if btn in h_pattern_gears:
                                GLib.idle_add(self._h_gear_row.set_label, "N")
                            elif btn in seq_gears:
                                GLib.idle_add(self._seq_gear_row.set_label, "-")
            except Exception:
                break

    # --- HID Commands (based on GX-100.html protocol) ---

    def _send_report(self, data: bytes):
        """Send HID output report to device via hidraw."""
        if not self._hidraw_path:
            print("[GX100] No hidraw device available")
            return False

        try:
            # Pad to 64 bytes as expected by device
            padded = data.ljust(64, b'\x00')
            with open(self._hidraw_path, "wb") as f:
                f.write(padded)
            print(f"[GX100] Sent report: {data.hex()}")
            return True
        except PermissionError:
            self.show_toast("Permission denied. Check udev rules.", 3)
            print("[GX100] Permission denied writing to hidraw")
            return False
        except Exception as e:
            print(f"[GX100] Send error: {e}")
            return False

    def _toggle_h_calibration(self, *args):
        """Toggle H-pattern calibration mode."""
        # Report: [0x01, 0x01] to start, [0x01, 0x02] to finish
        data = bytes([0x01, 0x02 if self._h_calibrating else 0x01])

        if self._send_report(data):
            self._h_calibrating = not self._h_calibrating
            # Update UI after successful send
            self._h_cal_btn.set_label("Finish" if self._h_calibrating else "Start")
            # Disable seq calibration while H is active
            self._seq_cal_btn.set_sensitive(not self._h_calibrating)

    def _toggle_seq_calibration(self, *args):
        """Toggle sequential calibration mode."""
        # Report: [0x01, 0x03] to start, [0x01, 0x04] to finish
        data = bytes([0x01, 0x04 if self._seq_calibrating else 0x03])

        if self._send_report(data):
            self._seq_calibrating = not self._seq_calibrating
            # Update UI after successful send
            self._seq_cal_btn.set_label("Finish" if self._seq_calibrating else "Start")
            # Disable H calibration while seq is active
            self._h_cal_btn.set_sensitive(not self._seq_calibrating)

    def _apply_config(self, *args):
        """Send configuration to device."""
        # Report format: [0x02, cb1, cb2, seqMode, hAdj, 0, seqAdj, 0, pullBtn]
        data = bytes([
            0x02,
            0x01 if self._combo_switch1 else 0x00,
            0x01 if self._combo_switch2 else 0x00,
            0x01 if self._sequential_mode else 0x00,
            self._h_sensitivity & 0xFF,
            0x00,
            self._seq_sensitivity & 0xFF,
            0x00,
            0x01 if self._pull_button else 0x00,
        ])
        if self._send_report(data):
            self.show_toast("Configuration applied", 2)

    # --- Settings Callbacks ---

    def _on_h_sens_changed(self, value):
        self._h_sensitivity = int(value)

    def _on_seq_sens_changed(self, value):
        self._seq_sensitivity = int(value)

    def _on_combo1_changed(self, value):
        self._combo_switch1 = bool(value)

    def _on_combo2_changed(self, value):
        self._combo_switch2 = bool(value)

    def _on_pull_changed(self, value):
        self._pull_button = bool(value)

    def _on_seq_mode_changed(self, value):
        self._sequential_mode = bool(value)

    # --- Preset Integration ---

    def get_preset_settings(self) -> dict:
        """Return current settings for preset save."""
        return {
            "h-sensitivity": self._h_sensitivity,
            "seq-sensitivity": self._seq_sensitivity,
            "combo-switch1": self._combo_switch1,
            "combo-switch2": self._combo_switch2,
            "pull-button": self._pull_button,
            "sequential-mode": self._sequential_mode,
        }

    def on_preset_loaded(self, settings: dict) -> None:
        """Apply settings from loaded preset."""
        if "h-sensitivity" in settings:
            self._h_sensitivity = settings["h-sensitivity"]
            GLib.idle_add(self._h_sens_row.set_value, self._h_sensitivity)

        if "seq-sensitivity" in settings:
            self._seq_sensitivity = settings["seq-sensitivity"]
            GLib.idle_add(self._seq_sens_row.set_value, self._seq_sensitivity)

        if "combo-switch1" in settings:
            self._combo_switch1 = settings["combo-switch1"]
            GLib.idle_add(self._combo1_row.set_value, self._combo_switch1)

        if "combo-switch2" in settings:
            self._combo_switch2 = settings["combo-switch2"]
            GLib.idle_add(self._combo2_row.set_value, self._combo_switch2)

        if "pull-button" in settings:
            self._pull_button = settings["pull-button"]
            GLib.idle_add(self._pull_row.set_value, self._pull_button)

        if "sequential-mode" in settings:
            self._sequential_mode = settings["sequential-mode"]
            GLib.idle_add(self._seq_mode_row.set_value, self._sequential_mode)

        # Auto-apply to device after loading preset
        GLib.idle_add(self._apply_config)

    def shutdown(self):
        """Cleanup on panel/app shutdown."""
        self._running.clear()
        super().shutdown()
