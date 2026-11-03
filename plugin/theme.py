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
        "good": color(colors.get("green", colors.get("color2")), "#7fae7f"),
        "warning": color(colors.get("yellow", colors.get("color3")), "#c9a554"),
        "release": color(colors.get("magenta", colors.get("color5")), "#b48ead"),
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
        good, warning, urgent, release = values["good"], values["warning"], values["urgent"], values["release"]
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
            .settings-version {{ font-size: {max(9, round(size * .75))}px; }}
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
            button.flat:hover:not(:disabled), .popup-header button:hover:not(:disabled),
            headerbar button:hover:not(:disabled) {{
                background: alpha({fg}, {alpha("hover-cursor-fill-alpha", .08)});
            }}
            button:disabled {{ opacity: .4; }}
            check {{ border-radius: {radius}px; background: {bg}; border: 1px solid alpha({fg}, .4); }}
            check:checked {{ background: {accent}; color: {bg}; }}
            .toolbar {{ background: transparent; padding: 0; border-radius: 0; }}
            .message {{ background: transparent; padding: 10px 2px;
                        border-bottom: 1px solid alpha({fg}, .1); border-radius: 0; }}
            .popup-card scrolledwindow > overshoot,
            .popup-card scrolledwindow > undershoot {{
                background: transparent; background-image: none;
                border: none; box-shadow: none;
            }}
            .user-message {{ background: transparent; }}
            .card-role {{ color: {accent}; font-size: {max(1, size - 1)}px; opacity: 1; }}
            .composer {{ background: alpha({fg}, .025); border: 1px solid alpha({fg}, .3);
                         border-radius: {radius}px; padding: 8px; }}
            .composer-footer {{ padding: 0 9px; }}
            .queue-area {{ padding: 0 2px; }}
            .queue-row {{ border-bottom: 1px solid alpha({fg}, .1); }}
            .queue-area label {{ font-size: {max(1, size - 1)}px; }}
            button.queue-action {{ min-height: 24px; min-width: 24px; padding: 1px; }}
            .markdown-heading {{ font-size: {max(1, size + 1)}px; }}
            button.conversation-choice {{ padding: 8px 10px; border-color: alpha({accent}, .3); }}
            button.conversation-choice:hover:not(:disabled) {{ background: alpha({accent}, .12); }}
            button.conversation-choice:disabled {{ opacity: .75; }}
            .markdown-code {{ background: alpha({fg}, .04); padding: 8px; }}
            .markdown-quote {{ border-left: 2px solid alpha({accent}, .5); padding-left: 10px; }}
            .markdown-cell {{ padding: 7px; border-right: 1px solid alpha({fg}, .16);
                              border-bottom: 1px solid alpha({fg}, .16); }}
            .markdown-table {{ border-top: 1px solid alpha({fg}, .16); border-left: 1px solid alpha({fg}, .16); }}
            .markdown-table-header {{ background: alpha({fg}, .06); }}
            label link {{ color: {accent}; }}
            button.scroll-latest {{ background: {bg}; border-color: alpha({fg}, .25);
                                    border-radius: 50%; min-height: 24px; min-width: 24px; padding: 4px; }}
            textview, textview text {{ background: transparent; color: {fg}; }}
            textview text selection, entry selection {{ background: alpha({accent}, .35); }}
            .muted, .status {{ color: alpha({fg}, .65); opacity: 1; }}
            .panel {{ border: 1px solid alpha({fg}, .3); border-radius: {radius}px; padding: 14px; }}
            .view-tabs {{ padding: 6px 14px 0; border-bottom: 1px solid alpha({fg}, .12); }}
            .view-tabs button {{ background: transparent; border: none; border-radius: 0; box-shadow: none;
                                 border-bottom: 2px solid transparent; padding: 4px 2px; margin-right: 16px;
                                 color: alpha({fg}, .65); min-height: 24px; }}
            .view-tabs button:hover {{ color: {fg}; background: transparent; }}
            .view-tabs button:checked {{ color: {fg}; border-bottom-color: {accent}; background: transparent; }}
            .feature-row {{ border-bottom: 1px solid alpha({fg}, .08); padding: 12px 6px; }}
            .feature-row:hover, .feature-row.expanded {{ background: alpha({fg}, .03); }}
            .feature-row.unavailable {{ opacity: .55; }}
            .feature-title {{ font-weight: 600; }}
            .feature-subtitle {{ font-size: {max(1, size - 1)}px; color: alpha({fg}, .6); }}
            .feature-chevron {{ color: alpha({fg}, .45); margin-top: 2px; }}
            .feature-group-row {{ margin: 18px 6px 4px; }}
            .feature-group-icon {{ opacity: .8; }}
            .settings-error {{ color: {urgent}; }}
            .settings-heading {{ margin: 22px 2px 6px; }}
            .settings-heading.first {{ margin-top: 2px; }}
            .settings-group {{ border-top: 1px solid alpha({fg}, .12); }}
            .settings-item {{ padding: 12px 2px; border-bottom: 1px solid alpha({fg}, .08); }}
            .feature-row.release-affected {{ box-shadow: inset 2px 0 {release}; }}
            .release-label {{ color: {release}; font-size: {max(1, size - 1)}px; }}
            .features-notice.release-notice {{ border-left-color: {release}; background: alpha({release}, .08); }}
            .release-diff {{ font-family: monospace; font-size: {max(1, size - 2)}px; color: alpha({fg}, .75);
                             background: alpha({fg}, .04); padding: 6px 8px; }}
            .program-row {{ padding: 8px 6px; }}
            .program-install {{ color: alpha({good}, .85); }}
            .program-remove {{ color: alpha({urgent}, .85); }}
            .feature-group {{ font-size: {max(1, size - 2)}px; font-weight: 600; letter-spacing: 1px;
                              color: alpha({fg}, .55); }}
            .feature-count {{ font-size: {max(1, size - 2)}px; color: alpha({fg}, .4); }}
            .feature-section {{ font-size: {max(1, size - 2)}px; font-weight: 600; letter-spacing: 1px;
                                color: alpha({fg}, .5); margin-top: 6px; }}
            .feature-details {{ margin: 2px 0 2px 26px; padding-left: 12px; border-left: 2px solid alpha({accent}, .3); }}
            .feature-status {{ font-size: {max(1, size - 1)}px; color: alpha({fg}, .7); }}
            .status-dot {{ font-size: {max(1, size - 4)}px; }}
            .status-dot.status-applied {{ color: {good}; }}
            .status-dot.status-pending, .status-dot.status-staged {{ color: {warning}; }}
            .status-dot.status-modified {{ color: {urgent}; }}
            .status-dot.status-off, .status-dot.status-unavailable {{ color: alpha({fg}, .35); }}
            .feature-pill {{ font-size: {max(1, size - 2)}px; color: {accent}; background: alpha({accent}, .14);
                             padding: 1px 8px; border-radius: {max(radius, 4)}px; }}
            .features-notice {{ background: alpha({accent}, .07); border-left: 2px solid {accent}; padding: 4px 4px 4px 12px; }}
            button.link-action {{ color: {accent}; padding: 2px 8px; min-height: 22px; }}
            button.machine-button {{ padding: 4px 10px; }}
            button.inline-link {{ padding-left: 0; padding-right: 0; }}
            .feature-actions {{ margin-top: 4px; }}
            switch {{ background: alpha({fg}, .12); border: 1px solid alpha({fg}, .4);
                      border-radius: {radius}px; min-height: 20px; }}
            switch:checked {{ background: alpha({accent}, .35); border-color: {accent}; }}
            switch slider {{ background: alpha({fg}, .75); border-radius: {radius}px;
                             min-width: 18px; min-height: 18px; box-shadow: none; }}
            switch:checked slider {{ background: {accent}; }}
            switch:disabled {{ opacity: .4; }}
            radio {{ background: {bg}; border: 1px solid alpha({fg}, .4); }}
            radio:checked {{ background: {accent}; color: {bg}; border-color: {accent}; }}
            .features-banner {{ border-left: 2px solid {warning}; background: alpha({warning}, .06);
                                padding: 6px 6px 6px 12px; }}
            .pending-bar {{ border-top: 1px solid alpha({fg}, .16); padding-top: 8px; }}
            button.destructive {{ color: {urgent}; border-color: alpha({urgent}, .6); }}
            button.flat.destructive {{ border-color: transparent; }}
            button.destructive:hover:not(:disabled) {{ background: alpha({urgent}, .12); }}
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
