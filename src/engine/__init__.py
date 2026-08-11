"""Headless application boundary shared by desktop frontends."""

from .config import build_default_config, normalize_config, scan_images, validate_config
from .runner import JobManager

__all__ = [
    "JobManager",
    "build_default_config",
    "normalize_config",
    "scan_images",
    "validate_config",
]
