import os
import sys
import json
import re
import importlib.util
import evdev
from threading import Thread, Event, Lock
from time import sleep
from typing import Optional, Callable

from foxblat.subscription import EventDispatcher
from foxblat.plugin_base import PluginPanel, PluginContext, PluginDeviceInfo


class PluginMatcher:
    """Device matching rules for a plugin."""
    def __init__(self, plugin_name: str, metadata: dict):
        self.plugin_name = plugin_name
        self.devices = metadata.get("devices", [])

    def matches(self, device: evdev.InputDevice) -> bool:
        """Check if an evdev device matches any of this plugin's rules."""
        for rule in self.devices:
            vid = rule.get("vendor_id")
            pid = rule.get("product_id")
            pattern = rule.get("name_pattern")

            # VID/PID matching
            if vid is not None and pid is not None:
                vid_int = int(vid, 16) if isinstance(vid, str) else vid
                pid_int = int(pid, 16) if isinstance(pid, str) else pid
                if device.info.vendor == vid_int and device.info.product == pid_int:
                    return True

            # Name pattern matching
            if pattern is not None:
                if re.search(pattern, device.name, re.IGNORECASE):
                    return True

        return False


class LoadedPlugin:
    """Represents a successfully loaded plugin."""
    def __init__(self, name: str, metadata: dict, module, panel_class: type,
                 matcher: PluginMatcher, path: str):
        self.name = name
        self.metadata = metadata
        self.module = module
        self.panel_class = panel_class
        self.matcher = matcher
        self.path = path
        self.panel_instance: Optional[PluginPanel] = None
        self.connected_devices: list[PluginDeviceInfo] = []


