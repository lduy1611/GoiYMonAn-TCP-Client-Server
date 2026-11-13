"""Controlled academic reference data, independent of meal allocation targets.

Dry-run creates an auditable per-recipe plan. Apply only that reviewed plan in
one transaction, checking all original values. No engine reference is imported.
"""
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP
from statistics import median
import argparse
import hashlib
import json
from pathlib import Path
import re
import unicodedata
import mysql.connector

VERSION='academic-reference-20261112-v1'
D=Decimal


def fold(value):
    return ''.join(c for c in unicodedata.normalize('NFD',str(value or '').lower().replace('đ','d')) if unicodedata.category(c)!='Mn')


def number(value):
    return format(D(value).quantize(D('.001'),rounding=ROUND_HALF_UP).normalize(),'f')


def explicit_amount(text):
    units={'muong ca phe':'tsp','thia ca phe':'tsp','muong canh':'tbsp','thia canh':'tbsp',
           'kg':'kg','g':'g','ml':'ml','lit':'l','tep':'clove','nhanh':'stalk','cay':'stalk',
           'bo':'bunch','la':'leaf','con':'piece','qua':'piece','trai':'piece','cai':'piece',
           'bia':'piece','xap':'source_stack','chen':'source_bowl','muong':'source_spoon'}
    match=re.match(r'^(\d+/\d+|\d+(?:[.,]\d+)?)\s*('+ '|'.join(sorted(units,key=len,reverse=True))+r')\b',fold(text))
    if not match:return None
    raw=match[1].replace(',','.')
    if '/' in raw:
        a,b=raw.split('/')
        if D(b)==0:return None
        value=D(a)/D(b)
    else:value=D(raw)
    return value,units[match[2]]


def reasonable_peer(unit,value,group,text):
    """Wide simulation sanity bounds; not nutritional recommendations.

    In particular do not borrow a deep-frying oil bath for coating a pan, or
    a large cleaning-alcohol bath for a small cooking seasoning quantity.
    """
    t=fold(text)
    mass_caps={'salt':5,'pepper':2,'dry-spice':5,'seasoning-powder':5,'sugar':50,
               'aromatic':20,'root-aromatic':20,'chilli':10,'fresh-herb':30,
               'nut-topping':40,'wood-ear':30}
    if unit in ('g','kg'):
        return 0<value*(1000 if unit=='kg' else 1)<=mass_caps.get(group,400)
    if unit in ('ml','l'):
        cap=600
        if group=='cooking-fat':cap=15 if any(k in t for k in ('trang chao','chong dinh','phi')) else 200
        elif group in ('seasoning-sauce','acid-or-cooking-liquid'):cap=25 if group=='seasoning-sauce' else 20
        elif group=='coconut-liquid':cap=200
        return 0<value*(1000 if unit=='l' else 1)<=cap
    return 0<value<={'tsp':4,'tbsp':5,'piece':30,'clove':6,'stalk':6,'bunch':2,'leaf':30,'cup':3}.get(unit,8)


