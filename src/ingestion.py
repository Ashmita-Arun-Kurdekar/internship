"""Read source files without modifying them; isolate batch errors."""
import json
import logging
from pathlib import Path


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Source root must be an object")
    data = value.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("responseDetails"), list):
        raise ValueError("Expected data.responseDetails array")
    return value


def load_batch(folder: Path, config=None):
    sources, errors = [], []
    for path in sorted(folder.rglob("*.json")):
        logging.info("Processing %s", path.name)
        try:
            if config is None:
                source = load_json(path)
            else:
                from .adapters import adapt_source
                import json
                raw = json.loads(path.read_text(encoding="utf-8-sig"))
                if not isinstance(raw, dict):
                    raise ValueError("Source root must be an object")
                source = adapt_source(raw, path.relative_to(folder).as_posix(), config)
            sources.append((path, source))
        except (OSError, ValueError) as exc:
            errors.append({"file": path.relative_to(folder).as_posix(), "error": str(exc)})
            logging.error("Cannot process %s: %s", path.name, exc)
    return sources, errors
