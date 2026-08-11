"""Frozen entry point for the Tauri desktop engine sidecar."""

from src.engine.server import main


if __name__ == "__main__":
    raise SystemExit(main())
