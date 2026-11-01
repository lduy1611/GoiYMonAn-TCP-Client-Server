import pytest

from scripts.check_b3_image_inputs import EXPECTED_IDS, check_inputs, main


def test_complete_filename_set_accepts_supported_extensions_without_changing_files(tmp_path):
    # Deliberately empty fixtures: this checker only validates filenames, not image content.
    extensions = ("png", "jpg", "jpeg", "webp")
    for index, recipe_id in enumerate(EXPECTED_IDS):
        (tmp_path / f"recipe-{recipe_id:02d}.{extensions[index % 4]}").touch()
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert check_inputs(tmp_path).ok
    assert main(["--input-dir", str(tmp_path)]) == 0
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_empty_directory_reports_all_missing_ids(tmp_path):
    result = check_inputs(tmp_path)
    assert result.missing == list(EXPECTED_IDS)
    assert not result.ok
    assert main(["--input-dir", str(tmp_path)]) == 1


def test_multiple_extensions_for_one_recipe_are_duplicates(tmp_path):
    for name in ("recipe-01.png", "recipe-01.jpg"):
        (tmp_path / name).touch()
    result = check_inputs(tmp_path)
    assert result.duplicates == {1: ["recipe-01.jpg", "recipe-01.png"]}
    assert not result.ok


@pytest.mark.parametrize("name", [
    "recipe-1.png", "recipe-04.png", "recipe-01-320.webp", "recipe-01.PNG",
    "Recipe-01.png", "recipe-01.png.exe", "recipe-01 (1).png", "recipe-01.svg",
])
def test_invalid_or_out_of_scope_name_is_rejected(tmp_path, name):
    (tmp_path / name).touch()
    assert check_inputs(tmp_path).invalid == [name]


def test_directory_with_an_image_filename_is_rejected(tmp_path):
    (tmp_path / "recipe-01.png").mkdir()
    assert check_inputs(tmp_path).invalid == ["recipe-01.png"]


def test_missing_directory_returns_error_without_creating_it(tmp_path):
    missing = tmp_path / "not-created"
    assert main(["--input-dir", str(missing)]) == 2
    assert not missing.exists()
