from functools import cached_property
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def find_project_root() -> Path:
    for candidate in [Path.cwd(), *Path.cwd().parents]:
        has_backend = (candidate / "backend" / "pyproject.toml").exists()
        has_frontend = (candidate / "frontend").exists()
        if has_backend and has_frontend:
            return candidate
    return Path(__file__).resolve().parents[3]


PROJECT_ROOT = find_project_root()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FINA_", extra="ignore")

    env: str = "development"
    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    duckdb_path: Path = Field(default=PROJECT_ROOT / "data" / "fina.duckdb")
    primary_provider: str = "akshare"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins_raw: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        validation_alias="FINA_CORS_ORIGINS",
    )
    factor_outlier_method: str = "mad"
    factor_outlier_mad_n: float = 5.0
    factor_standardize: bool = True
    factor_neutralize: bool = True
    factor_neutralize_method: str = "intra_group_rank"
    factor_min_cross_section_size: int = 10
    factor_evaluation_horizons: str = "1,5,10,20"
    data_stale_after_days: int = 3

    @cached_property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def clean_dir(self) -> Path:
        return self.data_dir / "clean"

    @property
    def qlib_dir(self) -> Path:
        return self.data_dir / "qlib"


settings = Settings()
