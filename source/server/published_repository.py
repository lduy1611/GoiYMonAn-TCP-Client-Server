"""Request-local union view; legacy ranking/v1 never construct this wrapper."""
from dataclasses import replace
from hashlib import sha256
import json

from source.common.catalog_ids import V2_OFFSET
from source.server.meal_plan import Classification


class PublishedRepository:
    def __init__(self, legacy, catalog):
        self.legacy, self.catalog = legacy, catalog

    def __getattr__(self, name):
        return getattr(self.legacy, name)

    def dataset_version(self, connection):
        # Ingredient-picker membership is part of the saved User view. Bump its
        # public token when the projection changes so old cached selections and
        # recommendation results are revalidated after catalog-policy changes.
        legacy_version=self.legacy.dataset_version(connection)
        catalog=self._user_ingredient_rows(connection)
        catalog_hash=sha256(json.dumps([(r["id"],r["name"]) for r in catalog],
            ensure_ascii=False,separators=(",",":")).encode("utf-8")).hexdigest()[:16]
        return f"{legacy_version}:user-catalog-v2:{self.catalog.version}:{catalog_hash}"

    def meal_classification(self, classification):
        if not self.catalog.details:
            return classification
        return Classification(classification.version + ':' + self.catalog.version,
                              {**classification.categories, **self.catalog.roles})

    def get_recipe(self, connection, recipe_id):
        if recipe_id in self.catalog.hidden_ids or recipe_id in self.catalog.deleted_ids:
            return None
        if recipe_id > V2_OFFSET:
            return self.catalog.details.get(recipe_id)
        return self.legacy.get_recipe(connection, recipe_id)

    def public_recipe_image(self, connection, recipe_id):
        if recipe_id in self.catalog.hidden_ids or recipe_id in self.catalog.deleted_ids:
            return None
        return self.legacy.public_recipe_image(connection, recipe_id)

    def recipe_ids_exist(self, connection, ids):
        if set(ids) & (self.catalog.hidden_ids | self.catalog.deleted_ids):
            return False
        new = {i for i in ids if i > V2_OFFSET}
        old = tuple(i for i in ids if i <= V2_OFFSET)
        return new <= self.catalog.details.keys() and (not old or self.legacy.recipe_ids_exist(connection,old))

    def recipes_for_ranking(self, connection):
        old=[r for r in self.legacy.recipes_for_ranking(connection)
             if r['id'] not in self.catalog.hidden_ids and r['id'] not in self.catalog.deleted_ids]
        return old + [
            {'id':r['id'],'title':r['title'],'minutes':r['minutes'],
             'required_ids':{i['id'] for i in r['ingredients'] if i['is_required']},
             'all_ids':{i['id'] for i in r['ingredients']}}
            for r in self.catalog.details.values()
            if r['id'] not in self.catalog.hidden_ids and r['id'] not in self.catalog.deleted_ids]

    def recipes_for_search(self, connection):
        old=[r for r in self.legacy.recipes_for_search(connection)
             if r['id'] not in self.catalog.hidden_ids and r['id'] not in self.catalog.deleted_ids]
        return old + [
            {'id':r['id'],'title':r['title'],'minutes':r['minutes'],
             'required_ids':{i['id'] for i in r['ingredients'] if i['is_required']},
             'all_ids':{i['id'] for i in r['ingredients']},
             'ingredient_names':[i['name'] for i in r['ingredients']]}
            for r in self.catalog.details.values()
            if r['id'] not in self.catalog.hidden_ids and r['id'] not in self.catalog.deleted_ids]

    def ingredient_ids_exist(self, connection, ids):
        # User filters must match the public ingredient projection below. V2
        # storage identities stay hidden until explicitly added to that view.
        if not ids:
            return True
        public={row["id"] for row in self._user_ingredient_rows(connection)}
        return set(ids)<=public

    def list_ingredients(self, connection, query, limit):
        return self._user_ingredient_rows(connection,query=query,limit=limit)

    def _user_ingredient_rows(self,connection,query="",limit=None):
        # Legacy remains the original User catalog. A v2-only identity is
        # exposed only when it occurs in a verified, active recipe release;
        # merely existing in v2_ingredients (or a direct Admin save) is not
        # sufficient to add it to the public picker.
        rows=self.legacy._legacy_ingredient_catalog(
            connection,query=query,include_inactive=False)
        seen={int(row["id"]) for row in rows}
        from source.common.catalog_ids import V2_OFFSET
        from source.server.repository import ingredient_search_normalize
        eligible={int(iid)-V2_OFFSET for iid in self.catalog.release_ingredient_ids
                  if int(iid)>V2_OFFSET}
        from source.server.ingredient_catalog import normalized_key
        existing_names={normalized_key(name) for row in rows
                        for name in (row["name"],*row.get("aliases",[]))}
        conditions=[];params=[]
        if eligible:
            marks=",".join("%s" for _ in eligible)
            conditions.append(f"i.id IN ({marks})")
            params.extend(sorted(eligible))
        # An explicit Admin-created ingredient is part of the common public
        # catalog immediately. Imported NEEDS_VERIFICATION/DRAFT identities
        # are not exposed by this path.
        conditions.append("(i.identity_status='DRAFT' AND i.review_decision_id IS NULL AND i.evidence_set_id IS NULL AND i.legacy_ingredient_id IS NULL)")
        where=" OR ".join(conditions)
        try:
            stored=self.legacy._fetchall(connection,f"""SELECT i.id,i.canonical_name,COALESCE(s.is_active,1)
                FROM v2_ingredients i LEFT JOIN v2_ingredient_admin_state s ON s.ingredient_id=i.id
                WHERE ({where}) ORDER BY i.id""",tuple(params))
        except Exception as exc:
            if getattr(exc,"errno",None)!=1146:raise
            # The core legacy-only deployment has no v2 ingredient tables yet.
            # Missing the optional activation table falls back to the core v2
            # table; if that table is absent too, the published ingredient
            # projection is simply the active legacy catalog.
            try:
                stored=[(*row,1) for row in self.legacy._fetchall(connection,
                    f"SELECT i.id,i.canonical_name FROM v2_ingredients i WHERE ({where}) ORDER BY i.id",
                    tuple(params))]
            except Exception as missing:
                if getattr(missing,"errno",None)!=1146:raise
                stored=[]
        needle=ingredient_search_normalize(query.strip()) if query else ""
        for ingredient_id,name,is_active in stored:
            public_id=V2_OFFSET+int(ingredient_id)
            key=normalized_key(name)
            if public_id in seen or key in existing_names or not is_active:
                continue
            if needle and needle not in ingredient_search_normalize(name):
                continue
            rows.append({"id":public_id,"name":name})
            seen.add(public_id);existing_names.add(key)
        # Use the same normalized display order as Admin's shared projection.
        rows.sort(key=lambda row:(normalized_key(row["name"]),row["id"]))
        return rows if limit is None else rows[:limit]

    def meal_preference_catalog(self, connection, recipes, classification):
        old = [r for r in recipes if r['id'] <= V2_OFFSET]
        catalog = self.legacy.meal_preference_catalog(connection,old,classification)
        if not self.catalog.details:
            return catalog
        assessments = {**catalog.vegetarian_assessments, **{
            rid:{'status':'VERIFIED','reasons':[]} for rid in self.catalog.plant_ids}}
        contexts = {group:{code:frozenset(ids) for code,ids in values.items()}
                    for group,values in catalog.contexts.items()}
        for group,values in self.catalog.contexts.items():
            for code,ids in values.items():
                contexts.setdefault(group,{})[code] = contexts.setdefault(group,{}).get(code,frozenset()) | ids
        return replace(catalog,version=catalog.version + ':' + self.catalog.version,
                       roles={**catalog.roles,**self.catalog.roles},vegetarian_assessments=assessments,
                       contexts=contexts)
