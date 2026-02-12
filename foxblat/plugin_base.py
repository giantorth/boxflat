from abc import abstractmethod
from foxblat.panels.settings_panel import SettingsPanel
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from foxblat.hid_handler import HidHandler
    from foxblat.settings_handler import SettingsHandler


class PluginContext:
    """
    Context object passed to plugins providing access to foxblat infrastructure.
    """
    def __init__(self, hid_handler: 'HidHandler', settings_handler: 'SettingsHandler',
                 plugin_path: str, config_path: str):
        self.hid_handler = hid_handler
        self.settings_handler = settings_handler
        self.plugin_path = plugin_path      # Path to the plugin's directory
        self.config_path = config_path      # Path to foxblat config (~/.config/foxblat)


class PluginDeviceInfo:
    """
    Information about a connected device that matched the plugin.
    """
    def __init__(self, name: str, vendor_id: int, product_id: int, path: str):
        self.name = name
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.path = path                    # evdev device path


class PluginPanel(SettingsPanel):
    """
    Base class for plugin panels. Extends SettingsPanel with plugin-specific features.

    Plugins must implement:
    - prepare_ui(): Build the panel UI using inherited widget methods

    Plugins may override:
    - on_device_connected(device: PluginDeviceInfo): Called when matching device connects
    - on_device_disconnected(device: PluginDeviceInfo): Called when device disconnects
    - shutdown(): Cleanup when panel/plugin is being unloaded

    Preset integration (optional):
    - get_preset_settings(): Return dict of current settings for preset save
    - on_preset_loaded(settings): Apply settings from loaded preset
    - preset_device_name: Property returning the device name used in preset YAML
    """

    def __init__(self, title: str, button_callback, context: PluginContext):
        self._context = context
        self._connected_devices: dict[str, PluginDeviceInfo] = {}

        # SettingsPanel expects connection_manager and hid_handler as optional args
        # For plugins, we pass None for connection_manager and provide hid_handler
        super().__init__(title, button_callback,
                        connection_manager=None,
                        hid_handler=context.hid_handler)

    @property
    def context(self) -> PluginContext:
        """Access to foxblat infrastructure."""
        return self._context

    @property
    def plugin_path(self) -> str:
        """Path to this plugin's directory."""
        return self._context.plugin_path

    @property
    def preset_device_name(self) -> str:
        """Device name used in preset YAML (defaults to panel title lowercase with dashes)."""
        return self.title.lower().replace(" ", "-")

    def get_plugin_setting(self, key: str):
        """Read a plugin-specific setting from persistent storage."""
        plugin_settings = self._context.settings_handler.read_setting("plugin-settings") or {}
        plugin_name = self.preset_device_name
        if plugin_name in plugin_settings:
            return plugin_settings[plugin_name].get(key)
        return None

    def set_plugin_setting(self, key: str, value):
        """Write a plugin-specific setting to persistent storage."""
        plugin_settings = self._context.settings_handler.read_setting("plugin-settings") or {}
        plugin_name = self.preset_device_name
        if plugin_name not in plugin_settings:
            plugin_settings[plugin_name] = {}
        plugin_settings[plugin_name][key] = value
        self._context.settings_handler.write_setting(plugin_settings, "plugin-settings")

    def on_device_connected(self, device: PluginDeviceInfo) -> None:
        """Called when a matching device is connected. Override in subclass."""
        self._connected_devices[device.path] = device

    def on_device_disconnected(self, device: PluginDeviceInfo) -> None:
        """Called when a matching device is disconnected. Override in subclass."""
        if device.path in self._connected_devices:
            del self._connected_devices[device.path]

    def get_preset_settings(self) -> dict:
        """
        Return current settings to save in preset.
        Called when user saves a preset with this plugin included.
        Returns dict like {"setting-name": value, ...}

        Override in subclass to enable preset support.
        """
        return {}

    def on_preset_loaded(self, settings: dict) -> None:
        """
        Apply settings from a loaded preset.
        Called when a preset containing this plugin's settings is loaded.
        settings is dict like {"setting-name": value, ...}

        Override in subclass to handle preset loading.
        """
        pass

    @abstractmethod
    def prepare_ui(self) -> None:
        """Build the panel UI. Must be implemented by plugins."""
        pass
