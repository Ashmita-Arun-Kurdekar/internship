"""Double-click launcher for the local dashboard; uses existing dependencies if needed."""
import importlib.util
import sys
from pathlib import Path

base = Path(__file__).resolve().parent
# This workspace has a dependency directory from the verified project setup.
# A normal pip/venv installation remains the preferred portable setup.
if importlib.util.find_spec("openpyxl") is None:
    local_dependencies = base.parent / "dependencies"
    if local_dependencies.is_dir():
        sys.path.insert(0, str(local_dependencies))
        import os
        os.environ["PYTHONPATH"] = str(local_dependencies) + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else "")

if __name__ == "__main__":
    from src.webapp import main
    sys.argv.append("--open-browser")
    main()
