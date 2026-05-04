import os
import json
import base64
import shutil
from datetime import datetime, timezone
from pathlib import Path

import bcrypt
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

CONFIG_BASE = Path.home() / ".polymarket_bot"


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))


class UserConfig:
    def __init__(self, username: str):
        self.username = username
        self._config_dir = CONFIG_BASE / username
        self._config_path = self._config_dir / "config.json"

        self.password_hash: bytes = b""
        self.polymarket_api_key: str = ""
        self.polymarket_api_secret: str = ""
        self.polymarket_api_passphrase: str = ""
        self.polymarket_private_key: str = ""
        self.polymarket_funder_address: str = ""
        self.anthropic_api_key: str = ""
        self.binance_api_key: str = ""
        self.paper_balance: float = 200.0
        self.real_balance: float = 0.0
        self.created_at: str = ""

    def exists(self) -> bool:
        return self._config_path.exists()

    def validate_password(self, password: str) -> bool:
        return bcrypt.checkpw(password.encode(), self.password_hash)

    def save(self, password: str) -> None:
        self._config_dir.mkdir(parents=True, exist_ok=True)

        salt = os.urandom(16)
        key = _derive_key(password, salt)
        fernet = Fernet(key)

        sensitive = {
            "polymarket_api_key": self.polymarket_api_key,
            "polymarket_api_secret": self.polymarket_api_secret,
            "polymarket_api_passphrase": self.polymarket_api_passphrase,
            "polymarket_private_key": self.polymarket_private_key,
            "polymarket_funder_address": self.polymarket_funder_address,
            "anthropic_api_key": self.anthropic_api_key,
            "binance_api_key": self.binance_api_key,
        }
        encrypted = fernet.encrypt(json.dumps(sensitive).encode()).decode()

        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

        data = {
            "username": self.username,
            "password_hash": pw_hash.decode(),
            "salt": base64.b64encode(salt).decode(),
            "encrypted_keys": encrypted,
            "paper_balance": self.paper_balance,
            "real_balance": self.real_balance,
            "created_at": self.created_at or datetime.now(timezone.utc).isoformat(),
        }

        with open(self._config_path, "w") as fp:
            json.dump(data, fp, indent=2)

        self.password_hash = pw_hash
        self.created_at = data["created_at"]

    def load(self, password: str) -> bool:
        """Decrypt and load config. Returns True on success, False on bad password."""
        with open(self._config_path) as fp:
            data = json.load(fp)

        pw_hash = data["password_hash"].encode()
        if not bcrypt.checkpw(password.encode(), pw_hash):
            return False

        self.password_hash = pw_hash

        salt = base64.b64decode(data["salt"])
        key = _derive_key(password, salt)
        fernet = Fernet(key)

        sensitive = json.loads(fernet.decrypt(data["encrypted_keys"].encode()))
        self.polymarket_api_key        = sensitive.get("polymarket_api_key", "")
        self.polymarket_api_secret     = sensitive.get("polymarket_api_secret", "")
        self.polymarket_api_passphrase = sensitive.get("polymarket_api_passphrase", "")
        self.polymarket_private_key    = sensitive.get("polymarket_private_key", "")
        self.polymarket_funder_address = sensitive.get("polymarket_funder_address", "")
        self.anthropic_api_key         = sensitive.get("anthropic_api_key", "")
        self.binance_api_key           = sensitive.get("binance_api_key", "")
        self.paper_balance = data.get("paper_balance", 200.0)
        self.real_balance  = data.get("real_balance", 0.0)
        self.created_at    = data.get("created_at", "")

        return True

    def save_balances(self, paper: float = None, real: float = None) -> None:
        """Update balance fields in config without re-encrypting keys."""
        with open(self._config_path) as fp:
            data = json.load(fp)
        if paper is not None:
            data["paper_balance"] = round(paper, 4)
        if real is not None:
            data["real_balance"] = round(real, 4)
        with open(self._config_path, "w") as fp:
            json.dump(data, fp, indent=2)

    def delete(self) -> None:
        if self._config_dir.exists():
            shutil.rmtree(self._config_dir)
