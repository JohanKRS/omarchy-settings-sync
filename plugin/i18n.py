"""Small gettext-style catalog; the application's locale selects the language."""
import json
import os
from pathlib import Path


def language(environment=None):
    env = os.environ if environment is None else environment
    for key in ("AGENT_SETTINGS_LANGUAGE", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        if env.get(key):
            for candidate in env[key].split(":"):
                code = candidate.split(".", 1)[0].split("_", 1)[0].split("-", 1)[0].lower()
                if code in ("en", "pt", "es"):
                    return code
                if code in ("c", "posix"):
                    return "en"
            return "en"
    return "en"


LANGUAGE = language()
try:
    CATALOG = json.loads((Path(__file__).parent / "locales" / f"{LANGUAGE}.json").read_text())
except (OSError, ValueError):
    CATALOG = {}


def tr(message, **values):
    return CATALOG.get(message, message).format(**values) if values else CATALOG.get(message, message)
