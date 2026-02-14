# Copyright (c) 2025, Tomasz Pakuła Using Arch BTW

from .settings_panel import SettingsPanel
from .h_pattern import HPatternSettings
from .stalks import StalksSettings
from foxblat.connection_manager import MozaConnectionManager
from foxblat.widgets import *
from foxblat.preset_handler import MozaPresetHandler
from foxblat.pithouse_converter import PithouseConverter
from foxblat.settings_handler import SettingsHandler
import os
from threading import Thread
from time import sleep

from gi.repository import Gtk, Gio, GLib
from gi.repository.Gio import Notification, NotificationPriority

class PresetSettings(SettingsPanel):
    def __init__(self, button_callback, connection_manager: MozaConnectionManager, settings: SettingsHandler,
                 hpattern: HPatternSettings, stalks: StalksSettings, simapi_handler=None, plugin_manager=None):
        self._settings = settings
        self._simapi = simapi_handler
        self._plugin_manager = plugin_manager

        self._hpattern = hpattern
        self._stalks = stalks

        self._includes = {}
        self._plugin_includes = {}  # Separate dict for plugin includes
        self._name_row = Adw.EntryRow()
        self._name_row.set_title("Preset Name")

        self._save_row = None
        self._presets_path = os.path.join(self._settings.get_path(), "presets")
        self._presets_list_group = None
        self._presets = []
        self._default_preset = None
        self._include_expander = None  # Store expander for adding plugin switches
        super().__init__("Presets", button_callback, connection_manager)
        self.list_presets()

        # Subscribe to plugin panel availability for dynamic switch addition
        if self._plugin_manager:
            self._plugin_manager.subscribe("plugin-panel-available", self._on_plugin_available)

        if self._settings.read_setting("default-preset-on-startup"):
            Thread(target=self._load_default, args=[5], daemon=True).start()


    def prepare_ui(self):
        self.add_preferences_group("Saving")
        self._current_group.set_description("Doesn't overwrite unavailable devices")
        self._add_row(self._name_row)

        expander = Adw.ExpanderRow(title="Include Devices")
        self._include_expander = expander
        self._add_row(expander)

        row = FoxblatSwitchRow("Base")
        expander.add_row(row)
        row.set_value(1)
        row.set_value(self._settings.read_setting("presets-include-base"))
        row.subscribe(self._settings.write_setting, "presets-include-base")
        self._cm.subscribe_connected("base-limit", row.set_active, 1, True)
        self._includes["base"] = row.get_value

        row = FoxblatSwitchRow("Dash")
        expander.add_row(row)
        row.set_value(1)
        row.set_value(self._settings.read_setting("presets-include-dash"))
        row.subscribe(self._settings.write_setting, "presets-include-dash")
        self._cm.subscribe_connected("dash-rpm-indicator-mode", row.set_active, 1, True)
        self._includes["dash"] = row.get_value

        row = FoxblatSwitchRow("Dash Colors")
        expander.add_row(row)
        row.set_value(1)
        row.set_value(self._settings.read_setting("presets-include-dash-color"))
        row.subscribe(self._settings.write_setting, "presets-include-dash-color")
        self._cm.subscribe_connected("dash-rpm-indicator-mode", row.set_active, 1, True)
        self._includes["dash-colors"] = row.get_value

        row = FoxblatSwitchRow("Wheel")
        expander.add_row(row)
        row.set_value(1)
        row.set_value(self._settings.read_setting("presets-include-wheel"))
        row.subscribe(self._settings.write_setting, "presets-include-wheel")
        self._cm.subscribe_connected("wheel-telemetry-mode", row.set_active, 1, True)
        self._includes["wheel"] = row.get_value

        row = FoxblatSwitchRow("Wheel Colors")
        expander.add_row(row)
        row.set_value(0)
        row.set_value(self._settings.read_setting("presets-include-wheel-colors"))
        row.subscribe(self._settings.write_setting, "presets-include-wheel-colors")
        self._cm.subscribe_connected("wheel-telemetry-mode", row.set_active, 1, True)
        self._includes["wheel-colors"] = row.get_value

        row = FoxblatSwitchRow("Pedals")
        expander.add_row(row)
        row.set_value(1)
        row.set_value(self._settings.read_setting("presets-include-pedals"))
        row.subscribe(self._settings.write_setting, "presets-include-pedals")
        self._cm.subscribe_connected("pedals-throttle-dir", row.set_active, 1, True)
        self._includes["pedals"] = row.get_value

        row = FoxblatSwitchRow("H-Pattern Shifter")
        expander.add_row(row)
        row.set_value(0)
        row.set_active(0)
        row.set_value(self._settings.read_setting("presets-include-hpattern"))
        row.subscribe(self._settings.write_setting, "presets-include-hpattern")
        self._hpattern.subscribe("active", row.set_active, 0, True)
        self._hpattern.subscribe("active", row.set_present)
        self._includes["hpattern"] = row.get_value

        row = FoxblatSwitchRow("Sequential Shifter")
        expander.add_row(row)
        row.set_value(1)
        row.set_value(self._settings.read_setting("presets-include-sequential"))
        row.subscribe(self._settings.write_setting, "presets-include-sequential")
        self._cm.subscribe_connected("sequential-output-y", row.set_active, 1, True)
        self._includes["sequential"] = row.get_value

        row = FoxblatSwitchRow("Handbrake")
        expander.add_row(row)
        row.set_value(1)
        row.set_value(self._settings.read_setting("presets-include-handbrake"))
        row.subscribe(self._settings.write_setting, "presets-include-handbrake")
        self._cm.subscribe_connected("handbrake-direction", row.set_active, 1, True)
        self._includes["handbrake"] = row.get_value

        row = FoxblatSwitchRow("Multifunction Stalks")
        expander.add_row(row)
        row.set_value(0)
        row.set_active(0)
        row.set_value(self._settings.read_setting("presets-include-stalks"))
        row.subscribe(self._settings.write_setting, "presets-include-stalks")
        self._stalks.subscribe("active", row.set_active, 0, True)
        self._stalks.subscribe("active", row.set_present)
        self._includes["stalks"] = row.get_value

        # Add plugin device switches dynamically
        self._add_plugin_switches()

        self._observer = process_handler.ProcessObserver()
        self._observer.set_simapi_handler(self._simapi)
        self._observer.subscribe("no-games", self._load_default)

        if Adw.get_minor_version() >= 6:
            self._save_row = Adw.ButtonRow(title="Save")
            self._save_row.add_css_class("suggested-action")
            self._save_row.set_end_icon_name("document-save-symbolic")
            self._add_row(self._save_row)
            self._save_row.connect("activated", self._save_preset)
            self._save_row.connect("activated", lambda v: expander.set_expanded(False))
            self._name_row.connect("notify::text-length", lambda e, *args: self._save_row.set_sensitive(e.get_text_length()))
            self._save_row.set_sensitive(False)

            # Import Pithouse preset button
            self._import_row = Adw.ButtonRow(title="Import Pithouse Preset")
            self._import_row.set_end_icon_name("document-open-symbolic")
            self._add_row(self._import_row)
            self._import_row.connect("activated", self._import_pithouse_preset)

        # compatibility with libadwaita older than 1.6
        else:
            self._save_row = FoxblatButtonRow("Save preset", "Save")
            self._add_row(self._save_row)
            self._current_row.subscribe(self._save_preset)
            self._current_row.subscribe(lambda v: expander.set_expanded(False))
            self._current_row.set_active(False)
            self._name_row.connect("notify::text-length", lambda e, *args: self._save_row.set_active(e.get_text_length()))

            # Import Pithouse preset button for older libadwaita
            self._import_row = FoxblatButtonRow("Import Pithouse preset", "Import")
            self._add_row(self._import_row)
            self._current_row.subscribe(self._import_pithouse_preset)



    def _save_preset(self, *rest):
        self.show_toast(f"Saving preset \"{self._name_row.get_text()}\"", 1.5)
        self._save_row.set_sensitive(False)

        pm = MozaPresetHandler(self._cm)
        pm.set_path(self._presets_path)
        pm.set_name(self._name_row.get_text())

        pm.subscribe(self.list_presets)
        pm.subscribe(self._activate_save)

        for key, method in self._includes.items():
            if method():
                pm.add_device_settings(key)

        pm.set_hpattern_settings(self._hpattern.get_settings())
        pm.set_stalks_settings(self._stalks.get_settings())

        # Collect plugin settings to save
        plugin_settings = {}
        if self._plugin_manager:
            for device_name, get_value in self._plugin_includes.items():
                if get_value():
                    settings = self._plugin_manager.get_plugin_preset_settings(device_name)
                    if settings:
                        plugin_settings[device_name] = settings

        pm.set_plugin_settings(plugin_settings)
        pm.save_preset()


    def _activate_save(self, *rest):
        GLib.idle_add(self._save_row.set_sensitive, True)


    def _add_plugin_switches(self) -> None:
        """Add include switches for active plugin devices."""
        if not self._plugin_manager:
            return

        for device_name, panel in self._plugin_manager.get_active_plugins().items():
            self._add_single_plugin_switch(device_name, panel)

    def _add_single_plugin_switch(self, device_name: str, panel) -> None:
        """Add a single plugin switch to the include expander."""
        if device_name in self._plugin_includes:
            return  # Already added

        row = FoxblatSwitchRow(panel.title)
        self._include_expander.add_row(row)
        row.set_value(0)
        setting_key = f"presets-include-plugin-{device_name}"
        saved_value = self._settings.read_setting(setting_key)
        if saved_value is not None:
            row.set_value(saved_value)
        row.subscribe(self._settings.write_setting, setting_key)
        panel.subscribe("active", row.set_active, 0, True)
        panel.subscribe("active", row.set_present)
        self._plugin_includes[device_name] = row.get_value

    def _on_plugin_available(self, plugin_name: str, panel) -> None:
        """Called when a plugin's matching device is connected (from background thread)."""
        device_name = panel.preset_device_name
        GLib.idle_add(self._add_single_plugin_switch, device_name, panel)


    def _load_preset(self, preset_name: str, automatic=False, default=False):
        preset_name = preset_name.removesuffix(".yml")
        print(f"Loading preset \"{preset_name}\"")
        GLib.idle_add(self._name_row.set_text, preset_name)
        pm = MozaPresetHandler(self._cm)
        pm.set_path(self._presets_path)
        pm.set_name(preset_name)
        pm.load_preset(self._hpattern, self._stalks)

        # Load plugin settings from preset
        if self._plugin_manager:
            plugin_settings = pm.get_plugin_settings()
            for device_name, settings in plugin_settings.items():
                print(f"[PRESETS] Applying settings for '{device_name}': {settings}")
                self._plugin_manager.apply_plugin_preset_settings(device_name, settings)

        if not automatic and not default:
            return

        notif = Notification()
        app = self._application

        # Format the process name nicely for notification
        if automatic:
            linked_process = pm.get_linked_process()
            # Extract just the executable name from command line for display
            process_display = linked_process.split()[0] if ' ' in linked_process else linked_process
            # Further simplify if it's a path
            import os
            process_display = os.path.basename(process_display)
            notif.set_title(f"Game detected: {process_display}")
        else:
            notif.set_title("No games detected")

        notif.set_body(f"Loading {"default" if default else ""} preset: {preset_name}")
        notif.set_priority(NotificationPriority.NORMAL)

        app.send_notification("preset", notif)
        sleep(10)
        app.withdraw_notification("preset")


    def _delete_preset(self, preset_name: str, *args):
        filepath = os.path.join(self._presets_path, preset_name)

        if not os.path.isfile(filepath):
            filepath += ".yml"

        if not os.path.isfile(filepath):
            return

        os.remove(filepath)
        self.list_presets()


    def list_presets(self, *rest):
        self.remove_preferences_group(self._presets_list_group)

        if not os.path.exists(self._presets_path):
            return

        files = os.listdir(self._presets_path)
        files.sort()

        self.add_preferences_group("Preset list")
        self._presets_list_group = self._current_group

        pm = MozaPresetHandler(None)
        pm.set_path(self._presets_path)
        self._observer.deregister_all_processes()
        self._default_preset = None

        for file in files:
            filepath = os.path.join(self._presets_path, file)
            if not os.path.isfile(filepath):
                continue

            preset_name = file.removesuffix(".yml")
            row = FoxblatButtonRow(preset_name)
            row.add_button("Load", self._load_preset, file)
            row.add_button("Settings", self._show_preset_dialog, file)
            # row.add_button("Delete", self._delete_preset, file).add_css_class("destructive-action")
            self._add_row(row)

            pm.set_name(file)
            process = pm.get_linked_process()
            vehicle = pm.get_linked_vehicle()

            if process and vehicle:
                # Process+vehicle combo preset - higher priority
                self._observer.register_process(process)
                self._observer.register_vehicle_preset(process, vehicle)
                combo_key = f"{process}|{vehicle}"
                self._observer.subscribe(combo_key, self._load_preset, preset_name, True)
            elif process:
                # Process-only preset - fallback
                self._observer.register_process(process)
                self._observer.register_process_only_preset(process)
                self._observer.subscribe(process, self._load_preset, preset_name, True)

            if pm.is_default():
                print(f"Found default preset: {preset_name}")
                self._default_preset = preset_name
                self._presets_list_group.set_description(f"Default: {preset_name}")


    def _handle_preset_save(self, file_name: str):
        if not os.path.exists(self._presets_path):
            return

        files = os.listdir(self._presets_path)
        pm = MozaPresetHandler(None)
        pm.set_path(self._presets_path)
        pm.set_name(file_name)

        if not pm.is_default():
            self.list_presets()
            return

        for file in files:
            if file_name in file:
                continue

            filepath = os.path.join(self._presets_path, file)
            if not os.path.isfile(filepath):
                continue

            pm.set_name(file)
            pm.set_default(False)

        self.list_presets()


    def _show_preset_dialog(self, file_name: str):
        if not file_name:
            return

        if file_name == "":
            return

        dialog = FoxblatPresetDialog(self._presets_path, file_name, self._simapi)
        dialog.subscribe("save", self._handle_preset_save)
        dialog.subscribe("delete", self._delete_preset)
        dialog.present(self._content)


    def _load_default(self, delay: int=0) -> None:
        if not self._default_preset:
            print("No default preset to load")
            return

        if delay > 0:
            sleep(delay)
            # After delay, check if a process preset was already loaded
            if self._observer.has_active_process():
                print("Skipping default preset - process preset already active")
                return

        print(f"Loading default preset: {self._default_preset}")
        self._load_preset(self._default_preset, default=True)


    def update_preset_name(self, preset_name: str) -> None:
        """Update the preset name in the UI (called when loaded via IPC)."""
        print(f"[PRESETS] update_preset_name called with: {preset_name}")
        preset_name = preset_name.removesuffix(".yml")
        GLib.idle_add(self._name_row.set_text, preset_name)


    def _import_pithouse_preset(self, *args):
        """Open file dialog to import a Moza Pithouse preset."""
        dialog = Gtk.FileDialog()
        dialog.set_title("Import Pithouse Preset")

        # Set up JSON filter
        json_filter = Gtk.FileFilter()
        json_filter.set_name("JSON files")
        json_filter.add_mime_type("application/json")
        json_filter.add_pattern("*.json")

        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(json_filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(json_filter)

        dialog.open(self._content.get_root(), None, self._on_pithouse_file_selected)


    def _on_pithouse_file_selected(self, dialog: Gtk.FileDialog, result):
        """Handle file selection for Pithouse import."""
        try:
            file = dialog.open_finish(result)
            if file is None:
                return
            filepath = file.get_path()
        except GLib.Error:
            # User cancelled the dialog
            return

        Thread(target=self._convert_and_save_pithouse, args=[filepath], daemon=True).start()


    def _convert_and_save_pithouse(self, filepath: str):
        """Convert Pithouse preset and save it (runs in background thread)."""
        converter = PithouseConverter()
        converted, preset_name, error = converter.load_and_convert(filepath)

        if error:
            GLib.idle_add(self.show_toast, f"Import failed: {error}", 3)
            return

        # Save the converted preset
        pm = MozaPresetHandler(None)
        pm.set_path(self._presets_path)
        pm.set_name(preset_name)
        pm.save_imported_preset(converted)

        GLib.idle_add(self.show_toast, f"Imported preset: {preset_name}", 2)
        GLib.idle_add(self.list_presets)

        # Load the preset to apply settings to device
        GLib.idle_add(self._load_preset, preset_name)
