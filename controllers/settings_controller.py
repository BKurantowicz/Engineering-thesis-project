import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from contextlib import closing
from copy import deepcopy
from controllers.auth_controller import bind, require_access

class SettingsController:
    """Handles reading, validating, and saving the application configuration."""
    
    def __init__(self, config_path='config.json'):
        self.config_path = config_path
        bind(self)
        
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
                "database": "application.db",
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

    def _global_config(self):
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

    def get_config(self):
        config = deepcopy(self._global_config())
        from controllers import auth_controller as auth
        if auth.runtime and auth.runtime.unified and auth.runtime.shop_id is not None:
            from controllers.shop_controller import ShopController
            require_access(self)
            settings = ShopController(auth.runtime).settings(self._shop_id)
            for key in ('company','company_info','email_smtp'):
                config[key] = settings.get(key,{})
            config.setdefault('paths',{})['database'] = auth.runtime.path
        return config

    def save_config(self, new_config):
        """Saves the configuration dictionary to the JSON file."""
        new_config = deepcopy(new_config)
        from controllers import auth_controller as auth
        if auth.runtime and auth.runtime.unified:
            return self._save_shop_config(new_config,auth.runtime)
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(new_config, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False

    def _save_shop_config(self, new_config, auth):
        from controllers.shop_controller import ShopController
        require_access(self)
        old = self.get_config()
        keys = ('company','company_info','email_smtp')
        settings = {key:new_config.pop(key,{}) for key in keys}
        changed = any(old.get(k,{}) != settings[k] for k in keys)
        if changed:
            require_access(self,admin=True)
        new_config.setdefault('paths',{})['database'] = auth.path
        target = Path(self.config_path).resolve()
        previous = target.read_bytes() if target.exists() else None
        temporary = None
        published = False
        try:
            with NamedTemporaryFile(mode='w',encoding='utf-8',dir=target.parent,delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(new_config,stream,indent=4,ensure_ascii=False)
            ctrl = ShopController(auth)
            with closing(ctrl.connect()) as db, db:
                db.execute('BEGIN IMMEDIATE')
                require_access(self)
                ctrl._require(db,changed)
                if changed:
                    db.execute('UPDATE shop_settings SET configuration=? WHERE shop_id=?',
                               (json.dumps(settings,ensure_ascii=False),self._shop_id))
                os.replace(temporary,target)
                published = True
            return True
        except BaseException:
            if published:
                if previous is None:
                    target.unlink()
                else:
                    with NamedTemporaryFile(mode='wb',dir=target.parent,delete=False) as stream:
                        recovery = Path(stream.name)
                        stream.write(previous)
                    os.replace(recovery,target)
            raise
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
            
    def _merge_configs(self, default, current):
        """Recursively merges current config into default to prevent missing keys."""
        merged = default.copy()
        for key, value in current.items():
            if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
                merged[key] = self._merge_configs(merged[key], value)
            else:
                merged[key] = value
        return merged
