import json
import os
import glob

class translator:
    def __init__(self, lang_code, translations_dir="utils"):
        self.lang_code = lang_code
        self.translations = {}
        self.load_all_translations(translations_dir)

    def load_all_translations(self, directory):
        """Ładuje i łączy wszystkie pliki translations_*.json w jeden słownik."""
        # Szuka wszystkich plików pasujących do wzorca w podanym folderze
        search_pattern = os.path.join(directory, "translations_*.json")
        
        for filepath in glob.glob(search_pattern):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Jeśli plik zawiera sekcję z naszym językiem (np. "pl"), zaktualizuj słownik
                    if self.lang_code in data:
                        self.translations.update(data[self.lang_code])
            except Exception as e:
                print(f"Błąd ładowania pliku tłumaczeń {filepath}: {e}")

    def t(self, key, fallback=""):
        """Zwraca tłumaczenie dla danego klucza lub awaryjną wartość tekstową."""
        return self.translations.get(key, fallback)