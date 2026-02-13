import psutil
from threading import Thread, Event
from time import sleep
from foxblat.subscription import EventDispatcher
from os import environ, path
import subprocess


class ProcessInfo:
    """Represents a running process with name and command line."""
    def __init__(self, name: str, cmdline: str):
        self.name = name
        self.cmdline = cmdline

    def __repr__(self):
        return f"ProcessInfo(name='{self.name}', cmdline='{self.cmdline}')"

    def __eq__(self, other):
        if isinstance(other, ProcessInfo):
            return self.name == other.name and self.cmdline == other.cmdline
        return False

    def __hash__(self):
        return hash((self.name, self.cmdline))


def list_processes(filter: str="") -> list[ProcessInfo]:
    """List running processes with their full command lines.

    Args:
        filter: Optional filter string to match against process name or command line

    Returns:
        List of ProcessInfo objects containing process name and full command line
    """
    if environ["FOXBLAT_FLATPAK_EDITION"] == "true":
        return _list_process_flatpak(filter)

    return _list_process_native(filter)


def _list_process_native(filter: str) -> list[ProcessInfo]:
    output = []
    seen = set()

    for p in psutil.process_iter(['name', 'cmdline']):
        try:
            name = p.name()
            cmdline_list = p.cmdline()
            cmdline = ' '.join(cmdline_list) if cmdline_list else name

            # Apply filter to both name and command line
            filter_lower = filter.lower()
            if filter_lower and filter_lower not in name.lower() and filter_lower not in cmdline.lower():
                continue

            # Deduplicate by (name, cmdline) tuple
            key = (name, cmdline)
            if key in seen:
                continue

            seen.add(key)
            output.append(ProcessInfo(name, cmdline))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            # Process may have terminated or we don't have permission
            continue

    return output


def _list_process_flatpak(filter: str) -> list[ProcessInfo]:
    output = []
    seen = set()

    try:
        # Get full command lines
        command_lines = _flatpak_ps_command()

        for cmdline in command_lines:
            if len(cmdline.strip()) < 3:
                continue

            # Extract process name from command line (first part)
            name = path.basename(cmdline.split()[0]) if cmdline.strip() else ""
            if not name:
                continue

            # Apply filter to both name and command line
            filter_lower = filter.lower()
            if filter_lower and filter_lower not in name.lower() and filter_lower not in cmdline.lower():
                continue

            # Deduplicate by (name, cmdline) tuple
            key = (name, cmdline)
            if key in seen:
                continue

            seen.add(key)
            output.append(ProcessInfo(name, cmdline))
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fallback to comm-only if command fails
        for name in _flatpak_ps_comm():
            if len(name) < 3:
                continue

            name = path.basename(name)
            if filter.lower() in name.lower():
                key = (name, name)
                if key not in seen:
                    seen.add(key)
                    output.append(ProcessInfo(name, name))

    return output


def _flatpak_ps_comm() -> list[str]:
    processes = subprocess.check_output(["flatpak-spawn", "--host", "ps", "-wwu", psutil.Process().username(), "-o", "comm="])
    return processes.decode().split()


def _flatpak_ps_command() -> list[str]:
    """Get full command lines from ps."""
    processes = subprocess.check_output(["flatpak-spawn", "--host", "ps", "-wwu", psutil.Process().username(), "-o", "command="])
    return [line.strip() for line in processes.decode().replace("\\", "/").split("\n") if line.strip()]


