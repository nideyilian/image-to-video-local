"""Headless application boundary shared by desktop frontends."""

from .config import (
    IMAGE_SELECTION_MODES,
    SUBFOLDER_SELECTION_MODE,
    build_default_config,
    normalize_config,
    scan_images,
    scan_subfolders,
    validate_config,
    validate_config_detailed,
)
from .runner import JobManager

__all__ = [
    "IMAGE_SELECTION_MODES",
    "SUBFOLDER_SELECTION_MODE",
    "JobManager",
    "build_default_config",
    "normalize_config",
    "scan_images",
    "scan_subfolders",
    "validate_config",
    "validate_config_detailed",
]