def profile(name, role, text=''):
    """Fallback amounts per source serving, not per engine meal target.

    Explicitly hypothetical cooking inputs, not nutrition standards. Peers take
    precedence. Distinct profiles keep salt, herbs, staples and protein apart.
    """
    n=fold(name);t=fold(text)
    if n in ('nuoc loc','nuoc nong','nuoc soi','nuoc lanh'):return ('main' if role=='soup' else 'cooking_medium'),'ml',D(300 if role=='soup' else 80),'water'
    if 'dau an' in n or n in ('dau dieu','mo heo','bo'):return 'cooking_medium','ml',D(35 if 'chien ngap' in t else 5),'cooking-fat'
    if 'muoi'==n:return 'seasoning','g',D('.6'),'salt'
    if 'tieu' in n:return 'seasoning','g',D('.2'),'pepper'
    if any(k in n for k in ('hat nem','bot nem','bot ngot')):return 'seasoning','g',D('.7'),'seasoning-powder'
    if 'duong' in n:return 'seasoning','g',D(8 if role=='other' else 2),'sugar'
    if any(k in n for k in ('nuoc mam','nuoc tuong','dau hao','tuong ot','tuong ca','mam nem','mam ruoc','mam tom','tuong ban')):return 'seasoning','ml',D(5),'seasoning-sauce'
    if n in ('chanh','tac'):return 'seasoning','piece',D('.25'),'citrus-count'
    if n in ('toi','hanh tim','hanh tam','cu nen','hanh phi','bot toi'):return 'seasoning','g',D(3),'aromatic'
    if n in ('gung','rieng','nghe tuoi','bot nghe'):return 'seasoning','g',D(3),'root-aromatic'
    if n=='sa':return 'seasoning','stalk',D('.5'),'lemongrass-count'
    if n in ('ot','ot bot','sa te'):return 'seasoning','g',D(1),'chilli'
    if n in ('que','hoa hoi','vo quyt','ngu vi huong'):return 'seasoning','g',D('.4'),'dry-spice'
    if n in ('giam trang','giam bong','ruou trang','nuoc cot chanh','nuoc hang'):return 'seasoning','ml',D(4),'acid-or-cooking-liquid'
    if n=='me':return 'seasoning','g',D(8),'tamarind'
    if n in ('hanh','hanh la','rau ram','rau thom','ngo ri','ngo gai','thi la','rau om','rau song an kem','la dua'):
        return 'garnish','g',D(5),'fresh-herb'
    if n in ('rau song','rau an lau'):return 'garnish','g',D(40),'accompanying-greens'
    if n=='la lot':return 'main','leaf',D(5),'wrapping-leaves'
    if 'banh trang' in n or n=='banh da nem':return 'main','piece',D(3),'rice-paper-count'
    if 'trung' in n:return 'main','piece',D(2 if 'cut' in n else '.5'),'egg-count'
    if n in ('bun','bun tuoi','banh pho','mi quang','banh da'):return 'main','g',D(130),'cooked-or-ready-staple'
    if any(k in n for k in ('gao','bot gao','bot mi','bot nang','bot chien','bot bap','mien','bot bang')):return 'main','g',D(40),'dry-staple'
    if n=='dau phong':return 'garnish','g',D(8),'nut-topping'
    if n in ('nuoc cot dua','nuoc dua'):return 'cooking_medium','ml',D(40),'coconut-liquid'
    if n in ('nam meo','nam meo kho'):return 'main','g',D(5),'wood-ear'
    if n=='dau xanh':return 'main','g',D(30),'dry-legume'
    # Remaining ingredients with no missing quantity still use peer purpose.
    if any(k in n for k in ('thit','ca ','tom','muc','suon','cua','dau phu')):return 'main','g',D(100),'protein'
    return 'main','g',D(60),'vegetable-or-other'


def basis(line):
    n=fold(line['name']);form=fold(line.get('ingredient_form'))
    if any(k in form for k in ('chien','rang','nuong','phi thom','ngam no')) or n in ('bun','bun tuoi','banh pho','hanh phi','banh mi chien','cha lua','cha chay','thinh gao'):
        return 'prepared','ingredient is ready/cooked, or form explicitly fried/roasted/rehydrated'
    if any(k in form for k in ('boc vo','bo chi','da lam sach','thit oc')):
        return 'edible','form explicitly describes cleaned edible component'
    return 'gross','hypothesis: source ingredient input before preparation; no yield conversion'


def snapshot(connection):
    cur=connection.cursor(dictionary=True)
    try:
        cur.execute("SELECT * FROM recipes WHERE is_public=1 AND deleted_at IS NULL AND role!='drink' ORDER BY recipe_id")
        recipes=cur.fetchall()
        cur.execute("""SELECT i.*,g.name,u.code FROM recipe_ingredients i JOIN ingredients g USING(ingredient_id)
            JOIN recipes r USING(recipe_id) LEFT JOIN units u USING(unit_id)
            WHERE r.is_public=1 AND r.deleted_at IS NULL AND r.role!='drink' ORDER BY i.recipe_id,i.line_no""")
        lines=cur.fetchall()
        cur.execute('SELECT unit_id,code FROM units')
        units={r['code']:r['unit_id'] for r in cur.fetchall()}
        return recipes,lines,units
    finally:cur.close()


