from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_ingredient_selection_state_moves_between_disjoint_maps():
    script = (ROOT / "source/web/static/app.js").read_text(encoding="utf-8")
    assert "available:new Map()" in script
    assert "excluded:new Map()" in script
    assert "state.available.delete(id);state.excluded.set(id,name)" in script
    assert "state.excluded.delete(id);state.available.set(id,name)" in script
    assert "excluded_ids:[...state.excluded.keys()]" in script


def test_frontend_has_explicit_error_empty_loading_and_unicode_contracts():
    script = (ROOT / "source/web/static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "source/web/static/styles.css").read_text(encoding="utf-8")
    detail = (ROOT / "source/web/static/detail.js").read_text(encoding="utf-8")
    assert "showError(error.message)" in script
    assert "$('empty-state').classList.add('hidden')" in script
    assert "background: #fff" in css
    assert '"Segoe UI", "Noto Sans", Arial, sans-serif' in css
    assert "databaseSteps(instructions)" in detail
    assert "instruction-single" in detail
    assert "Các bước chế biến" in detail
