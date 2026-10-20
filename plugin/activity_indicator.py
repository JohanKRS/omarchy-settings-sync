"""An activity indicator that resumes after the panel is hidden and reopened."""
from gi.repository import Gtk


class ActivityIndicator(Gtk.Box):
    def __init__(self):
        super().__init__(visible=False, valign=Gtk.Align.CENTER)
        self.active = False
        self.indicator = None

    def set_spinning(self, active):
        self.active = bool(active)
        if self.indicator:
            if active:
                self.indicator.start()
            else:
                self.indicator.stop()
        self.set_visible(self.active)

    def get_spinning(self):
        return self.active

    def do_map(self):
        # GTK 4.24 pauses the SVG on unmap but can reuse it without playing it
        # on the next map. A fresh child gets a fresh animation/frame clock.
        self.indicator = Gtk.Spinner()
        self.indicator.set_size_request(16, 16)
        if self.active:
            self.indicator.start()
        self.append(self.indicator)
        Gtk.Box.do_map(self)

    def do_unmap(self):
        Gtk.Box.do_unmap(self)
        if self.indicator:
            self.remove(self.indicator)
            self.indicator = None
