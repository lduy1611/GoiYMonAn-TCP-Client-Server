"""Fill input measurement basis only for manually reviewed existing recipes.

Evidence: stored instructions for 2337--2343 explicitly add salt/pepper during
cooking. Existing tsp quantities are input seasoning, not cooked dish weights.
No amount, serving count, unit or ingredient is inferred or replaced.
Run with an explicit TEST_ONLY database name; defaults to a dry run.
"""
import argparse
import mysql.connector
import re
from decimal import Decimal

RECIPE_IDS = tuple(7980670000 + n for n in range(2337, 2344))


def apply(connection, *, write=False):
    cursor = connection.cursor(dictionary=True)
    cursor.execute("""SELECT ri.recipe_id,ri.line_no,ri.quantity_text,i.name
        FROM recipe_ingredients ri JOIN ingredients i USING(ingredient_id)
        JOIN units u USING(unit_id) WHERE ri.recipe_id IN (%s,%s,%s,%s,%s,%s,%s)
        AND ri.measurement_basis='unknown' AND ri.purpose='seasoning'
        AND ri.amount_kind='exact' AND ri.amount_min>0 AND ri.amount_min=ri.amount_max
        AND u.code='tsp' AND i.name IN ('Muối','Tiêu đen')
        ORDER BY ri.recipe_id,ri.line_no""", RECIPE_IDS)
    rows = cursor.fetchall()
    if write:
        for row in rows:
            cursor.execute("""UPDATE recipe_ingredients SET measurement_basis='gross'
                WHERE recipe_id=%s AND line_no=%s AND measurement_basis='unknown'""",
                (row['recipe_id'], row['line_no']))
    cursor.close()
    return rows



def normalize_reviewed_input_basis(connection):
    """Existing instructions explicitly prepare these ingredients before cooking.

    2403: clean raw squid, slice ginger/onion, crush lemongrass, then steam.
    Lemongrass and onion are steaming aromatics, not mass portion drivers.
    2414: wash/cut ingredients, add water and seasonings before boiling.
    This does not verify the accuracy of source amounts or invent conversions.
    """
    cursor = connection.cursor()
    changed = 0
    try:
        for rid in (7980672403, 7980672414):
            cursor.execute("SELECT instructions_legacy FROM recipes WHERE recipe_id=%s", (rid,))
            instructions = cursor.fetchone()
            if not instructions or not instructions[0]:
                raise ValueError("Reviewed instructions unavailable")
            cursor.execute("""UPDATE recipe_ingredients SET measurement_basis='gross'
                WHERE recipe_id=%s AND measurement_basis='unknown' AND amount_kind='exact'
                AND amount_min>0 AND amount_min=amount_max AND unit_id IS NOT NULL""", (rid,))
            changed += cursor.rowcount
        cursor.execute("""UPDATE recipe_ingredients SET purpose='seasoning'
            WHERE recipe_id=7980672403 AND line_no IN (3,4) AND purpose='main'""")
        changed += cursor.rowcount
        return changed
    finally:
        cursor.close()


def normalize_existing_input_amounts(connection):
    """Complete measurement basis for the reviewed input-ingredient batch.

    Retain every existing amount, unit, serving and cooking instruction. These
    recipes list preparation of the ingredients before cooking. Treat amounts
    as purchased/input quantities, with no edible yield or cooked yield assumed.
    The basis interpretation is ESTIMATED, not external source verification.
    Count main ingredients remain counts and cannot be converted to mass.
    """
    cursor = connection.cursor(dictionary=True)
    try:
        ids = (7980672398, *range(7980672417,7980672471))
        changed = []
        for rid in ids:
            cursor.execute("SELECT instructions_legacy,portion_data_status FROM recipes WHERE recipe_id=%s AND is_public=1 AND deleted_at IS NULL",(rid,))
            row=cursor.fetchone()
            if not row or row['portion_data_status']=='verified':
                continue
            cursor.execute("SELECT COUNT(*) n FROM recipe_ingredients WHERE recipe_id=%s AND (amount_min IS NULL OR unit_id IS NULL OR scaling_mode='unknown')",(rid,))
            if cursor.fetchone()['n']:
                continue
            cursor.execute("SELECT COUNT(*) n FROM recipe_ingredients WHERE recipe_id=%s AND measurement_basis='unknown'",(rid,))
            if not cursor.fetchone()['n']:
                continue
            cursor.execute("UPDATE recipe_ingredients SET measurement_basis='gross' WHERE recipe_id=%s AND measurement_basis='unknown'",(rid,))
            line_count=cursor.rowcount
            evidence=("ESTIMATED measurement basis only. Evidence: this recipe's existing ingredient list and preparation instructions "
                "place ingredients before cooking. Assumption: existing quantities measure purchased/input ingredients; "
                "no edible/cooked yield, count-to-mass conversion or new amount is assumed. Existing servings and amounts "
                "are retained, not independently verified. Admin must review ambiguous preparation states and source quantities.")
            cursor.execute("UPDATE recipes SET portion_data_status='estimated',portion_data_evidence=%s,edit_version=edit_version+1 WHERE recipe_id=%s",(evidence,rid))
            changed.append((rid,line_count))
        return changed
    finally:
        cursor.close()


