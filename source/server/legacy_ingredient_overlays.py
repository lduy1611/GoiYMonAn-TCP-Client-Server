"""Read-only interpretation of Admin overlays for legacy ingredient rows."""


def read_overrides(connection, ingredient_ids=None):
    ids = tuple(sorted(set(ingredient_ids or ())))
    where = " WHERE ingredient_id IN (" + ",".join("%s" for _ in ids) + ")" if ids else ""
    cursor = connection.cursor(dictionary=True)
    try:
        try:
            cursor.execute("""SELECT ingredient_id,name_override,normalized_name,is_active,updated_by,updated_at
                FROM v2_admin_legacy_ingredient_overrides""" + where, ids)
            rows = cursor.fetchall()
        except Exception as exc:
            import mysql.connector
            if isinstance(exc, mysql.connector.Error) and exc.errno == 1146:
                return {}
            raise
        return {int(row["ingredient_id"]): {**row, "ingredient_id": int(row["ingredient_id"]),
                "is_active": bool(row["is_active"])} for row in rows}
    finally:
        cursor.close()


def display_name(name, override):
    return override["name_override"] if override and override["name_override"] is not None else name
