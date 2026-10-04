import json

class Translator:
    """Handles multi-language translation loading and key resolution for the UI."""
    def __init__(self, lang_code="pl"):
        self.lang_code = lang_code
        self.translations = self.load_translations()

    def load_translations(self):
        """Loads translations from the translations.json file based on the active language."""
        try:
            with open("translations_main.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                # Returns dictionary for selected language, defaults to Polish if not found
                return data.get(self.lang_code, data.get("pl", {}))
        except FileNotFoundError:
            print("Warning: translations_main.json not found!")
            return {}

    def t(self, key, default=""):
        """Retrieves the translated text for a given key."""
        return self.translations.get(key, default or key)