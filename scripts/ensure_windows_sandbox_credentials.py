from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
WEBUI_DIR = ROOT / "webui"
if str(WEBUI_DIR) not in sys.path:
    sys.path.insert(0, str(WEBUI_DIR))

from sandbox_credentials import SandboxCredentialsManager  # noqa: E402


def main():
    credentials_path = ROOT / "sandbox" / "credentials" / "windows-sandbox.env"
    manager = SandboxCredentialsManager(credentials_path)
    payload = manager.ensure_credentials()
    print(f"Windows sandbox credentials ready at: {payload['path']}")
    print(f"Username: {payload['username']}")
    print(f"Password: {payload['password']}")


if __name__ == "__main__":
    main()
