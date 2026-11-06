from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='DREVO_', env_file=ROOT / '.env', extra='ignore')
    archive_root: Path = Path.home() / 'Desktop' / 'Архив'
    data_dir: Path = ROOT / '.local'
    frontend_origin: str = 'http://127.0.0.1:5173'
    public_api_url: str = 'http://127.0.0.1:8000'
    session_hours: int = 8
    link_minutes: int = 30
    github_repo: str = ''
    github_token: str = ''
    github_branch: str = 'main'
    sync_seconds: int = 60
    export_living: bool = False
    max_image_pixels: int = 100_000_000
    max_zip_bytes: int = 100_000_000_000
    max_member_bytes: int = 200_000_000
    max_message_bytes: int = 262144
    max_cache_bytes: int = 2_000_000_000

    @property
    def db_path(self):
        return self.data_dir / 'drevo.sqlite3'

    def prepare(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for name in ('cache', 'backups', 'managed'):
            (self.data_dir / name).mkdir(exist_ok=True)
