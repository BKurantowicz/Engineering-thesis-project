import json
import os

class translator:
    """Handles multi-language translation loading for specific modules."""
    def __init__(self, lang_code="pl", file_name="translations_main.json"):
        self.lang_code = lang_code
        self.file_name = file_name
        self.translations = self.load_translations()

    def load_translations(self):
        """Loads translations from the specified JSON file."""
        try:
            with open(self.file_name, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get(self.lang_code, data.get("pl", {}))
        except FileNotFoundError:
            print(f"Warning: {self.file_name} not found!")
            return {}

    def t(self, key, default=""):
        """Retrieves the translated text for a given key."""
        return self.translations.get(key, default or key)