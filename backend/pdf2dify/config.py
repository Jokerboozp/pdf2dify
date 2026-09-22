from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    project_root: Path
    data_dir: Path
    database_path: Path
    engine_root: Path
    engine_python: Path
    poll_seconds: float = 1.0

    @classmethod
    def load(cls) -> "Settings":
        project_root = Path(os.getenv("PDF2DIFY_ROOT", PROJECT_ROOT)).resolve()
        data_dir = Path(os.getenv("PDF2DIFY_DATA_DIR", project_root / "data")).resolve()
        default_engine = project_root / "engine" / "ops-pdf-rag"
        engine_root = Path(os.getenv("PDF2DIFY_ENGINE_ROOT", default_engine)).resolve()
        default_python = engine_root / ".venv" / "Scripts" / "python.exe"
        if os.name != "nt":
            default_python = engine_root / ".venv" / "bin" / "python"
        engine_python = Path(os.getenv("PDF2DIFY_ENGINE_PYTHON", default_python)).resolve()
        return cls(
            project_root=project_root,
            data_dir=data_dir,
            database_path=Path(os.getenv("PDF2DIFY_DATABASE", data_dir / "pdf2dify.db")).resolve(),
            engine_root=engine_root,
            engine_python=engine_python,
            poll_seconds=float(os.getenv("PDF2DIFY_WORKER_POLL_SECONDS", "1")),
        )

    def ensure(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "jobs").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "uploads").mkdir(parents=True, exist_ok=True)


class SecretStore:
    """Small local secret store. It is never exposed verbatim through the API."""

    def __init__(self, settings: Settings):
        self.path = settings.data_dir / "secrets.json"

    def read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return {str(k): str(v) for k, v in value.items() if v is not None}
        except (json.JSONDecodeError, OSError):
            return {}

    def update(self, values: dict[str, str | None]) -> None:
        current = self.read()
        for key, value in values.items():
            if value is not None and value != "":
                current[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.path)

    def public(self) -> dict[str, object]:
        values = self.read()
        return {
            "dify_base_url": values.get("DIFY_BASE_URL", ""),
            "dify_api_key_configured": bool(values.get("DIFY_DATASET_API_KEY")),
            "embedding_provider": values.get("DIFY_EMBEDDING_PROVIDER", "langgenius/ollama/ollama"),
            "embedding_model": values.get("DIFY_EMBEDDING_MODEL", "nomic-embed-text:latest"),
        }
