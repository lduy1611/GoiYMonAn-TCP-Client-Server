"""Validation and private storage for Admin-managed recipe cover images."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import re
import uuid

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_WIDTH = MAX_HEIGHT = 8000
MAX_PIXELS = 20_000_000
FORMATS = {"JPEG": ("image/jpeg", "jpg"), "PNG": ("image/png", "png"), "WEBP": ("image/webp", "webp")}
KEY_PATTERN = re.compile(r"^[a-f0-9]{32}\.(?:jpg|png|webp)$")


class RecipeImageError(ValueError):
    pass


def validate_image(data: bytes, declared_type: str) -> tuple[bytes, dict[str, object]]:
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise RecipeImageError("Ảnh phải có dung lượng từ 1 byte đến 5 MB.")
    try:
        with Image.open(BytesIO(data)) as image:
            actual_format = image.format
            if actual_format not in FORMATS:
                raise RecipeImageError("Chỉ hỗ trợ ảnh JPG, PNG hoặc WebP.")
            media_type, extension = FORMATS[actual_format]
            if declared_type.split(";", 1)[0].strip().lower() != media_type:
                raise RecipeImageError("Định dạng ảnh thực tế không khớp với Content-Type.")
            width, height = image.size
            if width < 1 or height < 1 or width > MAX_WIDTH or height > MAX_HEIGHT or width * height > MAX_PIXELS:
                raise RecipeImageError("Kích thước ảnh vượt giới hạn 8000 × 8000 hoặc 20 megapixel.")
            image.verify()
        with Image.open(BytesIO(data)) as image:
            image.load()
            image = ImageOps.exif_transpose(image)
            width, height = image.size
            out = BytesIO()
            if actual_format == "JPEG":
                if image.mode not in ("RGB", "L"):
                    image = image.convert("RGB")
                image.save(out, format="JPEG", quality=88, optimize=True, progressive=True)
            elif actual_format == "PNG":
                image.save(out, format="PNG", optimize=True)
            else:
                image.save(out, format="WEBP", quality=86, method=4)
            normalized = out.getvalue()
        if not normalized or len(normalized) > MAX_UPLOAD_BYTES:
            raise RecipeImageError("Ảnh sau khi xử lý vượt giới hạn 5 MB.")
    except RecipeImageError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise RecipeImageError("Tệp không phải ảnh hợp lệ hoặc bị hỏng.") from exc
    return normalized, {"media_type": media_type, "extension": extension, "byte_size": len(normalized),
                        "width": width, "height": height, "sha256": sha256(normalized).hexdigest()}


def storage_root() -> Path:
    configured = os.getenv("RECIPE_IMAGE_STORAGE_DIR")
    if configured:
        root = Path(configured).expanduser().resolve()
    else:
        root = (Path(__file__).resolve().parents[2] / "statics" / "runtime" / "recipe-images").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_image_path(root: Path, key: str) -> Path:
    if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
        raise RecipeImageError("Invalid image storage key.")
    base = root.resolve()
    target = (base / key).resolve()
    if target.parent != base:
        raise RecipeImageError("Image path escaped its storage directory.")
    return target


def write_image(data: bytes, extension: str, root: Path | None = None) -> tuple[str, Path]:
    if extension not in {"jpg", "png", "webp"}:
        raise RecipeImageError("Unsupported image extension.")
    base = root or storage_root()
    base.mkdir(parents=True, exist_ok=True)
    key = f"{uuid.uuid4().hex}.{extension}"
    target = safe_image_path(base, key)
    temporary = base / f".{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return key, target


def delete_image(key: str | None, root: Path | None = None) -> bool:
    if not key:
        return False
    try:
        safe_image_path(root or storage_root(), key).unlink(missing_ok=True)
        return True
    except (OSError, RecipeImageError):
        return False