def make_plan(connection):
    recipes,lines,units=snapshot(connection)
    headers={r['recipe_id']:r for r in recipes};grouped=defaultdict(list)
    peers=defaultdict(list);purposes=defaultdict(list)
    for line in lines:
        grouped[line['recipe_id']].append(line)
        r=headers[line['recipe_id']]
        if line['purpose']!='unknown':purposes[line['ingredient_id']].append(line['purpose'])
        if r['servings'] and line['amount_min'] and line['code'] and line['amount_kind']=='exact':
            peers[line['ingredient_id']].append((r['recipe_id'],r['role'],line['purpose'],line['code'],line['amount_min']/r['servings']))
    plan={'version':VERSION,'catalog_size':len(recipes),'recipes':[]}
    for r in recipes:
        updates=[];reasons=[]
        base=r['servings']
        if not base:
            refs=[x for x in recipes if x['role']==r['role'] and x['servings']]
            base=D(str(median([x['servings'] for x in refs]))) if refs else D(4)
            reasons.append({'field':'servings','before':None,'after':number(base),'rule':'median existing same-role source servings; academic assumption',
                            'reference_recipe_ids':[x['recipe_id'] for x in refs]})
        for line in grouped[r['recipe_id']]:
            new={};why=[];p,default_unit,default_amount,group=profile(line['name'],r['role'],line['quantity_text'])
            purpose=line['purpose']
            if purpose=='unknown':
                # Explicit seasonings always stay separate from food drivers.
                purpose=p if p!='main' else Counter(purposes[line['ingredient_id']]).most_common(1)[0][0] if purposes[line['ingredient_id']] else p
                new['purpose']=purpose;why.append('purpose profile: '+group)
            if purpose=='garnish' and group=='cooked-or-ready-staple':
                default_unit,default_amount,group='piece' if fold(line['name'])=='banh da' else 'g',D(1 if fold(line['name'])=='banh da' else 30),'accompanying-staple'
            if line['measurement_basis']=='unknown':
                new['measurement_basis'],reason=basis(line);why.append(reason)
            if line['scaling_mode']=='unknown':new['scaling_mode']='linear';why.append('academic linear recipe scaling, not a yield coefficient')
            if line['amount_min'] is None:
                explicit=explicit_amount(line['quantity_text'])
                candidates=[v for v in peers[line['ingredient_id']] if v[0]!=r['recipe_id'] and v[2]==purpose]
                candidates=[v for v in candidates if reasonable_peer(v[3],v[4],group,line['quantity_text'])]
                same_role=[v for v in candidates if v[1]==r['role']]
                if len(same_role)>=2:candidates=same_role
                if explicit:
                    value,unit=explicit
                    why.append('explicit source quantity prefix retained; descriptive units are not converted to mass/volume')
                elif candidates:
                    unit=Counter(v[3] for v in candidates).most_common(1)[0][0]
                    candidates=[v for v in candidates if v[3]==unit]
                    # Source peer units remain native: never turn a piece into grams.
                    value=D(str(median(v[4] for v in candidates)))*base
                    why.append('same ingredient/purpose peer median per source serving; refs '+','.join(str(v[0]) for v in candidates))
                else:
                    unit=default_unit;value=default_amount*base
                    why.append('academic cooking-input profile '+group+'; '+str(default_amount)+' '+unit+' per assumed source serving')
                # A pre-existing unit is authoritative; do not overwrite it.
                if line['unit_id'] is not None and line['code']!=unit:
                    raise ValueError('existing unit conflict; manual review required: '+str((r['recipe_id'],line['line_no'])))
                if value<=0 or not value.is_finite():raise ValueError('invalid reference amount')
                new.update(amount_kind='exact',amount_min=number(value),amount_max=number(value))
                if line['unit_id'] is None:new['unit_id']=units.get(unit,'code:'+unit)
            if new:
                updates.append({'line_no':line['line_no'],'ingredient_id':line['ingredient_id'],'ingredient':line['name'],
                    'quantity_text':line['quantity_text'],'before':{k:line[k] for k in new},'after':new,'basis':why})
        if updates or reasons:
            if r['portion_data_status']=='verified':
                raise ValueError('verified recipe needs manual review: '+str(r['recipe_id']))
            plan['recipes'].append({'recipe_id':r['recipe_id'],'title':r['title'],'expected_edit_version':r['edit_version'],
                'servings_before':r['servings'],'servings_after':number(base),'servings_basis':reasons,'lines':updates})
    return json.loads(json.dumps(plan,ensure_ascii=False,default=str))


