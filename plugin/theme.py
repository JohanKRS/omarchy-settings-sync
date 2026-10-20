"""Read the same palette and typography used by Omarchy's shell."""
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib

from gi.repository import Gdk, Gtk, Pango


def toml(path):
    try:
        return tomllib.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def palette(directory=None):
    directory = Path(directory or Path.home() / ".local/state/omarchy/current/theme")
    colors = toml(directory / "colors.toml")
    shell = toml(directory / "shell.toml")
    def color(value, fallback):
        return value if isinstance(value, str) and re.fullmatch(r"#[a-fA-F0-9]{6}", value) else fallback
    surface = shell.get("popups", {})
    return {
        "background": color(surface.get("background"), color(colors.get("background"), "#101315")),
        "foreground": color(surface.get("text"), color(colors.get("foreground"), "#cacccc")),
        "accent": color(colors.get("accent", colors.get("color4")), "#cacccc"),
        "urgent": color(colors.get("red", colors.get("color1")), "#a55555"),
        "font": shell.get("font", {}),
        "controls": shell.get("controls", shell.get("style", {})),
        "spacing": shell.get("spacing", {}),
    }


class Theme:
    def __init__(self, window):
        self.window = window
        self.provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self.provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self.previous = None
        self.rounding = 0
        try:
            result = subprocess.run(["hyprctl", "-j", "getoption", "decoration:rounding"],
                                    capture_output=True, text=True, timeout=2)
            self.rounding = max(0, json.loads(result.stdout).get("int", 0))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        self.refresh()

    def refresh(self):
        values = palette()
        if values == self.previous:
            return True
        self.previous = values
        fg, bg, accent = values["foreground"], values["background"], values["accent"]
        fonts, controls = values["font"], values["controls"]
        size = max(1, int(fonts.get("body", fonts.get("base-size", 12))))
        title = max(1, int(fonts.get("title", round(size * 1.167))))
        family = os.environ.get("OMARCHY_MENU_FONT", "monospace").replace('"', "").replace("\\", "")
        radius = self.rounding
        def alpha(key, default):
            try:
                return min(1, max(0, float(controls.get(key, default))))
            except (ValueError, TypeError):
                return default
        self.provider.load_from_data(f"""
            @define-color theme_bg_color {bg};
            @define-color theme_fg_color {fg};
            @define-color accent_bg_color {accent};
            @define-color accent_fg_color {bg};
            window, popover > contents, .panel {{ background: {bg}; color: {fg}; }}
            window.popup-host {{ background: transparent; box-shadow: none; }}
            .popup-card {{ background: {bg}; color: {fg}; border: 2px solid {accent}; border-radius: {radius}px; }}
            .popup-header {{ padding: 16px 14px 2px; }}
            .popup-header button {{ background: transparent; border-color: transparent; }}
            * {{ font-family: "{family}"; font-size: {size}px; }}
            headerbar {{ background: {bg}; color: {fg}; min-height: 34px;
                         box-shadow: none; border-bottom: 1px solid alpha({fg}, .16); }}
            headerbar label, .title {{ font-size: {title}px; font-weight: 600; }}
            button, entry, dropdown > button {{ background: alpha({fg}, {alpha("normal-fill-alpha", .04)});
                color: {fg}; border: 1px solid alpha({fg}, {alpha("normal-border-alpha", .4)});
                border-radius: {radius}px; box-shadow: none; text-shadow: none; min-height: 24px; }}
            dropdown > button {{ padding: 5px 10px; min-height: 24px; }}
            .empty-title {{ font-weight: 600; font-size: {title}px; }}
            .status {{ font-size: {max(1, size - 1)}px; }}
            button:hover, dropdown > button:hover {{ background: alpha({fg}, {alpha("hover-cursor-fill-alpha", .08)}); }}
            dropdown popover > contents {{ border: 1px solid alpha({fg}, .4);
                border-radius: {radius}px; box-shadow: none; }}
            dropdown popover listview {{ background: {bg}; color: {fg}; }}
            dropdown popover row {{ background: transparent; color: {fg}; border-radius: {radius}px; }}
            dropdown popover row:hover {{ background: alpha({fg}, .08); }}
            dropdown popover row:selected {{ background: alpha({accent}, .16); color: {fg}; }}
            button:focus-visible, entry:focus-within {{ outline: 1px solid {accent}; outline-offset: -1px; }}
            button.suggested-action {{ color: {accent}; background: alpha({accent}, .10);
                                      border-color: alpha({accent}, .6); }}
            button.flat, headerbar button {{ border-color: transparent; background: transparent; }}
            button:disabled {{ opacity: .4; }}
            check {{ border-radius: {radius}px; background: {bg}; border: 1px solid alpha({fg}, .4); }}
            check:checked {{ background: {accent}; color: {bg}; }}
            .toolbar {{ background: transparent; padding: 0; border-radius: 0; }}
            .message {{ background: transparent; padding: 10px 2px;
                        border-bottom: 1px solid alpha({fg}, .1); border-radius: 0; }}
            .user-message {{ background: transparent; }}
            .card-role {{ color: {accent}; font-size: {max(1, size - 1)}px; opacity: 1; }}
            .composer {{ background: alpha({fg}, .025); border: 1px solid alpha({fg}, .3);
                         border-radius: {radius}px; padding: 8px; }}
            textview, textview text {{ background: transparent; color: {fg}; }}
            textview text selection, entry selection {{ background: alpha({accent}, .35); }}
            .muted, .status {{ color: alpha({fg}, .65); opacity: 1; }}
            .panel {{ border: 1px solid alpha({fg}, .3); border-radius: {radius}px; padding: 14px; }}
        """.encode())
        if self.window.vte:
            def rgba(value):
                result = Gdk.RGBA()
                result.parse(value)
                return result
            self.window.vte.set_colors(rgba(fg), rgba(bg), None)
            desc = Pango.FontDescription.from_string(family)
            desc.set_absolute_size(size * Pango.SCALE)
            self.window.vte.set_font(desc)
        return True
