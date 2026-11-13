"""Private local image storage for user achievement posts."""
from __future__ import annotations

import os
from pathlib import Path

from source.web.recipe_images import RecipeImageError, safe_image_path, validate_image, write_image, delete_image


def storage_root() -> Path:
    configured = os.getenv("ACHIEVEMENT_IMAGE_STORAGE_DIR")
    root = Path(configured).expanduser().resolve() if configured else (Path(__file__).resolve().parents[2] / "statics/runtime/achievement-images").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


__all__ = ["RecipeImageError", "safe_image_path", "validate_image", "write_image", "delete_image", "storage_root"]