def apply_plan(connection,plan):
    if plan.get('version')!=VERSION:raise ValueError('unsupported plan version')
    cur=connection.cursor(dictionary=True);changed=[]
    try:
        for item in plan['recipes']:
            rid=item['recipe_id']
            cur.execute('SELECT * FROM recipes WHERE recipe_id=%s FOR UPDATE',(rid,));r=cur.fetchone()
            marker=VERSION+':'+str(rid)
            if marker in (r['portion_data_evidence'] or ''):continue
            if r['role']=='drink' or not r['is_public'] or r['deleted_at'] or r['portion_data_status']=='verified' or r['edit_version']!=int(item['expected_edit_version']):
                raise ValueError('recipe changed since preview: '+str(rid))
            if not D(item['servings_after']).is_finite() or D(item['servings_after'])<=0:
                raise ValueError('invalid reference servings')
            if r['servings'] is not None and D(item['servings_after'])!=r['servings']:raise ValueError('cannot replace source servings')
            for line in item['lines']:
                cur.execute('SELECT * FROM recipe_ingredients WHERE recipe_id=%s AND line_no=%s FOR UPDATE',(rid,line['line_no']));old=cur.fetchone()
                for key,value in line['before'].items():
                    if str(old[key])!=str(value) and old[key]!=value:raise ValueError('line changed since preview')
                keys=list(line['after'])
                if set(keys)-{'purpose','measurement_basis','scaling_mode','amount_kind','amount_min','amount_max','unit_id'} or set(keys)!=set(line['before']):
                    raise ValueError('unexpected editable field')
                values=dict(line['after'])
                for key in ('amount_min','amount_max','unit_id'):
                    if key in values and old[key] is not None:raise ValueError('cannot overwrite existing quantity/unit')
                for key in ('purpose','measurement_basis','scaling_mode'):
                    if key in values and old[key]!='unknown':raise ValueError('cannot overwrite known metadata')
                if 'amount_min' in values and (D(values['amount_min'])<=0 or D(values['amount_max'])<D(values['amount_min'])):
                    raise ValueError('invalid amount')
                if isinstance(values.get('unit_id'),str) and values['unit_id'].startswith('code:'):
                    code=values['unit_id'][5:]
                    if code not in ('source_spoon','source_bowl','source_stack'):raise ValueError('unknown descriptive unit')
                    cur.execute('SELECT unit_id FROM units WHERE code=%s',(code,));unit=cur.fetchone()
                    if unit:values['unit_id']=unit['unit_id']
                    else:
                        cur.execute("INSERT INTO units(code,name,dimension) VALUES(%s,%s,'other')",(code,'Source descriptive '+code[7:]+'; no mass/volume conversion'))
                        values['unit_id']=cur.lastrowid
                cur.execute('UPDATE recipe_ingredients SET '+','.join(k+'=%s' for k in keys)+' WHERE recipe_id=%s AND line_no=%s',
                    (*[values[k] for k in keys],rid,line['line_no']))
            evidence=(marker+' | Academic simulation only; not independently verified or nutritional advice. '
                'Missing amounts use same-ingredient/purpose peer medians per source serving, else distinct cooking-input profiles. '
                'Only missing fields filled; native units and existing numbers retained. No meal-engine targets or invented yields. '
                'Per-line assumptions and reference recipe IDs: report '+plan.get('report_name','preview JSON')+'.')
            # Append previous provenance within the API evidence limit.
            evidence=(evidence+' Previous: '+(r['portion_data_evidence'] or ''))[:2000]
            cur.execute("UPDATE recipes SET servings=%s,portion_data_status='estimated',portion_data_evidence=%s,edit_version=edit_version+1 WHERE recipe_id=%s",
                (item['servings_after'],evidence,rid))
            changed.append(rid)
        return changed
    finally:cur.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True)
    parser.add_argument('--report',required=True,type=Path)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9_]+_test',args.database):parser.error('TEST_ONLY schema required')
    connection=mysql.connector.connect(host='127.0.0.1',port=63900,user='root',password='',database=args.database,charset='utf8mb4')
    try:
        if args.apply:
            plan=json.loads(args.report.read_text(encoding='utf-8'));print('Applied',len(apply_plan(connection,plan)));connection.commit()
        else:
            if args.report.exists():raise ValueError('refusing to overwrite an existing review report')
            plan=make_plan(connection);plan['report_name']=args.report.name
            args.report.write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
            print('Preview',len(plan['recipes']),'recipes;',sum(len(r['lines']) for r in plan['recipes']),'ingredient lines')
    except Exception:
        connection.rollback();raise
    finally:connection.close()
