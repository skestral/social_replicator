import os
from collections import OrderedDict

class SettingsManager:
    def __init__(self, env_path=".env"):
        self.env_path = env_path
        self._ensure_env_exists()

    def _ensure_env_exists(self):
        if not os.path.exists(self.env_path):
            with open(self.env_path, 'w') as f:
                f.write("")

    def get_all(self):
        """Reads .env file and returns a dictionary of key-value pairs."""
        settings = {}
        with open(self.env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    settings[key.strip()] = value.strip().strip("'").strip('"')
        return settings

    def get(self, key, default=None):
        return self.get_all().get(key, default)

    def get_bool(self, key, default=False):
        val = self.get(key)
        if val is None:
            return default
        return val.lower() in ('true', '1', 'yes', 'on')

    def get_int(self, key, default=None):
        val = self.get(key)
        if val is None:
            return default
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    def set(self, key, value):
        """Updates or adds a setting in the .env file, preserving comments and structure."""
        lines = []
        with open(self.env_path, 'r') as f:
            lines = f.readlines()

        key_found = False
        new_lines = []
        
        # Determine strict string representation for value
        if isinstance(value, bool):
            str_val = "True" if value else "False"
        else:
            str_val = str(value)

        for line in lines:
            if line.strip().startswith(f"{key}="):
                new_lines.append(f"{key}={str_val}\n")
                key_found = True
            else:
                new_lines.append(line)

        if not key_found:
            # If file doesn't end with newline, add one
            if new_lines and not new_lines[-1].endswith('\n'):
                new_lines[-1] += '\n'
            new_lines.append(f"{key}={str_val}\n")

        with open(self.env_path, 'w') as f:
            f.writelines(new_lines)

        # Update running process environment
        os.environ[key] = str_val

    def bulk_update(self, updates):
        """Updates multiple settings at once."""
        current_lines = []
        if os.path.exists(self.env_path):
             with open(self.env_path, 'r') as f:
                current_lines = f.readlines()
        
        # Create a map of existing keys to line numbers
        key_map = {}
        for i, line in enumerate(current_lines):
            stripped = line.strip()
            if stripped and not stripped.startswith('#') and '=' in stripped:
                k = stripped.split('=', 1)[0].strip()
                key_map[k] = i
        
        new_lines = list(current_lines)
        
        for key, value in updates.items():
            if isinstance(value, bool):
                val_str = "True" if value else "False"
            else:
                val_str = str(value)
                
            new_line = f"{key}={val_str}\n"
            os.environ[key] = val_str # Update running process environment
            
            if key in key_map:
                new_lines[key_map[key]] = new_line
            else:
                if new_lines and not new_lines[-1].endswith('\n'):
                    new_lines[-1] += '\n'
                new_lines.append(new_line)
                key_map[key] = len(new_lines) - 1

        with open(self.env_path, 'w') as f:
            f.writelines(new_lines)
