-- Additive context metadata for regional and occasion suitability.
-- Apply only after a matching migration runner revision is approved. No data,
-- review decisions, labels, or release activation are inserted here.
CREATE TABLE v2_regions (
 id BIGINT UNSIGNED PRIMARY KEY,
 code VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
 label VARCHAR(80) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE v2_occasions (
 id BIGINT UNSIGNED PRIMARY KEY,
 code VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
 label VARCHAR(80) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE v2_recipe_regions (
 id BIGINT UNSIGNED PRIMARY KEY,
 revision_id BIGINT UNSIGNED NOT NULL,
 region_id BIGINT UNSIGNED NOT NULL,
 relation_kind VARCHAR(24) NOT NULL,
 decision VARCHAR(24) NOT NULL DEFAULT 'NEEDS_VERIFICATION',
 evidence_set_id BIGINT UNSIGNED NULL,
 review_decision_id BIGINT UNSIGNED NULL,
 UNIQUE (revision_id,region_id,relation_kind),
 FOREIGN KEY (revision_id) REFERENCES v2_recipe_revisions(id) ON DELETE RESTRICT,
 FOREIGN KEY (region_id) REFERENCES v2_regions(id) ON DELETE RESTRICT,
 FOREIGN KEY (evidence_set_id) REFERENCES v2_evidence_sets(id) ON DELETE RESTRICT,
 FOREIGN KEY (review_decision_id) REFERENCES v2_review_decisions(id) ON DELETE RESTRICT,
 CHECK (relation_kind IN ('origin','suitable_for_meal')),
 CHECK (decision IN ('DRAFT','NEEDS_VERIFICATION','APPROVED','REJECTED')),
 KEY idx_v2_recipe_region (region_id,relation_kind,revision_id,decision)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE v2_recipe_occasions (
 id BIGINT UNSIGNED PRIMARY KEY,
 revision_id BIGINT UNSIGNED NOT NULL,
 occasion_id BIGINT UNSIGNED NOT NULL,
 applicability_context VARCHAR(255) NOT NULL,
 decision VARCHAR(24) NOT NULL DEFAULT 'NEEDS_VERIFICATION',
 evidence_set_id BIGINT UNSIGNED NULL,
 review_decision_id BIGINT UNSIGNED NULL,
 UNIQUE (revision_id,occasion_id),
 FOREIGN KEY (revision_id) REFERENCES v2_recipe_revisions(id) ON DELETE RESTRICT,
 FOREIGN KEY (occasion_id) REFERENCES v2_occasions(id) ON DELETE RESTRICT,
 FOREIGN KEY (evidence_set_id) REFERENCES v2_evidence_sets(id) ON DELETE RESTRICT,
 FOREIGN KEY (review_decision_id) REFERENCES v2_review_decisions(id) ON DELETE RESTRICT,
 CHECK (decision IN ('DRAFT','NEEDS_VERIFICATION','APPROVED','REJECTED')),
 KEY idx_v2_recipe_occasion (occasion_id,revision_id,decision)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- A release-specific reviewed digest pins the complete context assertion set.
-- Any row added/edited after review invalidates the digest and disables filtering.
CREATE TABLE v2_release_context_manifests (
 release_id BIGINT UNSIGNED PRIMARY KEY,
 manifest_hash CHAR(64) CHARACTER SET ascii NOT NULL,
 status VARCHAR(24) NOT NULL DEFAULT 'NEEDS_VERIFICATION',
 evidence_set_id BIGINT UNSIGNED NULL,
 review_decision_id BIGINT UNSIGNED NULL,
 FOREIGN KEY (release_id) REFERENCES v2_data_releases(id) ON DELETE RESTRICT,
 FOREIGN KEY (evidence_set_id) REFERENCES v2_evidence_sets(id) ON DELETE RESTRICT,
 FOREIGN KEY (review_decision_id) REFERENCES v2_review_decisions(id) ON DELETE RESTRICT,
 CHECK (status IN ('DRAFT','NEEDS_VERIFICATION','APPROVED','REJECTED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
