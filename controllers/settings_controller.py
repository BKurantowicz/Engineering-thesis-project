import json
import os

class SettingsController:
    """Handles reading, validating, and saving the application configuration."""
    
    def __init__(self, config_path='config.json'):
        self.config_path = config_path
        
        # Safe default configuration in case the file is deleted or corrupted
        self.default_config = {
            "localization": {
                "language": "en",
                "currency": "USD",
                "date_format": "YYYY-MM-DD"
            },
            "appearance": {
                "theme": "dark",
                "font_size": "medium"
            },
            "paths": {
                "database": "warehouse.db",
                "default_export_dir": "Exports",
                "default_import_dir": "Imports",
                "database_backup_dir": "Backups",
                "templates_dir": "Templates"
            },
            "system": {
                "default_dashboard_filter": "7_days",
                "auto_backup_on_exit": False,
                "notifications": {
                    "show_toasts": True,
                    "play_sound": False
                }
            },
            "company": {
                "name": "",
                "nip": "",
                "address": "",
                "email": "",
                "phone": "",
                "smtp_key": ""
            }
        }

    def get_config(self):
        """Reads the config file or returns default if not found."""
        if not os.path.exists(self.config_path):
            return self.default_config
            
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Merge with defaults to guarantee all required keys exist
                return self._merge_configs(self.default_config, data)
        except Exception as e:
            print(f"Error reading config: {e}")
            return self.default_config

    def save_config(self, new_config):
        """Saves the configuration dictionary to the JSON file."""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(new_config, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False
            
    def _merge_configs(self, default, current):
        """Recursively merges current config into default to prevent missing keys."""
        merged = default.copy()
        for key, value in current.items():
            if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
                merged[key] = self._merge_configs(merged[key], value)
            else:
                merged[key] = value
        return merged