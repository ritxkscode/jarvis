"""Encrypted secrets management using age encryption."""

import os
import json
import subprocess
from pathlib import Path
from typing import Optional
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

from .settings import get_settings
from loguru import logger


class SecretsManager:
    """Manages encrypted secrets storage using age or Fernet fallback."""

    def __init__(self, secrets_path: Optional[Path] = None, password: Optional[str] = None):
        self.settings = get_settings()
        self.secrets_path = secrets_path or (self.settings.data_dir / "secrets.age")
        self._password = password or os.environ.get("JARVIS_SECRETS_PASSWORD")
        self._fernet: Optional[Fernet] = None
        self._cache: dict[str, str] = {}
        self._loaded = False

    def _get_fernet(self) -> Fernet:
        """Get or create Fernet cipher from password."""
        if self._fernet is not None:
            return self._fernet

        if not self._password:
            raise ValueError(
                "No password provided. Set JARVIS_SECRETS_PASSWORD env var "
                "or call set_password() first."
            )

        # Derive key from password
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"jarvis-salt-v1",  # In production, use random salt per file
            iterations=100_000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(self._password.encode()))
        self._fernet = Fernet(key)
        return self._fernet

    def set_password(self, password: str) -> None:
        """Set the encryption password."""
        self._password = password
        self._fernet = None  # Reset cipher

    def _encrypt_age(self, plaintext: str) -> bytes:
        """Encrypt using age (preferred)."""
        try:
            # Use age CLI if available
            result = subprocess.run(
                ["age", "-p", "-a"],
                input=plaintext.encode(),
                capture_output=True,
                check=True,
                text=False,
            )
            return result.stdout
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Fallback to Fernet
            return self._get_fernet().encrypt(plaintext.encode())

    def _decrypt_age(self, ciphertext: bytes) -> str:
        """Decrypt using age or Fernet."""
        # Try age first
        try:
            result = subprocess.run(
                ["age", "-d", "-p"],
                input=ciphertext,
                capture_output=True,
                check=True,
                text=False,
            )
            return result.stdout.decode()
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Fallback to Fernet
            return self._get_fernet().decrypt(ciphertext).decode()

    def load(self) -> None:
        """Load and decrypt secrets file."""
        if self._loaded:
            return

        if not self.secrets_path.exists():
            self._cache = {}
            self._loaded = True
            return

        try:
            ciphertext = self.secrets_path.read_bytes()
            plaintext = self._decrypt_age(ciphertext)
            self._cache = json.loads(plaintext)
            logger.debug(f"Loaded {len(self._cache)} secrets from {self.secrets_path}")
        except Exception as e:
            logger.error(f"Failed to load secrets: {e}")
            self._cache = {}

        self._loaded = True

    def save(self) -> None:
        """Encrypt and save secrets file."""
        if not self._loaded:
            self.load()

        plaintext = json.dumps(self._cache, indent=2)
        ciphertext = self._encrypt_age(plaintext)
        self.secrets_path.write_bytes(ciphertext)
        # Restrict permissions
        self.secrets_path.chmod(0o600)
        logger.debug(f"Saved {len(self._cache)} secrets to {self.secrets_path}")

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get a secret value."""
        self.load()
        return self._cache.get(key, default)

    def set(self, key: str, value: str) -> None:
        """Set a secret value."""
        self.load()
        self._cache[key] = value
        self.save()

    def delete(self, key: str) -> bool:
        """Delete a secret."""
        self.load()
        if key in self._cache:
            del self._cache[key]
            self.save()
            return True
        return False

    def list_keys(self) -> list[str]:
        """List all secret keys."""
        self.load()
        return list(self._cache.keys())

    def set_multiple(self, secrets: dict[str, str]) -> None:
        """Set multiple secrets at once."""
        self.load()
        self._cache.update(secrets)
        self.save()

    # Convenience methods for common secrets
    def get_github_token(self) -> Optional[str]:
        return self.get("github_token")

    def set_github_token(self, token: str) -> None:
        self.set("github_token", token)

    def get_gmail_credentials(self, email: str) -> Optional[dict]:
        """Get Gmail OAuth credentials for an account."""
        data = self.get(f"gmail_{email.replace('@', '_at_')}")
        if data:
            return json.loads(data)
        return None

    def set_gmail_credentials(self, email: str, credentials: dict) -> None:
        """Store Gmail OAuth credentials."""
        key = f"gmail_{email.replace('@', '_at_')}"
        self.set(key, json.dumps(credentials))

    def get_google_oauth(self) -> Optional[dict]:
        """Get Google Cloud OAuth client config."""
        data = self.get("google_oauth")
        if data:
            return json.loads(data)
        return None

    def set_google_oauth(self, client_id: str, client_secret: str, project_id: str) -> None:
        """Store Google Cloud OAuth config."""
        self.set("google_oauth", json.dumps({
            "client_id": client_id,
            "client_secret": client_secret,
            "project_id": project_id,
        }))

    def get_plaid_credentials(self) -> Optional[dict]:
        """Get Plaid API credentials."""
        data = self.get("plaid")
        if data:
            return json.loads(data)
        return None

    def set_plaid_credentials(self, client_id: str, secret: str, env: str = "sandbox") -> None:
        self.set("plaid", json.dumps({
            "client_id": client_id,
            "secret": secret,
            "env": env,
        }))


# Singleton
_secrets_manager: Optional[SecretsManager] = None


def get_secrets_manager() -> SecretsManager:
    """Get or create secrets manager singleton."""
    global _secrets_manager
    if _secrets_manager is None:
        _secrets_manager = SecretsManager()
    return _secrets_manager