def parse_explicit_missing_amounts(connection):
    """Transcribe explicit source text only, without inventing unit conversions.

    Unknown measurement basis/scaling stays unknown. Ambiguous spoons, bunches,
    taste quantities and compound quantities are deliberately not accepted.
    """
    units = {'g':'g','kg':'kg','ml':'ml','l':'l','lít':'l',
             'muỗng canh':'tbsp','thìa canh':'tbsp',
             'muỗng cà phê':'tsp','thìa cà phê':'tsp',
             'tép':'clove','nhánh':'stalk','cây':'stalk',
             'quả':'piece','trái':'piece','cái':'piece'}
    pattern = re.compile(r'^(\d+(?:[.,]\d+)?|\d+/\d+)\s*('+
                         '|'.join(re.escape(k) for k in units)+r')(?:, băm)?$')
    cursor=connection.cursor(dictionary=True)
    try:
        cursor.execute('SELECT code,unit_id FROM units')
        ids={r['code']:r['unit_id'] for r in cursor.fetchall()}
        cursor.execute("""SELECT i.recipe_id,i.line_no,i.quantity_text FROM recipe_ingredients i
            JOIN recipes r USING(recipe_id) WHERE r.is_public=1 AND r.deleted_at IS NULL
            AND i.amount_min IS NULL AND i.amount_max IS NULL AND i.amount_kind='unknown'""")
        changed=[]
        for row in cursor.fetchall():
            match=pattern.fullmatch((row['quantity_text'] or '').strip().lower())
            if not match or units[match[2]] not in ids:
                continue
            value=match[1].replace(',','.')
            if '/' in value:
                a,b=value.split('/')
                if Decimal(b)==0:
                    continue
                value=Decimal(a)/Decimal(b)
            else:
                value=Decimal(value)
            if value<=0 or value.quantize(Decimal('.000001'))!=value:
                continue
            cursor.execute("""UPDATE recipe_ingredients SET amount_kind='exact',amount_min=%s,
                amount_max=%s,unit_id=%s WHERE recipe_id=%s AND line_no=%s
                AND amount_min IS NULL AND amount_max IS NULL AND amount_kind='unknown'""",
                (value,value,ids[units[match[2]]],row['recipe_id'],row['line_no']))
            changed.append((row['recipe_id'],row['line_no']))
        for rid in sorted({rid for rid, _ in changed}):
            cursor.execute("""UPDATE recipes SET edit_version=edit_version+1,
                portion_data_evidence=CONCAT(COALESCE(portion_data_evidence,''),%s)
                WHERE recipe_id=%s""", (
                '\nExplicit numeric amounts transcribed from existing quantity_text only; '
                'no ambiguous unit conversion, serving assumption or source verification. '
                'Existing review status retained.', rid))
        return changed
    finally:
        cursor.close()


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--input-basis-batch',action='store_true')
    parser.add_argument('--explicit-amounts',action='store_true')
    args=parser.parse_args()
    if not args.database.endswith('_test'):
        parser.error('Only explicitly isolated TEST_ONLY databases are supported')
    connection=mysql.connector.connect(host='127.0.0.1',port=63900,user='root',password='',database=args.database,charset='utf8mb4')
    try:
        rows=apply(connection,write=True)
        if args.input_basis_batch:
            rows+=normalize_existing_input_amounts(connection)
        if args.explicit_amounts:
            rows+=parse_explicit_missing_amounts(connection)
        if args.apply:
            connection.commit()
        else:
            connection.rollback()
        print('Applied' if args.apply else 'Dry run (rolled back)',len(rows),'changes')
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
