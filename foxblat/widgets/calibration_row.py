# Copyright (c) 2025, Tomasz Pakuła Using Arch BTW

from gi.repository import Gtk, GLib
from .button_row import FoxblatButtonRow
from threading import Thread
from time import sleep
from foxblat.subscription import EventDispatcher

class FoxblatCalibrationRow(EventDispatcher, FoxblatButtonRow):
    def __init__(self, title: str, subtitle="", alternative=False):
        FoxblatButtonRow.__init__(self, title, button_label="Calibrate", subtitle=subtitle)
        EventDispatcher.__init__(self)

        self._alternative = alternative
        self._register_events("calibration-start", "calibration-stop")


    def _notify(self, *rest):
        Thread(daemon=True, target=self._calibration).start()


    def _calibration(self):
        GLib.idle_add(self.set_active, False)
        tmp = self.get_subtitle()
        text = "Calibration in progress..."
        # print("Calibration start")

        if self._alternative:
            GLib.idle_add(self.set_subtitle, "Press all paddles!")
            sleep(4)

        self._dispatch("calibration-start", 1)

        for i in reversed(range(3 if self._alternative else 7)):
            GLib.idle_add(self.set_subtitle, f"{text} {i+1}s")
            sleep(1)

        if self._alternative:
            GLib.idle_add(self.set_subtitle, "Release paddles")
            sleep(3)

        self._dispatch("calibration-stop", 0)
        # print("Calibration stop")

        GLib.idle_add(self.set_subtitle, tmp)
        GLib.idle_add(self.set_active, True)