class ProcessObserver(EventDispatcher):
    def __init__(self) -> None:
        super().__init__()
        self._shutdown = Event()
        self._current_process = "empty"
        self._current_vehicle = ""
        self._vehicle_preset_active = False  # Track if a vehicle-specific preset is currently loaded
        self._simapi = None
        self._vehicle_presets = {}  # Maps "process|vehicle" -> True
        self._process_only_presets = set()  # Process patterns that have process-only presets
        self._register_event("no-games")
        Thread(target=self._process_observer_worker, daemon=True).start()


    def set_simapi_handler(self, simapi_handler) -> None:
        """Set the SimAPI handler for vehicle tracking."""
        self._simapi = simapi_handler
        if simapi_handler:
            simapi_handler.subscribe("car-name", self._on_vehicle_change)


    def _on_vehicle_change(self, vehicle_name: str) -> None:
        """Handle vehicle change from SimAPI telemetry."""
        if vehicle_name == self._current_vehicle:
            return

        self._current_vehicle = vehicle_name

        if self._current_process == "empty":
            return  # No game running, ignore vehicle changes

        # Try to find a process+vehicle combo preset
        combo_key = f"{self._current_process}|{vehicle_name}"
        if combo_key in self._vehicle_presets:
            print(f"Vehicle preset matched: {combo_key}")
            self._vehicle_preset_active = True
            self._dispatch(combo_key)
        elif self._vehicle_preset_active and self._current_process in self._process_only_presets:
            # Vehicle changed from one with a preset to one without - load process-only fallback
            print(f"No vehicle preset for '{vehicle_name}', falling back to process preset")
            self._vehicle_preset_active = False
            self._dispatch(self._current_process)


    def register_vehicle_preset(self, process_pattern: str, vehicle_name: str) -> None:
        """Register a process+vehicle combination preset."""
        if not process_pattern or not vehicle_name:
            return

        combo_key = f"{process_pattern}|{vehicle_name}"
        self._vehicle_presets[combo_key] = True
        self._register_event(combo_key)
        #print(f"Registered vehicle preset: {combo_key}")


    def register_process_only_preset(self, process_pattern: str) -> None:
        """Mark a process pattern as having a process-only (fallback) preset."""
        if process_pattern:
            self._process_only_presets.add(process_pattern)


    def get_current_vehicle(self) -> str:
        """Get the current vehicle name from telemetry."""
        return self._current_vehicle

    def has_active_process(self) -> bool:
        """Check if a process preset is currently active."""
        return self._current_process != "empty"


    def _matches_pattern(self, pattern: str, process_info: ProcessInfo) -> bool:
        """Check if a process matches the given pattern.

        The pattern can be:
        - A simple process name (e.g., "ac_client")
        - A command-line substring (e.g., "EADesktop.exe --game-id=F1")

        Args:
            pattern: The pattern to match (from preset's linked-process field)
            process_info: ProcessInfo object with name and cmdline

        Returns:
            True if the process matches the pattern
        """
        if not pattern:
            return False

        pattern_lower = pattern.lower()

        # First try exact name match (backward compatibility)
        if process_info.name.lower() == pattern_lower:
            return True

        # Then try substring match in command line
        if pattern_lower in process_info.cmdline.lower():
            return True

        return False


    def _process_observer_worker(self) -> None:
        while not self._shutdown.is_set():
            sleep(5)
            process_list = list_processes()

            for pattern in self.list_events():
                if pattern == "no-games":
                    continue

                # Check if any running process matches this pattern
                matched = False
                for process_info in process_list:
                    if self._matches_pattern(pattern, process_info):
                        matched = True
                        # Only dispatch if this is a new match
                        if pattern != self._current_process:
                            print(f"Process pattern \"{pattern}\" matched: {process_info.name}")
                            print(f"  Command line: {process_info.cmdline}")
                            self._current_process = pattern
                            self._dispatch(pattern)
                        break

            # If no patterns matched and we had an active process, dispatch no-games
            if self._current_process != "empty":
                still_active = False
                for pattern in self.list_events():
                    if pattern == "no-games":
                        continue
                    if pattern == self._current_process:
                        # Check if this pattern still matches
                        for process_info in process_list:
                            if self._matches_pattern(pattern, process_info):
                                still_active = True
                                break
                        break

                if not still_active:
                    print(f"Process pattern \"{self._current_process}\" no longer active")
                    self._current_process = "empty"
                    self._current_vehicle = ""  # Clear vehicle state when game exits
                    self._vehicle_preset_active = False
                    self._dispatch("no-games")


    def register_process(self, process_pattern: str) -> None:
        """Register a process pattern to watch for.

        Args:
            process_pattern: Can be a simple process name or a command-line pattern
        """
        if len(process_pattern) < 1:
            return

        # print(f"Registering process pattern: {process_pattern}")
        self._register_event(process_pattern)


    def deregister_process(self, process_pattern: str) -> None:
        self._deregister_event(process_pattern)


    def deregister_all_processes(self) -> None:
        for name in self.list_events():
            if name == "no-games":
                continue
            self._deregister_event(name)
        self._vehicle_presets.clear()
        self._process_only_presets.clear()
        self._vehicle_preset_active = False
