-- Additive MySQL >= 8.0.16 schema. Run only through source.database.migrate_v2.
-- No USE, legacy DML, seed, recipe import, unit seed or approval is included.
CREATE TABLE v2_sources (
 id BIGINT UNSIGNED PRIMARY KEY,
 source_kind VARCHAR(40) NOT NULL,
 title VARCHAR(255) NOT NULL,
 url VARCHAR(1000) NULL,
 document_ref VARCHAR(255) NULL,
 author_or_publisher VARCHAR(255) NULL,
 accessed_at DATETIME(6) NULL,
 content_hash CHAR(64) CHARACTER SET ascii NULL,
 usage_note TEXT NULL,
 verification_status VARCHAR(24) NOT NULL DEFAULT 'NEEDS_VERIFICATION',
 CHECK (verification_status IN ('DRAFT','NEEDS_VERIFICATION','APPROVED','REJECTED','SUPERSEDED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE v2_evidence_sets (
 id BIGINT UNSIGNED PRIMARY KEY,
 description VARCHAR(255) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE v2_evidence (
 id BIGINT UNSIGNED PRIMARY KEY,
 source_id BIGINT UNSIGNED NOT NULL,
 locator VARCHAR(500) NOT NULL,
 excerpt_or_observation TEXT NOT NULL,
 claim_scope VARCHAR(40) CHARACTER SET ascii NOT NULL,
 entity_ref VARCHAR(120) CHARACTER SET ascii NOT NULL,
 captured_at DATETIME(6) NOT NULL,
 content_hash CHAR(64) CHARACTER SET ascii NULL,
 FOREIGN KEY (source_id) REFERENCES v2_sources(id) ON DELETE RESTRICT,
 KEY idx_v2_evidence_claim (claim_scope,entity_ref)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE v2_evidence_set_members (
 evidence_set_id BIGINT UNSIGNED NOT NULL,
 evidence_id BIGINT UNSIGNED NOT NULL,
 PRIMARY KEY (evidence_set_id,evidence_id),
 FOREIGN KEY (evidence_set_id) REFERENCES v2_evidence_sets(id) ON DELETE RESTRICT,
 FOREIGN KEY (evidence_id) REFERENCES v2_evidence(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE v2_review_decisions (
 id BIGINT UNSIGNED PRIMARY KEY,
 decision VARCHAR(24) NOT NULL DEFAULT 'NEEDS_VERIFICATION',
 reviewer_ref VARCHAR(255) NOT NULL,
 decided_at DATETIME(6) NOT NULL,
 rationale TEXT NOT NULL,
 claim_scope VARCHAR(40) CHARACTER SET ascii NOT NULL,
 entity_ref VARCHAR(120) CHARACTER SET ascii NOT NULL,
 subject_hash CHAR(64) CHARACTER SET ascii NOT NULL,
 evidence_set_id BIGINT UNSIGNED NOT NULL,
 FOREIGN KEY (evidence_set_id) REFERENCES v2_evidence_sets(id) ON DELETE RESTRICT,
 CHECK (decision IN ('NEEDS_VERIFICATION','APPROVED','REJECTED')),
 CHECK (CHAR_LENGTH(TRIM(reviewer_ref)) > 0),
 KEY idx_v2_review_claim (claim_scope,entity_ref,decision)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE v2_ingredients (
 id BIGINT UNSIGNED PRIMARY KEY,
 legacy_ingredient_id INT UNSIGNED NULL UNIQUE,
 canonical_name VARCHAR(255) NOT NULL,
 normalized_name VARCHAR(255) NOT NULL,
 identity_status VARCHAR(24) NOT NULL DEFAULT 'NEEDS_VERIFICATION',
 evidence_set_id BIGINT UNSIGNED NULL,
 review_decision_id BIGINT UNSIGNED NULL,
 FOREIGN KEY (legacy_ingredient_id) REFERENCES ingredients(id) ON DELETE RESTRICT,
 FOREIGN KEY (evidence_set_id) REFERENCES v2_evidence_sets(id) ON DELETE RESTRICT,
 FOREIGN KEY (review_decision_id) REFERENCES v2_review_decisions(id) ON DELETE RESTRICT,
 CHECK (identity_status IN ('DRAFT','NEEDS_VERIFICATION','APPROVED','REJECTED','SUPERSEDED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE v2_ingredient_forms (
 id BIGINT UNSIGNED PRIMARY KEY,
 ingredient_id BIGINT UNSIGNED NOT NULL,
 form_code VARCHAR(80) NOT NULL,
 description VARCHAR(255) NOT NULL,
 status VARCHAR(24) NOT NULL DEFAULT 'NEEDS_VERIFICATION',
 evidence_set_id BIGINT UNSIGNED NULL,
 review_decision_id BIGINT UNSIGNED NULL,
 UNIQUE (ingredient_id,form_code),
 UNIQUE (id,ingredient_id),
 FOREIGN KEY (ingredient_id) REFERENCES v2_ingredients(id) ON DELETE RESTRICT,
 FOREIGN KEY (evidence_set_id) REFERENCES v2_evidence_sets(id) ON DELETE RESTRICT,
 FOREIGN KEY (review_decision_id) REFERENCES v2_review_decisions(id) ON DELETE RESTRICT,
 CHECK (status IN ('DRAFT','NEEDS_VERIFICATION','APPROVED','REJECTED','SUPERSEDED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE v2_units (
 id BIGINT UNSIGNED PRIMARY KEY,
 code VARCHAR(40) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
 dimension VARCHAR(20) NOT NULL,
 symbol VARCHAR(40) NOT NULL,
 definition VARCHAR(255) NOT NULL,
 status VARCHAR(24) NOT NULL DEFAULT 'NEEDS_VERIFICATION',
 evidence_set_id BIGINT UNSIGNED NULL,
 review_decision_id BIGINT UNSIGNED NULL,
 FOREIGN KEY (evidence_set_id) REFERENCES v2_evidence_sets(id) ON DELETE RESTRICT,
 FOREIGN KEY (review_decision_id) REFERENCES v2_review_decisions(id) ON DELETE RESTRICT,
 CHECK (dimension IN ('mass','volume','count','source_defined')),
 CHECK (status IN ('DRAFT','NEEDS_VERIFICATION','APPROVED','REJECTED','SUPERSEDED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE v2_recipes (
 id BIGINT UNSIGNED PRIMARY KEY,
 legacy_recipe_id INT UNSIGNED NULL UNIQUE,
 variant_of_recipe_id BIGINT UNSIGNED NULL,
 origin_kind VARCHAR(24) NOT NULL,
 author_ref VARCHAR(255) NULL,
 FOREIGN KEY (legacy_recipe_id) REFERENCES recipes(id) ON DELETE RESTRICT,
 FOREIGN KEY (variant_of_recipe_id) REFERENCES v2_recipes(id) ON DELETE RESTRICT,
 CHECK (origin_kind IN ('legacy_import','curated_new','curated_variant'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE v2_recipe_revisions (
 id BIGINT UNSIGNED PRIMARY KEY,
 recipe_id BIGINT UNSIGNED NOT NULL,
 revision_no INT UNSIGNED NOT NULL,
 title VARCHAR(255) NOT NULL,
 instructions TEXT NOT NULL,
 minutes SMALLINT UNSIGNED NULL,
 base_servings DECIMAL(10,3) NULL,
 serving_basis VARCHAR(24) NULL,
 content_complete BOOLEAN NOT NULL DEFAULT FALSE,
 status VARCHAR(24) NOT NULL DEFAULT 'DRAFT',
 content_evidence_set_id BIGINT UNSIGNED NULL,
 servings_evidence_set_id BIGINT UNSIGNED NULL,
 content_review_id BIGINT UNSIGNED NULL,
 servings_review_id BIGINT UNSIGNED NULL,
 legacy_snapshot_hash CHAR(64) CHARACTER SET ascii NULL,
 UNIQUE (recipe_id,revision_no),
 UNIQUE (id,recipe_id),
 FOREIGN KEY (recipe_id) REFERENCES v2_recipes(id) ON DELETE RESTRICT,
 FOREIGN KEY (content_evidence_set_id) REFERENCES v2_evidence_sets(id) ON DELETE RESTRICT,
 FOREIGN KEY (servings_evidence_set_id) REFERENCES v2_evidence_sets(id) ON DELETE RESTRICT,
 FOREIGN KEY (content_review_id) REFERENCES v2_review_decisions(id) ON DELETE RESTRICT,
 FOREIGN KEY (servings_review_id) REFERENCES v2_review_decisions(id) ON DELETE RESTRICT,
 CHECK (revision_no > 0),
 CHECK (minutes IS NULL OR minutes BETWEEN 1 AND 240),
 CHECK (base_servings IS NULL OR base_servings > 0),
 CHECK (content_complete IN (0,1)),
 CHECK (serving_basis IS NULL OR serving_basis IN ('source_servings','adult_equivalent')),
 CHECK (status IN ('DRAFT','NEEDS_VERIFICATION','APPROVED','REJECTED','SUPERSEDED')),
 KEY idx_v2_revision_status (status,recipe_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE v2_recipe_ingredient_lines (
 revision_id BIGINT UNSIGNED NOT NULL,
 line_no INT UNSIGNED NOT NULL,
 ingredient_id BIGINT UNSIGNED NULL,
 form_id BIGINT UNSIGNED NULL,
 quantity_raw VARCHAR(255) NULL,
 amount_kind VARCHAR(20) NOT NULL DEFAULT 'unknown',
 amount_min DECIMAL(18,6) NULL,
 amount_max DECIMAL(18,6) NULL,
 unit_id BIGINT UNSIGNED NULL,
 requirement VARCHAR(16) NOT NULL DEFAULT 'unknown',
 purpose VARCHAR(20) NOT NULL DEFAULT 'unknown',
 measurement_basis VARCHAR(20) NOT NULL DEFAULT 'unknown',
 scaling_mode VARCHAR(20) NULL,
 status VARCHAR(24) NOT NULL DEFAULT 'DRAFT',
 quantity_evidence_set_id BIGINT UNSIGNED NULL,
 quantity_review_id BIGINT UNSIGNED NULL,
 scaling_evidence_set_id BIGINT UNSIGNED NULL,
 scaling_review_id BIGINT UNSIGNED NULL,
 legacy_relation_hash CHAR(64) CHARACTER SET ascii NULL,
 PRIMARY KEY (revision_id,line_no),
 FOREIGN KEY (revision_id) REFERENCES v2_recipe_revisions(id) ON DELETE RESTRICT,
 FOREIGN KEY (ingredient_id) REFERENCES v2_ingredients(id) ON DELETE RESTRICT,
 FOREIGN KEY (form_id,ingredient_id) REFERENCES v2_ingredient_forms(id,ingredient_id) ON DELETE RESTRICT,
 FOREIGN KEY (unit_id) REFERENCES v2_units(id) ON DELETE RESTRICT,
 FOREIGN KEY (quantity_evidence_set_id) REFERENCES v2_evidence_sets(id) ON DELETE RESTRICT,
 FOREIGN KEY (quantity_review_id) REFERENCES v2_review_decisions(id) ON DELETE RESTRICT,
 FOREIGN KEY (scaling_evidence_set_id) REFERENCES v2_evidence_sets(id) ON DELETE RESTRICT,
 FOREIGN KEY (scaling_review_id) REFERENCES v2_review_decisions(id) ON DELETE RESTRICT,
 CHECK (line_no > 0),
 CHECK (form_id IS NULL OR ingredient_id IS NOT NULL),
 CHECK (amount_kind IN ('exact','range','to_taste','as_needed','unknown')),
 CHECK (amount_min IS NULL OR amount_min > 0),
 CHECK (amount_max IS NULL OR amount_max > 0),
 CHECK (amount_min IS NULL OR amount_max IS NULL OR amount_min <= amount_max),
 CHECK (amount_kind <> 'exact' OR amount_max IS NULL OR amount_min = amount_max),
 CHECK (requirement IN ('required','optional','unknown')),
 CHECK (purpose IN ('consumed','cooking_medium','garnish','unknown')),
 CHECK (measurement_basis IN ('gross','edible','prepared','unknown')),
 CHECK (scaling_mode IS NULL OR scaling_mode IN ('linear','fixed')),
 CHECK (status IN ('DRAFT','NEEDS_VERIFICATION','APPROVED','REJECTED','SUPERSEDED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE v2_portion_policy_versions (
 id BIGINT UNSIGNED PRIMARY KEY,
 policy_code VARCHAR(40) CHARACTER SET ascii NOT NULL,
 version VARCHAR(39) CHARACTER SET ascii NOT NULL,
 description VARCHAR(255) NOT NULL,
 status VARCHAR(24) NOT NULL DEFAULT 'DRAFT',
 evidence_set_id BIGINT UNSIGNED NULL,
 review_decision_id BIGINT UNSIGNED NULL,
 UNIQUE (policy_code,version),
 FOREIGN KEY (evidence_set_id) REFERENCES v2_evidence_sets(id) ON DELETE RESTRICT,
 FOREIGN KEY (review_decision_id) REFERENCES v2_review_decisions(id) ON DELETE RESTRICT,
 CHECK (status IN ('DRAFT','NEEDS_VERIFICATION','APPROVED','REJECTED','SUPERSEDED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE v2_portion_policy_rules (
 policy_version_id BIGINT UNSIGNED NOT NULL,
 rule_no INT UNSIGNED NOT NULL,
 recipe_id BIGINT UNSIGNED NOT NULL,
 revision_id BIGINT UNSIGNED NOT NULL,
 subject_group VARCHAR(24) NOT NULL DEFAULT 'person',
 input_definition VARCHAR(40) NOT NULL DEFAULT 'per_person',
 serving_basis VARCHAR(24) NOT NULL,
 equivalent_servings DECIMAL(10,6) NULL,
 status VARCHAR(24) NOT NULL DEFAULT 'DRAFT',
 evidence_set_id BIGINT UNSIGNED NULL,
 review_decision_id BIGINT UNSIGNED NULL,
 PRIMARY KEY (policy_version_id,rule_no),
 UNIQUE (policy_version_id,recipe_id),
 FOREIGN KEY (policy_version_id) REFERENCES v2_portion_policy_versions(id) ON DELETE RESTRICT,
 FOREIGN KEY (revision_id,recipe_id) REFERENCES v2_recipe_revisions(id,recipe_id) ON DELETE RESTRICT,
 FOREIGN KEY (evidence_set_id) REFERENCES v2_evidence_sets(id) ON DELETE RESTRICT,
 FOREIGN KEY (review_decision_id) REFERENCES v2_review_decisions(id) ON DELETE RESTRICT,
 CHECK (rule_no > 0),
 CHECK (equivalent_servings IS NULL OR equivalent_servings > 0),
 CHECK (serving_basis IN ('source_servings','adult_equivalent')),
 CHECK (status IN ('DRAFT','NEEDS_VERIFICATION','APPROVED','REJECTED','SUPERSEDED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE v2_data_releases (
 id BIGINT UNSIGNED PRIMARY KEY,
 code VARCHAR(80) CHARACTER SET ascii NOT NULL UNIQUE,
 legacy_dataset_version VARCHAR(255) NOT NULL,
 legacy_baseline_hash CHAR(64) CHARACTER SET ascii NULL,
 status VARCHAR(24) NOT NULL DEFAULT 'DRAFT',
 approved_at DATETIME(6) NULL,
 manifest_hash CHAR(64) CHARACTER SET ascii NULL,
 evidence_set_id BIGINT UNSIGNED NULL,
 review_decision_id BIGINT UNSIGNED NULL,
 FOREIGN KEY (evidence_set_id) REFERENCES v2_evidence_sets(id) ON DELETE RESTRICT,
 FOREIGN KEY (review_decision_id) REFERENCES v2_review_decisions(id) ON DELETE RESTRICT,
 CHECK (status IN ('DRAFT','NEEDS_VERIFICATION','PUBLISHED','REJECTED','SUPERSEDED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE v2_release_recipes (
 release_id BIGINT UNSIGNED NOT NULL,
 recipe_id BIGINT UNSIGNED NOT NULL,
 revision_id BIGINT UNSIGNED NOT NULL,
 PRIMARY KEY (release_id,recipe_id),
 FOREIGN KEY (release_id) REFERENCES v2_data_releases(id) ON DELETE RESTRICT,
 FOREIGN KEY (revision_id,recipe_id) REFERENCES v2_recipe_revisions(id,recipe_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE v2_release_portion_policies (
 release_id BIGINT UNSIGNED NOT NULL,
 selection_key VARCHAR(80) CHARACTER SET ascii NOT NULL,
 policy_version_id BIGINT UNSIGNED NOT NULL,
 PRIMARY KEY (release_id,selection_key),
 FOREIGN KEY (release_id) REFERENCES v2_data_releases(id) ON DELETE RESTRICT,
 FOREIGN KEY (policy_version_id) REFERENCES v2_portion_policy_versions(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE v2_calculation_settings (
 id TINYINT UNSIGNED PRIMARY KEY,
 active_release_id BIGINT UNSIGNED NULL,
 FOREIGN KEY (active_release_id) REFERENCES v2_data_releases(id) ON DELETE RESTRICT,
 CHECK (id = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Review decisions are append-only, including synthetic decisions in test DBs.
CREATE TRIGGER v2_review_no_update BEFORE UPDATE ON v2_review_decisions
 FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Review decisions are immutable';
CREATE TRIGGER v2_review_no_delete BEFORE DELETE ON v2_review_decisions
 FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Review decisions are immutable';
