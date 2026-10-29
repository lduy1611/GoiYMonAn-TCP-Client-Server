# SQLite → MySQL migration report

Date: 2026-10-29  
Scope: phase 3 database migration

## 1. Source SQLite structure

The preserved `data/recipes.db` contains five tables:

- `metadata(key, value)` — dataset version.
- `ingredients(id, name, normalized_name)` — ingredient master data.
- `ingredient_aliases(alias_norm, ingredient_id)` — aliases with a foreign key to ingredients.
- `recipes(id, title, instructions, minutes, source_url, source_note)` — recipe data.
- `recipe_ingredients(recipe_id, ingredient_id, quantity, is_required)` — many-to-many relation with a composite primary key.

Foreign keys are enabled on SQLite connections. The current demo source contains 15 ingredients, 10 recipes and 29 recipe-ingredient relations.

## 2. MySQL design

[source/database/database.sql](source/database/database.sql) maps the schema to MySQL 8.0+ using `InnoDB` and `utf8mb4`. Integer IDs are preserved as explicit `INT UNSIGNED` primary keys; no `AUTO_INCREMENT` is used. Foreign keys and the composite relation key are preserved. `is_required` maps to `TINYINT(1)`, while SQLite `CHECK` constraints are represented by MySQL `CHECK` constraints.

[source/database/mysql_seed.sql](source/database/mysql_seed.sql) contains the same demo IDs and values. It is separate from the schema script so Workbench can run schema creation and data loading as two visible steps.

## 3. Runtime architecture

- `TCPServer()` without a database path constructs `MySQLRepository.from_env()`.
- `MySQLRepository` reads the five `MYSQL_*` variables using `python-dotenv`.
- `mysql.connector.pooling.MySQLConnectionPool` is created with a maximum of 32 connections.
- Each TCP request checks out one connection and closes it in the existing handler `finally` block, returning it to the pool.
- FastAPI and `TCPClient` have no repository/MySQL imports.
- The old SQLite `Repository` remains available only when an explicit SQLite path is passed, for rollback and regression tests.

## 4. Migration procedure

1. Create the MySQL database/schema in Workbench by running `source/database/database.sql`.
2. Load the demo data with `source/database/mysql_seed.sql`, or copy the existing SQLite data with:

   ```powershell
   .\.venv\Scripts\python.exe -m source.database.migrate_sqlite_to_mysql --sqlite data/recipes.db
   ```

3. Copy `.env.example` to `.env` and set the actual MySQL account and database.
4. Start `python -m source.server.main`; it now requires MySQL configuration.
5. Run the MySQL integration tests and record the actual output below.

The migration utility opens SQLite in read-only mode and never deletes or modifies `data/recipes.db`.

## 5. Verification status

Verification was executed on 2026-10-29 using the configured `.venv` and configured MySQL environment. Secret values were not printed or written to this report.

Runtime evidence:

```text
repository_class=MySQLRepository
repository_module=source.server.repository
mysql_pool_initialized=True
```

Full suite:

```text
16 passed, 0 failed, 0 skipped, 1 warning in 9.68s
```

MySQL integration suite:

```text
tests/test_mysql_integration.py::test_mysql_tcp_operations PASSED
tests/test_mysql_integration.py::test_mysql_multiclient_and_http_outage PASSED
2 passed, 0 failed, 0 skipped, 1 warning in 2.42s
```

The MySQL integration tests exercised PING, LIST_INGREDIENTS, GET_RECIPE, RECOMMEND, ten concurrent TCP clients, and FastAPI HTTP 503 after the TCP Server was stopped. Static import audit found no MySQL/SQLite repository or ranking references in the Web or TCP Client packages. The SQLite database remains preserved for regression/rollback comparison.

Logs:

- [phase3_runtime_backend.log](statics/results/phase3_runtime_backend.log)
- [phase3_migration_pytest.log](statics/results/phase3_migration_pytest.log)
- [phase3_mysql_integration.log](statics/results/phase3_mysql_integration.log)
