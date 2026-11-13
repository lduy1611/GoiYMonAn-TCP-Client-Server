"""Read-only filename/completeness check for the 15 B3 AI originals.

This does not decode, approve, convert, rename, or copy images, or edit a manifest.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re

EXPECTED_IDS = (1, 2, 3, 7, 8, 9, 10, 20, 21, 32, 38, 41, 45, 47, 48)
DEFAULT_INPUT_DIR = Path(__file__).resolve().parents[1] / "statics/runtime/b3-ai-originals"
NAME_PATTERN = re.compile(r"recipe-(\d{2})\.(png|jpg|jpeg|webp)", re.ASCII)


@dataclass
class InputCheck:
    files_by_id: dict[int, list[str]]
    invalid: list[str]

    @property
    def missing(self) -> list[int]:
        return [recipe_id for recipe_id in EXPECTED_IDS if recipe_id not in self.files_by_id]

    @property
    def duplicates(self) -> dict[int, list[str]]:
        return {recipe_id: names for recipe_id, names in self.files_by_id.items() if len(names) > 1}

    @property
    def ok(self) -> bool:
        return not (self.missing or self.duplicates or self.invalid)


def check_inputs(directory: Path) -> InputCheck:
    files_by_id: dict[int, list[str]] = {}
    invalid = []
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        match = NAME_PATTERN.fullmatch(path.name)
        if path.is_symlink() or not path.is_file() or not match:
            invalid.append(path.name)
            continue
        recipe_id = int(match.group(1))
        if recipe_id not in EXPECTED_IDS:
            invalid.append(path.name)
            continue
        files_by_id.setdefault(recipe_id, []).append(path.name)
    return InputCheck(files_by_id, invalid)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    args = parser.parse_args(argv)
    try:
        result = check_inputs(args.input_dir)
    except OSError as error:
        print(f"Cannot read input directory: {error}")
        return 2

    print(f"Input directory: {args.input_dir.resolve()}")
    print(f"Recipe IDs with named files: {len(result.files_by_id)}/{len(EXPECTED_IDS)}")
    for recipe_id in EXPECTED_IDS:
        names = result.files_by_id.get(recipe_id, [])
        print(f"  {recipe_id:02d}: {', '.join(names) if names else 'MISSING'}")
    for name in result.invalid:
        print(f"INVALID name or non-regular file: {name}")
    for recipe_id, names in result.duplicates.items():
        print(f"DUPLICATE recipe ID {recipe_id:02d}: {', '.join(names)}")
    print("Filename check PASSED. Image content still needs review." if result.ok
          else "Filename check NOT READY. No files or manifest were modified.")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
