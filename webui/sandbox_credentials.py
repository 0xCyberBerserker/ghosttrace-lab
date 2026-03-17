import os
import secrets
import string
from dataclasses import dataclass
from pathlib import Path


DEFAULT_WINDOWS_SANDBOX_USERNAME = "Docker"
PASSWORD_ALPHABET = string.ascii_letters + string.digits


@dataclass
class SandboxCredentialsManager:
    credentials_path: Path
    default_username: str = DEFAULT_WINDOWS_SANDBOX_USERNAME

    def ensure_credentials(self):
        existing = self.load_credentials()
        username = existing.get("USERNAME") or self.default_username
        password = existing.get("PASSWORD") or self._generate_password()

        if existing.get("USERNAME") != username or existing.get("PASSWORD") != password:
            self.save_credentials(username, password)

        return {
            "username": username,
            "password": password,
            "path": str(self.credentials_path),
        }

    def load_credentials(self):
        if not self.credentials_path.exists():
            return {}

        values = {}
        try:
            for raw_line in self.credentials_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
        except OSError:
            return {}
        return values

    def save_credentials(self, username, password):
        self.credentials_path.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join([
            "# Auto-generated Windows sandbox credentials for the local lab.",
            f"USERNAME={username}",
            f"PASSWORD={password}",
            "",
        ])
        self.credentials_path.write_text(content, encoding="utf-8")
        try:
            os.chmod(self.credentials_path, 0o600)
        except OSError:
            pass

    def _generate_password(self, length=24):
        return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))
