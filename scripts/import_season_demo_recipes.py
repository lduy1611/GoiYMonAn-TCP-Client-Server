"""Additive, reviewed academic demo batch. Never changes an existing recipe.

Quantities describe newly authored original batches, not allocations or yields.
All are estimates requiring Admin review. Unknown source servings stay NULL.
The CLI requires an identity-checked backup and a successful private rehearsal.
"""
import argparse
import datetime as dt
from decimal import Decimal
import difflib
import hashlib
import json
from pathlib import Path
import re
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from source.database.unified_catalog_migration import _norm
from source.server.daily_seasons import normalized

BATCH='season-demo-20261113-v1'
TABLES=('recipes','recipe_ingredients','recipe_steps','recipe_tags','recipe_tag_links')
EXPECTED_DB='goiy_v3_quality_final_20261110_test'

# Main food amounts are transparent authoring estimates from ingredient-level
# peers in the existing catalog. Links support technique/composition, not a
# claim that these adapted batches or serving counts were independently tested.
UNIE='https://unie.vn/blog/huong-dan-cach-lam-mon-thit-lon-hap-nam-la-mieng-thom-ngon'
FISH='https://monngonmoingay.com/ca-hap-mong-toi/'
TUNA='https://www.cet.edu.vn/cach-lam-ca-ngu-kho'
LOTUS='https://vnhow.vn/howto/cach-nau-dau-hu-nhoi-hat-sen'
CHICKEN='https://naungon.com/index.php?id=-thuc-don-ga-om-nam-bi-dao-nhoi-~-thuc-don-nau-an-mon-ngon-&pageindex=1&q=nau+an+mon+ngon'
BEEF='https://www.monngon.edu.vn/bo-xao-cai-thao-554'
EGGPLANT='https://dev.tailieu.vn/doc/ca-tim-hap-toi-bam-1370123.html'
RADISH='https://quangduc.com/images/file/OjFrTF6O0wgQAIF5/van-hoa-phat-giao-so-138-ngay-01-10-2011.pdf'

def item(title,role,season,method,foods,steps,minutes,primary=(),source=None,notes=''):
    lines=[{'name':name,'amount':str(amount),'unit':'g','purpose':'main',
            'basis':basis,'form':form} for name,amount,basis,form in foods]
    vegan=not any(normalized(x['name']) in {'thit heo xay','thit ga','thit bo','ca basa','ca ngu','tom','tom kho'} for x in lines)
    lines += [{'name':'Muối','amount':'0.5','unit':'g','purpose':'seasoning','basis':'gross','form':None},
              {'name':'Gừng' if method in ('steam','stew') or re.search(r'\bgung\b',normalized(title)) else 'Tỏi','amount':'3','unit':'g','purpose':'seasoning','basis':'gross','form':None}]
    if role=='soup':lines.append({'name':'Nước lọc','amount':str(400 if sum(float(x['amount']) for x in lines)<250 else 900),'unit':'ml','purpose':'cooking_medium','basis':'gross','form':None})
    else:lines.append({'name':'Nước tương' if vegan else 'Nước mắm','amount':'5','unit':'ml','purpose':'seasoning','basis':'gross','form':None})
    if method in ('stir_fry','braise'):lines.append({'name':'Dầu ăn','amount':'5','unit':'ml','purpose':'cooking_medium','basis':'gross','form':None})
    return dict(title=title,role=role,season=season,method=method,lines=lines,steps=steps,
                minutes=minutes,primary=list(primary),source_url=source,vegan=vegan,notes=notes)

