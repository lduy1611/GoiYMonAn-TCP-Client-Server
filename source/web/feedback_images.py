from __future__ import annotations

import os
from pathlib import Path

from source.web.recipe_images import RecipeImageError, validate_image, write_image, delete_image, safe_image_path


def storage_root() -> Path:
    configured = os.getenv("FEEDBACK_IMAGE_STORAGE_DIR")
    root = Path(configured).expanduser().resolve() if configured else (Path(__file__).resolve().parents[2] / "statics/runtime/feedback-images").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


__all__ = ["RecipeImageError", "validate_image", "write_image", "delete_image", "safe_image_path", "storage_root"]
