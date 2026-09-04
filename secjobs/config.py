from pathlib import Path
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"

load_dotenv(ROOT / ".env")


def _load(name: str) -> dict:
    with open(CONFIG_DIR / name, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def candidate() -> dict:
    if not (CONFIG_DIR / "candidate.yaml").exists():
        raise SystemExit("config/candidate.yaml not found. Copy config/candidate.example.yaml "
                         "to config/candidate.yaml and fill in your details.")
    return _load("candidate.yaml")


def companies() -> list[str]:
    return _load("companies.yaml").get("companies", [])


def settings() -> dict:
    return _load("settings.yaml")


def master_resume() -> str:
    path = ROOT / candidate().get("resume_source", "data/resume.md")
    if not path.exists():
        raise SystemExit(
            f"Master resume not found at {path}. Copy data/resume.example.md to "
            f"data/resume.md and fill in your real experience."
        )
    return path.read_text(encoding="utf-8")