def manifest():
    G='gross';E='edible';R='Nguyên liệu tươi, cân trước khi nấu'
    return [
      item('Thịt heo hấp nấm hương','main','spring','steam', [('Thịt heo xay',250,G,R),('Nấm hương',30,G,'Nấm hương tươi')],
           ['Trộn thịt với nấm thái nhỏ, gừng băm và gia vị đã cân; dàn vào đĩa chịu nhiệt.', 'Hấp từ khi nước sôi đến khi thịt chín hoàn toàn, kiểm tra phần giữa; dùng nóng.'],30,['pork'],UNIE,'Mẻ mới 250 g thịt; nguồn kỹ thuật dùng 180 g thịt/2 người, không sao chép số suất của nguồn.'),
      item('Cá basa hấp cải thìa','main','spring','steam',[('Cá basa',350,E,'Phi lê đã bỏ xương, cân phần ăn được'),('Cải thìa',100,G,R)],
           ['Rửa, để ráo cải; thấm khô phi lê, ướp gừng và gia vị.', 'Xếp cải và cá vào đĩa, hấp chín hoàn toàn; dùng cùng nước hấp.'],30,['fish'],FISH,'Biến thể cá basa/cải thìa; nguồn dùng cá chim/mồng tơi. Khối lượng là ước tính tác giả, không giả danh nguyên bản.'),
      item('Tôm rim cà chua','main','summer','braise',[('Tôm',300,E,'Tôm bóc vỏ bỏ đầu, cân phần ăn được'),('Cà chua',180,G,R)],
           ['Băm tỏi, cắt cà chua, làm sạch và để ráo tôm.', 'Phi tỏi với dầu, nấu cà chua mềm; thêm tôm và gia vị, rim đến khi tôm chín và xốt sánh.'],25,['shrimp'],'https://xaydungso.vn/blog/huong-dan-cach-lam-tom-rim-ca-chua-ngon-mien-che-tai-nha-vi-cb.html','Giữ 300 g tôm tham khảo; phần tôm cân sau bóc vỏ. Cà chua được cân bằng gam ước tính thay số quả, không gán số suất.'),
      item('Đậu hũ nhồi hạt sen','main','autumn','braise',[('Đậu phụ',300,G,R),('Hạt sen',50,G,'Hạt sen tươi bỏ tâm'),('Nấm hương',30,G,'Nấm hương tươi'),('Cà chua',120,G,R)],
           ['Luộc hạt sen mềm, nghiền một phần; trộn với ruột đậu và nấm băm rồi nhồi lại.', 'Làm xốt cà chua với gia vị, cho đậu nhồi vào rim nhẹ đến khi nóng chín đều.'],40,['tofu'],LOTUS,'Bản thích nghi dùng nấm tươi thay nấm khô, không quy đổi số tai nấm thành gam giả.'),
      item('Gà om nấm cà rốt','main','autumn','stew',[('Thịt gà',800,E,'Thịt gà đã bỏ xương, cân phần ăn được'),('Nấm hương',200,G,'Nấm hương tươi'),('Cà rốt',200,G,R)],
           ['Cắt gà và cà rốt vừa ăn; làm sạch nấm, ướp gà với gừng và gia vị.', 'Cho 300 ml nước lọc, om gà cùng cà rốt và nấm đến chín mềm, không để cạn.'],55,['chicken'],CHICKEN,'Mẻ lớn thích nghi từ gà om nấm, các lượng đã thiết kế lại và cần duyệt.'),
      item('Cá ngừ kho cà chua','main','summer','braise',[('Cá ngừ',500,G,'Cá cắt khúc còn xương, cân nguyên liệu sống'),('Cà chua',240,G,R)],
           ['Làm sạch cá, cắt cà chua, ướp cá với gia vị.', 'Nấu mềm cà chua với tỏi và dầu; thêm cá và 150 ml nước, kho nhẹ đến chín và xốt sánh.'],40,['fish'],TUNA,'Giữ 500 g cá của nguồn; cà chua cân ước tính thay đơn vị quả. Không mượn số suất nguồn khác.'),
      item('Bò xào cải thảo','main','winter','stir_fry',[('Thịt bò',600,G,R),('Cải thảo',1000,G,R),('Hành tây',200,G,R)],
           ['Thái bò mỏng, cắt cải và hành tây, ướp bò với gia vị.', 'Xào bò chín, để riêng; xào cải và hành tây, cho bò trở lại đảo đều đến chín hoàn toàn.'],30,['beef'],BEEF,'Mẻ gốc lớn gấp đôi lượng 300/500/100 g của nguồn, không scale theo người tại runtime.'),
      item('Cải ngồng luộc gừng','vegetable','spring','boil',[('Cải ngồng',120,G,R)],
           ['Nhặt rửa cải ngồng, cắt vừa ăn.', 'Đun 600 ml nước với gừng và muối, luộc cải chín tới, vớt ráo; nước luộc không phải nguyên liệu ăn của món.'],15,notes='Đối chiếu kỹ thuật luộc từ Rau muống luộc chấm tương Bần trong catalog; mẻ nhỏ 120 g là ước tính tác giả.'),
      item('Bí đao luộc chấm tương','vegetable','summer','boil',[('Bí đao',100,G,R)],
           ['Gọt vỏ, bỏ ruột bí đao rồi thái miếng.', 'Luộc trong 400 ml nước đến chín, vớt ráo; dùng cùng phần nước tương đã cân.'],15,notes='Kỹ thuật luộc và nêm từ Rau củ luộc chấm nước tương; nguyên liệu bí đao từ canh bí đao hiện có.'),
      item('Củ cải trắng hấp nấm rơm','vegetable','autumn','steam',[('Củ cải trắng',300,G,R),('Nấm rơm',150,G,R)],
           ['Gọt củ cải, thái lát; làm sạch nấm, xếp vào đĩa.', 'Thêm gừng và gia vị, hấp đến khi củ cải và nấm chín; dùng nóng.'],25,source=RADISH,notes='Thích nghi kỹ thuật củ cải hấp, thay nấm khô bằng nấm rơm tươi; không coi lượng này là nguyên bản nguồn.'),
      item('Cà tím hấp tỏi gừng','vegetable','spring','steam',[('Cà tím',250,G,R)],
           ['Cắt cà tím thành thanh, xếp vào đĩa chịu nhiệt.', 'Hấp chín; thêm 3 g tỏi băm, gừng và nước tương đã cân, hấp tiếp cho tỏi chín.'],25,source=EGGPLANT,notes='Nguồn nêu 3 quả; mẻ 250 g cân sống là ước tính riêng, không đổi 3 quả thành 250 g.'),
      item('Cải thảo xào gừng','vegetable','winter','stir_fry',[('Cải thảo',500,G,R)],
           ['Rửa và thái cải thảo, thái gừng sợi.', 'Phi thơm gừng với dầu, xào cải với gia vị đến chín, dùng nóng.'],20,notes='Biến thể rau thuần chay dựa trên cải thảo trong catalog và kỹ thuật xào của nguồn bò xào cải thảo; bỏ thịt, không dùng nước mắm.'),
      item('Canh đậu que thịt bằm','soup','spring','boil',[('Đậu que',100,G,R),('Thịt heo xay',50,G,R)],
           ['Tước xơ, thái đậu que; trộn thịt với gia vị.', 'Đun nước, cho thịt vào khuấy tơi và nấu chín, thêm đậu que nấu chín mềm.'],20,['pork'],notes='Đậu que từ món đậu que hiện có; phương pháp canh thịt bằm từ canh bí đỏ thịt bằm. Mẻ nhỏ là thiết kế ước tính, không có số suất xác minh.'),
      item('Canh bầu tôm khô','soup','summer','boil',[('Bầu',120,G,R),('Tôm khô',10,G,'Tôm khô, cân trước ngâm')],
           ['Gọt bầu, thái sợi; ngâm và giã nhẹ tôm khô.', 'Đun nước cùng tôm, cho bầu vào nấu chín, nêm phần muối và tỏi đã cân.'],20,['shrimp'],notes='Đối chiếu bầu/tôm khô và canh cải ngồng tôm khô hiện có; mẻ nhỏ được khai báo ước tính.'),
      item('Canh mồng tơi tôm','soup','summer','boil',[('Mồng tơi',100,G,R),('Tôm',50,E,'Tôm đã bóc vỏ bỏ đầu, cân phần ăn được')],
           ['Nhặt rửa mồng tơi; làm sạch và băm tôm.', 'Đun nước, nấu tôm chín rồi thêm rau, nấu chín rau và nêm gia vị.'],20,['shrimp'],notes='Thích nghi canh cua rau đay mồng tơi và canh bí đao tôm hiện có; thay đạm được công khai, không giả danh công thức nguồn.'),
      item('Canh bí đỏ hạt sen','soup','autumn','stew',[('Bí đỏ',200,G,R),('Hạt sen',100,G,'Hạt sen tươi bỏ tâm')],
           ['Bỏ vỏ và hạt bí, cắt miếng; rửa hạt sen.', 'Hầm hạt sen trong nước đến gần mềm, thêm bí đỏ và gia vị, nấu đến chín mềm.'],40,source='https://fptshop.com.vn/tin-tuc/dien-may/canh-bi-do-hat-sen-162272',notes='Biến thể chay bỏ đạm động vật, giảm bí so với nguồn; các thay đổi và gia vị đều ước tính.'),
      item('Canh củ cải hầm bò','soup','winter','stew',[('Củ cải trắng',400,G,R),('Thịt bò',250,G,R)],
           ['Thái bò và củ cải vừa ăn, làm sạch gừng.', 'Hầm bò trong nước đến gần mềm, thêm củ cải và gia vị, tiếp tục nấu chín mềm.'],65,['beef'],source='https://monanngon.vn/category/cong-thuc/mon-canh/',notes='Nguồn nêu 300 g bò và 2 củ cải; mẻ cân 250/400 g được thiết kế lại, không quy đổi số củ hoặc sao chép số suất.'),
    ]

