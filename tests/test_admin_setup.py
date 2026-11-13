import pytest

from source.web import setup_admin


def writer_grants():
    return [
        "GRANT USAGE ON *.* TO `goiy_admin_writer`@`localhost`",
        "GRANT SELECT (`id`, `name`) ON `goiy_mon_an`.`ingredients` TO `goiy_admin_writer`@`localhost`",
        "GRANT SELECT, INSERT, UPDATE ON `goiy_mon_an`.`v2_admin_recipe_catalog_overrides` TO `goiy_admin_writer`@`localhost`",
        "GRANT SELECT ON `goiy_mon_an`.`v2_admin_legacy_ingredient_overrides` TO `goiy_admin_writer`@`localhost`",
        "GRANT SELECT ON `goiy_mon_an`.`v2_ingredient_admin_state` TO `goiy_admin_writer`@`localhost`",
        "GRANT SELECT ON `goiy_mon_an`.`v2_ingredients` TO `goiy_admin_writer`@`localhost`",
        "GRANT SELECT (id) ON `goiy_mon_an`.`v2_ingredients` TO `goiy_admin_writer`@`localhost`",
        "GRANT INSERT (id, canonical_name, normalized_name) ON `goiy_mon_an`.`v2_ingredients` TO `goiy_admin_writer`@`localhost`",
        "GRANT INSERT (legacy_ingredient_id) ON `goiy_mon_an`.`v2_ingredients` TO `goiy_admin_writer`@`localhost`",
        "GRANT SELECT (id), INSERT (id, origin_kind, author_ref) ON `goiy_mon_an`.`v2_recipes` TO `goiy_admin_writer`@`localhost`",
        "GRANT SELECT (id, status, content_review_id, servings_review_id), INSERT (id, recipe_id, revision_no, title, description, instructions, minutes), UPDATE (title, description, instructions, minutes) ON `goiy_mon_an`.`v2_recipe_revisions` TO `goiy_admin_writer`@`localhost`",
        "GRANT SELECT (revision_id) ON `goiy_mon_an`.`v2_release_recipes` TO `goiy_admin_writer`@`localhost`",
        "GRANT SELECT (revision_id, status, quantity_review_id, scaling_review_id), INSERT (revision_id, line_no, ingredient_id, quantity_raw, amount_kind, requirement, purpose, measurement_basis), DELETE ON `goiy_mon_an`.`v2_recipe_ingredient_lines` TO `goiy_admin_writer`@`localhost`",
    ]+setup_admin.REVIEW_GRANTS


def test_writer_grant_validator_accepts_only_required_v2_privileges():
    setup_admin.validate_writer_grants(writer_grants())


def test_writer_grant_validator_accepts_mysql_merged_column_privileges():
    merged = "GRANT UPDATE (content_complete, content_evidence_set_id, content_review_id, description, instructions, minutes, status, title) ON `goiy_mon_an`.`v2_recipe_revisions` TO `goiy_admin_writer`@`localhost`"
    setup_admin.validate_writer_grants(writer_grants() + [merged])


@pytest.mark.parametrize("extra",[
    "GRANT CREATE USER ON *.* TO `goiy_admin_writer`@`localhost`",
    "GRANT SELECT ON `goiy_mon_an`.* TO `goiy_admin_writer`@`localhost`",
    "GRANT UPDATE (status, legacy_flag) ON `goiy_mon_an`.`v2_recipe_revisions` TO `goiy_admin_writer`@`localhost`",
    "GRANT INSERT ON `goiy_mon_an`.`recipes` TO `goiy_admin_writer`@`localhost`",
])
def test_writer_grant_validator_rejects_unapproved_scope_or_columns(extra):
    with pytest.raises(RuntimeError):
        setup_admin.validate_writer_grants(writer_grants()+[extra])


def test_writer_grant_validator_rejects_missing_required_rights():
    with pytest.raises(RuntimeError,match="missing required"):
        setup_admin.validate_writer_grants(writer_grants()[:-1])


def test_draft_writer_uses_default_identity_status_without_extra_insert_privilege():
    grants=writer_grants()
    setup_admin.validate_writer_grants(grants,draft_only=True)
    assert not any("INSERT (identity_status)" in grant for grant in grants)


def test_draft_writer_requires_direct_recipe_catalog_privileges():
    grants=writer_grants()
    setup_admin.validate_writer_grants(grants,draft_only=True)
    catalog_grant=next(g for g in grants if "v2_admin_recipe_catalog_overrides" in g)
    with pytest.raises(RuntimeError,match="missing required"):
        setup_admin.validate_writer_grants(
            [g for g in grants if g != catalog_grant],draft_only=True)


def test_old_draft_only_writer_does_not_pass_review_write_preflight():
    with pytest.raises(RuntimeError,match="missing required"):
        setup_admin.validate_writer_grants(writer_grants()[:5])


def test_ingredient_admin_requires_only_v2_column_and_state_table_grants():
    grants=writer_grants()+setup_admin.INGREDIENT_ADMIN_GRANTS
    setup_admin.validate_writer_grants(grants,ingredient_admin=True)
    activation_grant=next(g for g in grants if "UPDATE (identity_status)" in g)
    with pytest.raises(RuntimeError,match="ingredient-admin"):
        setup_admin.validate_writer_grants([g for g in grants if g != activation_grant],ingredient_admin=True)
    with pytest.raises(RuntimeError,match="ingredient-admin"):
        setup_admin.validate_writer_grants(writer_grants(),ingredient_admin=True)
    with pytest.raises(RuntimeError,match="unapproved"):
        setup_admin.validate_writer_grants(grants+["GRANT DELETE ON `goiy_mon_an`.`v2_ingredients` TO `goiy_admin_writer`@`localhost`"],ingredient_admin=True)


def test_env_writer_escapes_values_and_replaces_duplicate_keys(tmp_path,monkeypatch):
    env=tmp_path/".env"
    env.write_text("KEEP=value\nADMIN_USERNAME=old\nADMIN_USERNAME=duplicate\n",encoding="utf-8")
    monkeypatch.setattr(setup_admin,"ROOT",tmp_path)
    monkeypatch.setattr(setup_admin,"ENV_FILE",env)
    setup_admin._write_env({"ADMIN_USERNAME":"test admin","MYSQL_DRAFT_WRITER_PASSWORD":"p#$'\\word"})
    from dotenv import dotenv_values
    values=dotenv_values(env,interpolate=False)
    assert values["KEEP"]=="value"
    assert values["ADMIN_USERNAME"]=="test admin"
    assert values["MYSQL_DRAFT_WRITER_PASSWORD"]=="p#$'\\word"
    assert env.read_text(encoding="utf-8").count("ADMIN_USERNAME=")==1
