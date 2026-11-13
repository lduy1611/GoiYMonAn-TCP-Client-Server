"""Add a small, unquantified non-alcoholic catalog through existing recipe storage.

No food recipe or quantity is edited. Admin manages these as role=drink recipes
and edits weather/occasion labels through the existing taxonomy screens.
"""
import uuid
from source.database.unified_catalog_migration import _norm, _query
from source.server.admin_recipes import validate_save
from source.server.unified_repository import UnifiedMySQLRepository, _write


BEVERAGES = (
    ('water','Nước lọc dùng chung',[6313135189],[],
     'Dùng nước uống sạch, chọn nhiệt độ theo sở thích. Chưa có định lượng phục vụ được xác minh.'),
    ('lemon','Nước chanh dùng chung',[6313135189,22],['hot','sunny'],
     'Rửa sạch chanh, vắt lấy nước, bỏ hạt rồi pha với nước uống sạch theo khẩu vị. Không có định lượng phục vụ được xác minh.'),
    ('ginger','Nước gừng ấm',[6313135189,8],['cold','rain'],
     'Rửa sạch gừng, thái lát và hãm với nước nóng; để nguội đến nhiệt độ phù hợp trước khi uống. Chưa có định lượng phục vụ được xác minh.'),
)


def apply(config):
    repo=UnifiedMySQLRepository(config)
    result=[]
    for code,title,ingredients,weather,instructions in BEVERAGES:
        payload=validate_save({'title':title,'description':'Gợi ý đồ uống không cồn; chỉ tham khảo, chưa định lượng.',
            'instructions':instructions,'minutes':5,'role':'drink','servings':None,
            'ingredients':[{'ingredient_id':i,'quantity_raw':None,'requirement':'required'} for i in ingredients],
            'idempotency_key':str(uuid.uuid5(uuid.NAMESPACE_URL,'meal-v3-beverage-'+code))},None,unified=True)
        row=repo.admin_save_recipe(payload,'stage4-additive-catalog')
        rid=row['recipe_id']
        if not row['created']:
            result.append({'recipe_id':rid,'title':title})
            continue  # Never restore labels deliberately removed later by Admin.
        connection=repo.connect()
        try:
            pairs=[('dish_type','non_alcoholic','Đồ uống không cồn'),('diet','vegetarian','Chay')]
            pairs += [('weather',w,{'hot':'Nóng','cold':'Lạnh','rain':'Mưa','sunny':'Nắng'}[w]) for w in weather]
            pairs += [('occasion',o,label) for o,label in [('daily','Hằng ngày'),('guests','Đãi khách'),('drinking','Mồi nhậu')]]
            for group,key,label in pairs:
                tags=_query(connection,'SELECT tag_id,deleted_at FROM recipe_tags WHERE tag_type=%s AND code=%s',(group,key))
                if tags:
                    if tags[0]['deleted_at'] is not None:
                        continue  # Respect Admin deletion; never silently restore a tag.
                    tid=tags[0]['tag_id']
                else:
                    _,tid=_write(connection,'INSERT INTO recipe_tags(tag_type,code,label,normalized_label,description) VALUES(%s,%s,%s,%s,%s)',
                        (group,key,label,_norm(label),'Danh mục đồ uống tham khảo Đợt 4; không xác nhận định lượng.'))
                _write(connection,'INSERT IGNORE INTO recipe_tag_links(recipe_id,tag_id) VALUES(%s,%s)',(rid,tid))
            connection.commit()
        except Exception:
            connection.rollback();raise
        finally:
            connection.close()
        result.append({'recipe_id':rid,'title':title})
    return result