def query(c,sql,args=()):
    cur=c.cursor(dictionary=True)
    try:cur.execute(sql,args);return cur.fetchall() if cur.with_rows else []
    finally:cur.close()

def digest(rows):
    return hashlib.sha256(json.dumps(sorted(json.dumps(r,sort_keys=True,default=str) for r in rows)).encode()).hexdigest()

def snapshot(c):
    tables=[next(iter(r.values())) for r in query(c,'SHOW TABLES')]
    return {t:query(c,'SELECT * FROM `'+t+'`') for t in tables}

def signatures(data):return {t:{'count':len(rows),'sha256':digest(rows)} for t,rows in data.items()}

def encode(v):
    if isinstance(v,Decimal):return {'decimal':str(v)}
    if isinstance(v,(dt.datetime,dt.date)):return {'datetime':v.isoformat()}
    raise TypeError(type(v))

def decode(v):
    if set(v)=={'decimal'}:return Decimal(v['decimal'])
    if set(v)=={'datetime'}:return dt.datetime.fromisoformat(v['datetime'])
    return v

def insert_rows(c,table,rows):
    if not rows:return
    fields=list(rows[0]);cur=c.cursor()
    try:cur.executemany('INSERT INTO `'+table+'` ('+','.join('`'+k+'`' for k in fields)+') VALUES ('+','.join(['%s']*len(fields))+')',[tuple(r[k] for k in fields) for r in rows])
    finally:cur.close()

