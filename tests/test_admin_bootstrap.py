from source.database.bootstrap_admin_crud import _grants, _mysql_literal
from source.database.codex_mysql import validate_codex_grants
from source.web.setup_admin import REVIEW_GRANTS, validate_writer_grants


def test_bootstrap_grants_match_the_writer_allowlist():
    grants=["GRANT USAGE ON *.* TO `goiy_admin_writer`@`localhost`",*_grants()]
    validate_writer_grants(grants)


def test_mysql_sorted_column_grants_match_writer_allowlist():
    validate_writer_grants([
        "GRANT USAGE ON *.* TO `goiy_admin_writer`@`localhost`",
        "GRANT SELECT (`id`) ON `goiy_mon_an`.`v2_ingredients` TO `goiy_admin_writer`@`localhost`",
        "GRANT INSERT (`id`, `canonical_name`, `normalized_name`) ON `goiy_mon_an`.`v2_ingredients` TO `goiy_admin_writer`@`localhost`",
        "GRANT INSERT (`legacy_ingredient_id`) ON `goiy_mon_an`.`v2_ingredients` TO `goiy_admin_writer`@`localhost`",
        "GRANT SELECT (`quantity_review_id`, `revision_id`, `scaling_review_id`, `status`), INSERT (`amount_kind`, `ingredient_id`, `line_no`, `measurement_basis`, `purpose`, `quantity_raw`, `requirement`, `revision_id`), DELETE ON `goiy_mon_an`.`v2_recipe_ingredient_lines` TO `goiy_admin_writer`@`localhost`",
        "GRANT SELECT (`content_review_id`, `id`, `servings_review_id`, `status`), INSERT (`description`, `id`, `instructions`, `minutes`, `recipe_id`, `revision_no`, `title`), UPDATE (`description`, `instructions`, `minutes`, `title`) ON `goiy_mon_an`.`v2_recipe_revisions` TO `goiy_admin_writer`@`localhost`",
        "GRANT SELECT (`id`), INSERT (`author_ref`, `id`, `origin_kind`) ON `goiy_mon_an`.`v2_recipes` TO `goiy_admin_writer`@`localhost`",
        "GRANT SELECT (`revision_id`) ON `goiy_mon_an`.`v2_release_recipes` TO `goiy_admin_writer`@`localhost`",
    ]+REVIEW_GRANTS)


def test_generated_writer_password_is_sql_quoted():
    assert _mysql_literal("abc'\\def")=="'abc\\'\\\\def'"


def test_codex_grants_allow_project_admin_and_user_creation_only():
    validate_codex_grants([
        "GRANT USAGE ON *.* TO `goiy_codex_admin`@`localhost`",
        "GRANT CREATE USER ON *.* TO `goiy_codex_admin`@`localhost`",
        "GRANT ALL PRIVILEGES ON `goiy_mon_an`.* TO `goiy_codex_admin`@`localhost` WITH GRANT OPTION",
    ])


def test_codex_grants_allow_mysql_to_omit_implicit_usage_row():
    validate_codex_grants([
        "GRANT CREATE USER ON *.* TO `goiy_codex_admin`@`localhost`",
        "GRANT ALL PRIVILEGES ON `goiy_mon_an`.* TO `goiy_codex_admin`@`localhost` WITH GRANT OPTION",
    ])


def test_codex_grants_reject_global_database_privileges():
    try:
        validate_codex_grants([
            "GRANT USAGE ON *.* TO `goiy_codex_admin`@`localhost`",
            "GRANT CREATE USER ON *.* TO `goiy_codex_admin`@`localhost`",
            "GRANT ALL PRIVILEGES ON *.* TO `goiy_codex_admin`@`localhost` WITH GRANT OPTION",
            "GRANT ALL PRIVILEGES ON `goiy_mon_an`.* TO `goiy_codex_admin`@`localhost` WITH GRANT OPTION",
        ])
    except RuntimeError as exc:
        assert "unapproved grant" in str(exc)
    else:
        raise AssertionError("Global database privileges must be rejected")
