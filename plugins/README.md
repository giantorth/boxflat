# Foxblat Plugin System

Plugins extend Foxblat to support additional hardware devices. Each plugin provides a configuration panel that appears in the sidebar when a matching device is connected.

## Plugin Structure

```
~/.config/foxblat/plugins/
└── my-plugin/
    ├── plugin.json      # Required: Plugin metadata
    ├── __init__.py      # Required: Exports panel class
    └── panel.py         # Panel implementation
```

## plugin.json Schema

```json
{
    "name": "My Plugin",
    "version": "1.0.0",
    "author": "Your Name",
    "description": "Configuration panel for My Device",
    "panel_title": "My Device",
    "panel_class": "MyDevicePanel",
    "devices": [
        {"vendor_id": "0x1234", "product_id": "0x5678"},
        {"name_pattern": "My Device.*"}
    ]
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Display name for the plugin |
| `version` | No | Semantic version string |
| `author` | No | Plugin author |
| `description` | No | Human-readable description |
| `panel_title` | Yes | Title shown in sidebar button |
| `panel_class` | Yes | Python class name (must extend `PluginPanel`) |
| `devices` | Yes | Array of device matchers (VID/PID or name pattern) |

## PluginPanel Base Class

```python
from foxblat.plugin_base import PluginPanel, PluginContext, PluginDeviceInfo

class MyDevicePanel(PluginPanel):
    def __init__(self, title, button_callback, context):
        super().__init__(title, button_callback, context)

    def prepare_ui(self):
        """Required: Build the panel UI."""
        pass

    def on_device_connected(self, device: PluginDeviceInfo):
        """Optional: Called when device connects."""
        super().on_device_connected(device)

    def on_device_disconnected(self, device: PluginDeviceInfo):
        """Optional: Called when device disconnects."""
        super().on_device_disconnected(device)

    def shutdown(self):
        """Optional: Cleanup on app exit."""
        super().shutdown()
```

### Context Access

```python
self.context.hid_handler       # HID communication
self.context.settings_handler  # Persistent settings
self.context.plugin_path       # Path to plugin directory
self.context.config_path       # Path to ~/.config/foxblat
```

### Plugin Settings

```python
# Store persistent plugin-specific settings
self.set_plugin_setting("my-key", value)
value = self.get_plugin_setting("my-key")
```

## Panel Controls

Import widgets from `foxblat.widgets`:

```python
from foxblat.widgets import (
    FoxblatSliderRow, FoxblatSwitchRow, FoxblatButtonRow,
    FoxblatLabelRow, FoxblatComboRow, FoxblatToggleButtonRow,
    FoxblatColorPickerRow, FoxblatLevelRow, FoxblatCalibrationRow
)
```

### Layout Methods

```python
# Create a collapsible group
self.add_preferences_group("Group Title")

# Add rows to the current group
self._add_row(row)

# Show notification toast
self.show_toast("Message", timeout=2)
```

### Available Widgets

#### FoxblatSliderRow
Numeric slider with range and marks.
```python
slider = FoxblatSliderRow("Volume", range_start=0, range_end=100, value=50)
slider.subscribe(lambda val: print(f"Value: {val}"))
slider.set_value(75)
slider.get_value()  # Returns int
```

#### FoxblatSwitchRow
Boolean toggle switch.
```python
switch = FoxblatSwitchRow("Enable Feature")
switch.subscribe(lambda val: print(f"Enabled: {val}"))
switch.set_value(True)
switch.get_value()  # Returns bool
```

#### FoxblatButtonRow
Row with action buttons.
```python
# Single button with callback
btn_row = FoxblatButtonRow("Action", "Click Me")
btn_row.subscribe(my_callback)

# Multiple buttons
btn_row = FoxblatButtonRow("Actions")
btn1 = btn_row.add_button("Start", on_start)
btn2 = btn_row.add_button("Stop", on_stop)
btn1.set_label("Running...")  # Update button text
btn1.set_sensitive(False)     # Disable button
```

#### FoxblatLabelRow
Read-only status display.
```python
label = FoxblatLabelRow("Status")
label.set_label("Connected")
```

#### FoxblatComboRow
Dropdown selection.
```python
combo = FoxblatComboRow("Mode")
combo.add_entries("Option A", "Option B", "Option C")
combo.subscribe(lambda idx: print(f"Selected index: {idx}"))
combo.set_value(1)  # Select "Option B"
combo.get_value()   # Returns selected index
```

#### FoxblatToggleButtonRow
Mutually exclusive toggle buttons.
```python
toggle = FoxblatToggleButtonRow("Speed", ["Slow", "Medium", "Fast"])
toggle.subscribe(lambda idx: print(f"Selected: {idx}"))
toggle.set_value(1)  # Select "Medium"
```

#### FoxblatLevelRow
Visual progress/level bar.
```python
level = FoxblatLevelRow("Signal Strength")
level.set_value(0.75)  # 0.0 to 1.0
```

### Common Row Methods

All rows support:
```python
row.subscribe(callback)    # Register value change handler
row.set_value(value)       # Set the row's value
row.get_value()            # Get current value
row.set_active(bool)       # Enable/disable row
row.set_sensitive(bool)    # Control interactivity
row.set_visible(bool)      # Show/hide row
```

## Preset Integration

Enable preset save/load for your plugin:

```python
def get_preset_settings(self) -> dict:
    """Return current settings for preset save."""
    return {
        "setting-a": self._setting_a,
        "setting-b": self._setting_b,
    }