class PluginManager(EventDispatcher):
    """
    Manages plugin discovery, loading, device matching, and panel lifecycle.
    """

    def __init__(self, config_path: str, hid_handler, settings_handler):
        super().__init__()

        self._config_path = os.path.expanduser(config_path)
        self._plugins_path = os.path.join(self._config_path, "plugins")
        self._hid_handler = hid_handler
        self._settings_handler = settings_handler

        self._plugins: dict[str, LoadedPlugin] = {}
        self._plugins_lock = Lock()

        self._device_scan_thread: Optional[Thread] = None
        self._running = Event()
        self._button_callback: Optional[Callable] = None

        # Events for the main app to react to
        self._register_event("plugin-panel-available")    # (plugin_name, panel_instance)
        self._register_event("plugin-panel-unavailable")  # (plugin_name)
        self._register_event("plugin-load-error")         # (plugin_name, error_message)

    def start(self) -> None:
        """Start plugin discovery and device monitoring."""
        self._ensure_plugins_directory()
        self._discover_plugins()
        self._start_device_monitoring()

    def stop(self) -> None:
        """Stop device monitoring and cleanup plugins."""
        self._running.clear()

        with self._plugins_lock:
            for plugin in self._plugins.values():
                if plugin.panel_instance:
                    try:
                        plugin.panel_instance.shutdown()
                    except Exception as e:
                        print(f"[PluginManager] Error shutting down {plugin.name}: {e}")

    def _ensure_plugins_directory(self) -> None:
        """Create plugins directory if it doesn't exist."""
        if not os.path.exists(self._plugins_path):
            os.makedirs(self._plugins_path)

    def _discover_plugins(self) -> None:
        """Scan the plugins directory and load all valid plugins."""
        if not os.path.exists(self._plugins_path):
            return

        for entry in os.listdir(self._plugins_path):
            plugin_dir = os.path.join(self._plugins_path, entry)
            if os.path.isdir(plugin_dir):
                self._load_plugin(entry, plugin_dir)

    def _load_plugin(self, name: str, path: str) -> bool:
        """Load a single plugin from its directory."""
        metadata_file = os.path.join(path, "plugin.json")
        init_file = os.path.join(path, "__init__.py")

        # Validate required files exist
        if not os.path.isfile(metadata_file):
            self._dispatch("plugin-load-error", name, "Missing plugin.json")
            print(f"[PluginManager] Plugin '{name}': Missing plugin.json")
            return False

        if not os.path.isfile(init_file):
            self._dispatch("plugin-load-error", name, "Missing __init__.py")
            print(f"[PluginManager] Plugin '{name}': Missing __init__.py")
            return False

        # Load metadata
        try:
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)
        except json.JSONDecodeError as e:
            self._dispatch("plugin-load-error", name, f"Invalid plugin.json: {e}")
            print(f"[PluginManager] Plugin '{name}': Invalid plugin.json: {e}")
            return False

        # Validate required metadata fields
        required_fields = ["name", "panel_class", "devices"]
        for field in required_fields:
            if field not in metadata:
                self._dispatch("plugin-load-error", name, f"Missing required field: {field}")
                print(f"[PluginManager] Plugin '{name}': Missing field: {field}")
                return False

        # Load the plugin module
        try:
            module_name = f"foxblat_plugin_{name}"
            spec = importlib.util.spec_from_file_location(module_name, init_file,
                submodule_search_locations=[path])
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception as e:
            self._dispatch("plugin-load-error", name, f"Failed to load module: {e}")
            print(f"[PluginManager] Plugin '{name}': Failed to load module: {e}")
            return False

        # Get the panel class
        panel_class_name = metadata["panel_class"]
        if not hasattr(module, panel_class_name):
            self._dispatch("plugin-load-error", name, f"Panel class not found: {panel_class_name}")
            print(f"[PluginManager] Plugin '{name}': Panel class not found: {panel_class_name}")
            return False

        panel_class = getattr(module, panel_class_name)

        # Verify it's a subclass of PluginPanel
        if not issubclass(panel_class, PluginPanel):
            self._dispatch("plugin-load-error", name, "Panel class must extend PluginPanel")
            print(f"[PluginManager] Plugin '{name}': Panel class must extend PluginPanel")
            return False

        # Create matcher and store plugin
        matcher = PluginMatcher(name, metadata)

        with self._plugins_lock:
            self._plugins[name] = LoadedPlugin(
                name=name,
                metadata=metadata,
                module=module,
                panel_class=panel_class,
                matcher=matcher,
                path=path
            )

        print(f"[PluginManager] Loaded plugin: {metadata.get('name', name)}")
        return True

    def _start_device_monitoring(self) -> None:
        """Start background thread that monitors for device changes."""
        self._running.set()
        self._device_scan_thread = Thread(target=self._device_scan_loop, daemon=True)
        self._device_scan_thread.start()

    def _device_scan_loop(self) -> None:
        """Periodically scan for devices and match against plugins."""
        sleep(1)  # Initial delay to let other things initialize

        known_devices: set[str] = set()

        while self._running.is_set():
            current_devices: dict[str, evdev.InputDevice] = {}

            try:
                for path in evdev.list_devices():
                    try:
                        device = evdev.InputDevice(path)
                        current_devices[path] = device
                    except:
                        continue
            except Exception as e:
                print(f"[PluginManager] Error listing devices: {e}")
                sleep(3)
                continue

            current_paths = set(current_devices.keys())

            # Handle newly connected devices
            new_paths = current_paths - known_devices
            for path in new_paths:
                device = current_devices[path]
                self._handle_device_connected(device)

            # Handle disconnected devices
            removed_paths = known_devices - current_paths
            for path in removed_paths:
                self._handle_device_disconnected(path)

            known_devices = current_paths
            sleep(3)

    def _handle_device_connected(self, device: evdev.InputDevice) -> None:
        """Check if any plugin handles this device."""
        with self._plugins_lock:
            for plugin in self._plugins.values():
                if plugin.matcher.matches(device):
                    device_info = PluginDeviceInfo(
                        name=device.name,
                        vendor_id=device.info.vendor,
                        product_id=device.info.product,
                        path=device.path
                    )
                    plugin.connected_devices.append(device_info)

                    print(f"[PluginManager] Device matched plugin '{plugin.name}': {device.name}")

                    # Create panel instance if first device and we have a button callback
                    panel_just_created = False
                    if plugin.panel_instance is None and self._button_callback is not None:
                        self._instantiate_plugin_panel(plugin)
                        panel_just_created = True

                    # Notify the panel (skip if panel was just created, as _instantiate_plugin_panel already notified)
                    if plugin.panel_instance and not panel_just_created:
                        try:
                            plugin.panel_instance.on_device_connected(device_info)
                            plugin.panel_instance.active(1)
                        except Exception as e:
                            print(f"[PluginManager] Error notifying panel: {e}")

    def _handle_device_disconnected(self, path: str) -> None:
        """Notify plugins when a device disconnects."""
        with self._plugins_lock:
            for plugin in self._plugins.values():
                for device_info in plugin.connected_devices[:]:
                    if device_info.path == path:
                        plugin.connected_devices.remove(device_info)

                        print(f"[PluginManager] Device disconnected from plugin '{plugin.name}': {device_info.name}")

                        if plugin.panel_instance:
                            try:
                                plugin.panel_instance.on_device_disconnected(device_info)
                            except Exception as e:
                                print(f"[PluginManager] Error notifying panel: {e}")

                        # Hide panel if no devices left
                        if len(plugin.connected_devices) == 0 and plugin.panel_instance:
                            plugin.panel_instance.active(-1)

    def _instantiate_plugin_panel(self, plugin: LoadedPlugin) -> None:
        """Create a panel instance for a plugin."""
        try:
            context = PluginContext(
                hid_handler=self._hid_handler,
                settings_handler=self._settings_handler,
                plugin_path=plugin.path,
                config_path=self._config_path
            )

            title = plugin.metadata.get("panel_title", plugin.name)
            plugin.panel_instance = plugin.panel_class(
                title, self._button_callback, context
            )

            # Initialize panel as inactive (same as built-in panels in app.py)
            # This resets _active to False so active(1) will work properly
            plugin.panel_instance.active(-2)

            # Notify about existing connected devices
            for device_info in plugin.connected_devices:
                try:
                    plugin.panel_instance.on_device_connected(device_info)
                except Exception as e:
                    print(f"[PluginManager] Error notifying panel of device: {e}")

            if len(plugin.connected_devices) > 0:
                plugin.panel_instance.active(1)

            self._dispatch("plugin-panel-available", plugin.name, plugin.panel_instance)

        except Exception as e:
            self._dispatch("plugin-load-error", plugin.name, f"Failed to instantiate panel: {e}")
            print(f"[PluginManager] Error creating panel for {plugin.name}: {e}")

    def get_plugin_panels(self, button_callback: Callable) -> dict[str, PluginPanel]:
        """
        Get all plugin panels for plugins that have connected devices.
        Called by app.py to integrate panels into the UI.
        """
        self._button_callback = button_callback
        panels = {}

        with self._plugins_lock:
            for plugin in self._plugins.values():
                if len(plugin.connected_devices) > 0:
                    if plugin.panel_instance is None:
                        self._instantiate_plugin_panel(plugin)

                    if plugin.panel_instance:
                        title = plugin.metadata.get("panel_title", plugin.name)
                        panels[title] = plugin.panel_instance

        return panels

    def get_all_loaded_plugins(self) -> dict[str, LoadedPlugin]:
        """Get all loaded plugins (regardless of connected devices)."""
        with self._plugins_lock:
            return dict(self._plugins)

    def get_active_plugins(self) -> dict[str, PluginPanel]:
        """Get all plugins with connected devices (for preset UI)."""
        panels = {}
        with self._plugins_lock:
            for plugin in self._plugins.values():
                if plugin.panel_instance and len(plugin.connected_devices) > 0:
                    panels[plugin.panel_instance.preset_device_name] = plugin.panel_instance
        return panels

    def get_plugin_preset_settings(self, device_name: str) -> dict:
        """Get preset settings from a plugin by its preset device name."""
        with self._plugins_lock:
            for plugin in self._plugins.values():
                if plugin.panel_instance:
                    if plugin.panel_instance.preset_device_name == device_name:
                        try:
                            return plugin.panel_instance.get_preset_settings()
                        except Exception as e:
                            print(f"[PluginManager] Error getting preset settings from {device_name}: {e}")
        return {}

    def apply_plugin_preset_settings(self, device_name: str, settings: dict) -> None:
        """Apply preset settings to a plugin by its preset device name."""
        with self._plugins_lock:
            for plugin in self._plugins.values():
                if plugin.panel_instance:
                    if plugin.panel_instance.preset_device_name == device_name:
                        try:
                            plugin.panel_instance.on_preset_loaded(settings)
                            print(f"[PluginManager] Applied preset settings to {device_name}")
                        except Exception as e:
                            print(f"[PluginManager] Error applying preset settings to {device_name}: {e}")
                        return

            # No matching plugin found - log for debugging
            available = [p.panel_instance.preset_device_name for p in self._plugins.values() if p.panel_instance]
            print(f"[PluginManager] No plugin found for preset device '{device_name}'. Available: {available}")

    def has_active_plugins(self) -> bool:
        """Check if any plugins have connected devices."""
        with self._plugins_lock:
            return any(len(p.connected_devices) > 0 for p in self._plugins.values())