def prepare(c):
    all_rows=snapshot(c)
    active={}
    for row in sorted(all_rows['ingredients'],key=lambda x:int(x['ingredient_id'])):
        if row['is_active']:active.setdefault(normalized(row['name']),row)
    units={r['code']:r['unit_id'] for r in all_rows['units']}
    existing={normalized(r['title']):r for r in all_rows['recipes']}
    plans=[]
    for index,m in enumerate(manifest()):
        key=str(uuid.uuid5(uuid.NAMESPACE_URL,BATCH+':'+m['title']))
        if normalized(m['title']) in existing and existing[normalized(m['title'])].get('create_request_key')!=key:
            raise ValueError('Duplicate title: '+m['title'])
        evidence=[]
        for line in m['lines']:
            i=active.get(normalized(line['name']))
            if i is None:raise ValueError('No active ingredient: '+line['name'])
            line['ingredient_id']=int(i['ingredient_id']);line['unit_id']=units[line['unit']]
            assert Decimal(line['amount'])>0 and line['basis'] in {'gross','edible','prepared'}
            peers=[r for r in all_rows['recipe_ingredients'] if r['ingredient_id']==i['ingredient_id'] and r['unit_id']==line['unit_id'] and r['amount_min'] is not None]
            evidence.append({'ingredient':line['name'],'amount':line['amount'],'unit':line['unit'],'basis':line['basis'],
                'peer_recipe_ids':sorted({int(r['recipe_id']) for r in peers})[:8],
                'claim':'AUTHOR_ESTIMATE; peer ingredient scale/composition reference, not independently verified'})
        # Explicit recipe-specific water/garlic used in instructions must be in shopping.
        extra=[]
        if m['title']=='Gà om nấm cà rốt':extra=[('Nước lọc','300','ml','cooking_medium')]
        if m['title']=='Cá ngừ kho cà chua':extra=[('Nước lọc','150','ml','cooking_medium')]
        if m['title']=='Cà tím hấp tỏi gừng':extra=[('Tỏi','3','g','seasoning')]
        if m['role']=='vegetable' and m['method']=='boil':extra=[('Nước lọc','600' if index==7 else '400','ml','cooking_medium')]
        for name,amount,unit,purpose in extra:
            m['lines'].append(dict(name=name,amount=amount,unit=unit,purpose=purpose,basis='gross',form=None,ingredient_id=int(active[normalized(name)]['ingredient_id']),unit_id=units[unit]))
        for aromatic in ('gừng','tỏi'):
            if any(re.search(r'\b'+aromatic+r'\b',text.casefold()) for text in [m['title'],*m['steps']]):
                assert any(normalized(l['name'])==normalized(aromatic) for l in m['lines']), 'Instruction ingredient missing: '+m['title']
        foods={l['ingredient_id'] for l in m['lines'] if l['purpose']=='main'}
        near=[]
        for old in all_rows['recipes']:
            ratio=difflib.SequenceMatcher(None,normalized(m['title']),normalized(old['title'])).ratio()
            if ratio>=.70:near.append({'id':old['recipe_id'],'title':old['title'],'name_similarity':round(ratio,3)})
            oldfoods={int(l['ingredient_id']) for l in all_rows['recipe_ingredients'] if l['recipe_id']==old['recipe_id'] and l['purpose']=='main' and l['ingredient_id'] in {int(i['ingredient_id']) for i in active.values() if normalized(i['name']) not in {'toi','gung','hanh la','nuoc loc','nuoc mam','nuoc tuong','duong','muoi','dau an','hat nem','hanh tim'}}}
            old_methods={t['code'] for t in all_rows['recipe_tags'] if t['tag_type']=='cooking_method' and any(l['recipe_id']==old['recipe_id'] and l['tag_id']==t['tag_id'] for l in all_rows['recipe_tag_links'])}
            if old['role']==m['role'] and oldfoods==foods and m['method'] in old_methods and old.get('create_request_key')!=key:
                raise ValueError('Near identical composition/method: '+m['title']+' / '+old['title'])
        m.update(key=key,evidence=evidence,near_titles=near,servings=None)
        m['payload_hash']=hashlib.sha256(json.dumps(m,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        plans.append(m)
    return plans,all_rows

def apply(c,plans,fail_after=None):
    """Caller owns transaction. Insert only; old tags and recipes never updated."""
    result=[]
    for index,p in enumerate(plans):
        prior=query(c,'SELECT recipe_id,create_payload_hash FROM recipes WHERE create_request_key=%s',(p['key'],))
        if prior:
            if prior[0]['create_payload_hash']!=p['payload_hash']:raise ValueError('Idempotency content mismatch')
            result.append(int(prior[0]['recipe_id']));continue
        if query(c,'SELECT recipe_id FROM recipes WHERE normalized_title=%s',(_norm(p['title']),)):raise ValueError('Duplicate title')
        rid=int(query(c,'SELECT COALESCE(MAX(recipe_id),4294967296)+1 AS n FROM recipes')[0]['n'])
        evidence=json.dumps({'batch':BATCH,'status':'ESTIMATED_NEEDS_ADMIN_REVIEW','servings':'unknown; NULL, no invented serving count',
            'source':p['source_url'] or 'Existing catalog ingredient peers; authored technique',
            'adaptation':p['notes'],'lines':[{'name':e['ingredient'],'amount':e['amount'],'unit':e['unit'],'peers':e['peer_recipe_ids'][:2]} for e in p['evidence']],
            'claim':'All adapted quantities/seasonings are author estimates; not independently verified. Full evidence in batch plan.json.'},ensure_ascii=False,separators=(',',':'))
        assert len(evidence)<=2000,'Evidence exceeds existing Admin/API contract'
        desc='ƯỚC TÍNH — cần Admin duyệt. Mẻ gốc riêng, không điều chỉnh theo số người. '+p['notes']
        query(c,"""INSERT INTO recipes(recipe_id,title,normalized_title,description,role,minutes_total,minutes_prep,minutes_cook,
            servings,portion_data_status,portion_data_evidence,instructions_legacy,source_url,is_public,create_request_key,create_payload_hash)
            VALUES(%s,%s,%s,%s,%s,%s,10,%s,NULL,'estimated',%s,%s,%s,1,%s,%s)""",
            (rid,p['title'],_norm(p['title']),desc,p['role'],p['minutes'],p['minutes']-10,evidence,'\n'.join(p['steps']),p['source_url'],p['key'],p['payload_hash']))
        for n,l in enumerate(p['lines'],1):
            query(c,"""INSERT INTO recipe_ingredients(recipe_id,line_no,ingredient_id,quantity_text,amount_kind,amount_min,amount_max,unit_id,
                requirement,purpose,ingredient_form,measurement_basis,scaling_mode) VALUES(%s,%s,%s,%s,'exact',%s,%s,%s,'required',%s,%s,%s,'linear')""",
                (rid,n,l['ingredient_id'],l['amount']+' '+l['unit'],l['amount'],l['amount'],l['unit_id'],l['purpose'],l['form'],l['basis']))
        for n,s in enumerate(p['steps'],1):query(c,'INSERT INTO recipe_steps(recipe_id,step_no,instruction) VALUES(%s,%s,%s)',(rid,n,s))
        tags=[('occasion','daily','Hằng ngày'),('dish_type',p['role'],{'main':'Món chính','vegetable':'Món rau','soup':'Món canh'}[p['role']]),
              ('cooking_method',p['method'],{'steam':'Hấp','boil':'Luộc','stew':'Hầm','braise':'Kho / rim','stir_fry':'Xào'}[p['method']]),
              ('season',p['season'],{'spring':'Xuân','summer':'Hè','autumn':'Thu','winter':'Đông'}[p['season']])]
        tags += [('main_ingredient',code,code) for code in p['primary']]
        if p['vegan']:tags.append(('diet','vegetarian','Chay'))
        for kind,code,label in tags:
            existing=query(c,'SELECT tag_id,deleted_at FROM recipe_tags WHERE tag_type=%s AND code=%s',(kind,code))
            if existing:
                if existing[0]['deleted_at'] is not None:raise ValueError('Refuse restoring deleted tag')
                tid=existing[0]['tag_id']
            else:
                query(c,'INSERT INTO recipe_tags(tag_type,code,label,normalized_label) VALUES(%s,%s,%s,%s)',(kind,code,label,_norm(label)))
                tid=query(c,'SELECT tag_id FROM recipe_tags WHERE tag_type=%s AND code=%s',(kind,code))[0]['tag_id']
            query(c,'INSERT INTO recipe_tag_links(recipe_id,tag_id) VALUES(%s,%s)',(rid,tid))
        result.append(rid)
        if fail_after is not None and index+1==fail_after:raise RuntimeError('TEST_ONLY injected failure before commit')
    return result

def verify_additive(c,baseline,ids):
    after=snapshot(c)
    for t,rows in baseline.items():
        if t not in TABLES:
            assert digest(rows)==digest(after[t]),'Unrelated table changed: '+t
        else:
            original={json.dumps(r,sort_keys=True,default=str) for r in rows}
            assert original <= {json.dumps(r,sort_keys=True,default=str) for r in after[t]},'Old row changed: '+t
    for rid in ids:
        assert query(c,'SELECT COUNT(*) n FROM recipe_ingredients WHERE recipe_id=%s',(rid,))[0]['n']>=4
    return after

def rollback_batch(c,plans,baseline,expected_after):
    """Fail closed after later edits; delete only this batch, never old rows."""
    assert signatures(snapshot(c))==signatures(expected_after),'Later changes exist; manual review required'
    ids=[]
    for p in plans:
        row=query(c,'SELECT recipe_id,create_payload_hash,edit_version FROM recipes WHERE create_request_key=%s',(p['key'],))
        assert len(row)==1 and row[0]['create_payload_hash']==p['payload_hash'] and row[0]['edit_version']==1
        ids.append(int(row[0]['recipe_id']))
    marks=','.join(['%s']*len(ids))
    for t in ('recipe_tag_links','recipe_steps','recipe_ingredients','recipes'):
        query(c,'DELETE FROM `'+t+'` WHERE recipe_id IN ('+marks+')',tuple(ids))
    old_tags={r['tag_id'] for r in baseline['recipe_tags']}
    for tag in expected_after['recipe_tags']:
        if tag['tag_id'] not in old_tags:
            assert not query(c,'SELECT recipe_id FROM recipe_tag_links WHERE tag_id=%s',(tag['tag_id'],))
            query(c,'DELETE FROM recipe_tags WHERE tag_id=%s',(tag['tag_id'],))
    assert signatures(snapshot(c))==signatures(baseline)
    return ids

def verify_demo(c):
    r=query(c,'SELECT @@port port,@@datadir datadir,DATABASE() db')[0]
    from scripts.run_demo import DATADIR
    assert r['port']==63900 and r['db']==EXPECTED_DB and Path(r['datadir']).resolve()==DATADIR.resolve(),r
    engines=query(c,'SELECT TABLE_NAME,ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()')
    assert all(r['ENGINE']=='InnoDB' for r in engines)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','apply','rollback']);parser.add_argument('--directory',required=True);args=parser.parse_args()
    from scripts.run_demo import mysql_connect
    directory=Path(args.directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    c=mysql_connect(EXPECTED_DB)
    try:
        verify_demo(c);c.rollback();c.start_transaction(readonly=args.mode=='prepare')
        if args.mode=='prepare':
            plans,rows=prepare(c)
            backup={'batch':BATCH,'identity':EXPECTED_DB,'tables':{t:rows[t] for t in TABLES},'checksums':signatures(rows)}
            dest=directory/'before-backup.json'
            if dest.exists():raise RuntimeError('Refuse overwriting existing backup')
            dest.write_text(json.dumps(backup,ensure_ascii=False,indent=2,default=encode),encoding='utf-8')
            check=json.loads(dest.read_text(encoding='utf-8'),object_hook=decode)
            assert all(digest(check['tables'][t])==backup['checksums'][t]['sha256'] for t in TABLES)
            (directory/'plan.json').write_text(json.dumps(plans,ensure_ascii=False,indent=2),encoding='utf-8')
            c.rollback();print('Prepared',len(plans),'recipes; backup verified')
        elif args.mode=='rollback':
            applied=json.loads((directory/'applied.json').read_text(encoding='utf-8'))
            backup=json.loads((directory/'before-backup.json').read_text(encoding='utf-8'),object_hook=decode)
            plans=json.loads((directory/'plan.json').read_text(encoding='utf-8'))
            assert query(c,"SELECT GET_LOCK('unified_recipe_create_id_allocator',5) acquired")[0]['acquired']==1
            for t in TABLES:query(c,'SELECT * FROM `'+t+'` FOR UPDATE')
            current=snapshot(c);assert signatures(current)==applied['after'],'Later edits exist; refuse automatic rollback'
            original={**current,**backup['tables']}
            assert signatures(original)==backup['checksums']
            ids=rollback_batch(c,plans,original,current);c.commit()
            (directory/'rolled-back.json').write_text(json.dumps({'removed_only_batch_ids':ids}),encoding='utf-8')
            print('Rolled back only batch:',ids)
        else:
            proof=json.loads((directory/'rehearsal.json').read_text(encoding='utf-8'))
            raw=(directory/'plan.json').read_bytes();assert proof['plan_sha256']==hashlib.sha256(raw).hexdigest() and proof['passed']
            assert proof['script_sha256']==hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            plans=json.loads(raw);backup=json.loads((directory/'before-backup.json').read_text(encoding='utf-8'),object_hook=decode)
            assert query(c,"SELECT GET_LOCK('unified_recipe_create_id_allocator',5) acquired")[0]['acquired']==1
            if (directory/'applied.json').exists():
                prior=[]
                for p in plans:
                    row=query(c,'SELECT recipe_id,create_payload_hash FROM recipes WHERE create_request_key=%s',(p['key'],))
                    assert len(row)==1 and row[0]['create_payload_hash']==p['payload_hash'],'Previous batch changed; review required'
                    prior.append(int(row[0]['recipe_id']))
                c.rollback();print('Already applied; no writes:',prior);return
            baseline=snapshot(c);assert signatures(baseline)==backup['checksums'],'Database changed since backup; stop'
            for t in TABLES:query(c,'SELECT * FROM `'+t+'` FOR UPDATE')
            ids=apply(c,plans);after=verify_additive(c,baseline,ids)
            # Verify eligibility using the unchanged production portion model.
            from source.server.unified_repository import UnifiedMySQLRepository
            from source.server.daily_demo_portions import estimate
            repo=object.__new__(UnifiedMySQLRepository);catalog=repo.calculation_catalog(c,ids);tags=repo.meal_pairing_metadata(c,ids)
            assert all(estimate(catalog.revisions[rid],tags.get(rid))['status']=='estimated' for rid in ids)
            report={'batch':BATCH,'recipe_ids':ids,'before':signatures(baseline),'after':signatures(after),'titles':[p['title'] for p in plans]}
            (directory/'pending-commit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            c.commit()
            (directory/'applied.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print('Committed',len(ids),'recipes:',ids)
    except BaseException:c.rollback();raise
    finally:c.close()

if __name__=='__main__':main()
