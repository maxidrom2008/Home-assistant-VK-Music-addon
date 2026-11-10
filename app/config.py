"""Environment-backed application settings."""
from pathlib import Path
import os

class Settings:
    def __init__(self) -> None:
        self.data_dir = Path(os.getenv("VKMS_DATA_DIR", "/data"))
        self.host = os.getenv("VKMS_HOST", "0.0.0.0")
        self.port = int(os.getenv("VKMS_PORT", "8099"))
        self.database_path = self.data_dir / "vk_music.sqlite3"

settings = Settings()