def on_preset_loaded(self, settings: dict) -> None:
    """Apply settings from loaded preset."""
    if "setting-a" in settings:
        self._setting_a = settings["setting-a"]
        self._setting_a_row.set_value(self._setting_a)
```

## Device Communication

For HID devices, find the hidraw path and send reports:

```python
def _send_report(self, data: bytes):
    padded = data.ljust(64, b'\x00')
    with open(self._hidraw_path, "wb") as f:
        f.write(padded)
```

## Threading

When updating UI from background threads, use `GLib.idle_add`:

```python
from gi.repository import GLib

def _background_work(self):
    # ... do work ...
    GLib.idle_add(self._label.set_label, "Done")
```

---

## Example Plugin

A minimal plugin demonstrating available controls:

**plugin.json**
```json
{
    "name": "Example Device",
    "version": "1.0.0",
    "panel_title": "Example",
    "panel_class": "ExamplePanel",
    "devices": [{"vendor_id": "0x1234", "product_id": "0x5678"}]
}
```

**__init__.py**
```python
from .panel import ExamplePanel
```

**panel.py**
```python
from foxblat.plugin_base import PluginPanel, PluginDeviceInfo
from foxblat.widgets import (
    FoxblatSliderRow, FoxblatSwitchRow, FoxblatButtonRow,
    FoxblatLabelRow, FoxblatComboRow
)
from gi.repository import GLib


class ExamplePanel(PluginPanel):
    def __init__(self, title, button_callback, context):
        self._brightness = 50
        self._enabled = False
        self._mode = 0
        super().__init__(title, button_callback, context)

    def prepare_ui(self):
        # Status group
        self.add_preferences_group("Status")
        self._status = FoxblatLabelRow("Device")
        self._add_row(self._status)
        self._status.set_label("Disconnected")

        # Settings group
        self.add_preferences_group("Settings")

        self._brightness_row = FoxblatSliderRow("Brightness", range_end=100)
        self._add_row(self._brightness_row)
        self._brightness_row.set_value(self._brightness)
        self._brightness_row.subscribe(self._on_brightness)

        self._enabled_row = FoxblatSwitchRow("Enable Output")
        self._add_row(self._enabled_row)
        self._enabled_row.set_value(self._enabled)
        self._enabled_row.subscribe(self._on_enabled)

        self._mode_row = FoxblatComboRow("Mode")
        self._mode_row.add_entries("Standard", "Performance", "Silent")
        self._add_row(self._mode_row)
        self._mode_row.set_value(self._mode)
        self._mode_row.subscribe(self._on_mode)

        # Actions group
        self.add_preferences_group("Actions")
        self._apply_row = FoxblatButtonRow("Apply", "Send to Device")
        self._add_row(self._apply_row)
        self._apply_row.subscribe(self._apply)

    def on_device_connected(self, device: PluginDeviceInfo):
        super().on_device_connected(device)
        GLib.idle_add(self._status.set_label, f"Connected: {device.name}")

    def on_device_disconnected(self, device: PluginDeviceInfo):
        super().on_device_disconnected(device)
        GLib.idle_add(self._status.set_label, "Disconnected")

    def _on_brightness(self, value):
        self._brightness = int(value)

    def _on_enabled(self, value):
        self._enabled = bool(value)

    def _on_mode(self, value):
        self._mode = int(value)

    def _apply(self, *args):
        # Send configuration to device
        self.show_toast("Settings applied", 2)

    # Preset support
    def get_preset_settings(self) -> dict:
        return {
            "brightness": self._brightness,
            "enabled": self._enabled,
            "mode": self._mode,
        }

    def on_preset_loaded(self, settings: dict) -> None:
        if "brightness" in settings:
            self._brightness = settings["brightness"]
            GLib.idle_add(self._brightness_row.set_value, self._brightness)
        if "enabled" in settings:
            self._enabled = settings["enabled"]
            GLib.idle_add(self._enabled_row.set_value, self._enabled)
        if "mode" in settings:
            self._mode = settings["mode"]
            GLib.idle_add(self._mode_row.set_value, self._mode)
```
