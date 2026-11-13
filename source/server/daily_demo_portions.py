"""DAILY DEMO ONLY -- experimental food model, NOT nutritional advice.

One original batch per recipe. No SQL writes, stock changes or recipe scaling.
Shared-meal reference: 350 g prepared edible solids/adult equivalent, of which
at least 175 g-equivalent must come from main dishes. Standalone starch meals
use a separate 500 g reference. Accept N..1.30N; surplus is never hidden.
These are configurable-in-code demo assumptions, not measured food standards.
Soup portions below mean 75 g reference portions of solids, not full bowls.
Input broth is displayed separately, never counted as edible solids or output
volume: no evaporation/density conversion is needed by this food-mass model.
All trim, cooking, hydration and count weights below are explicit assumptions.
Unknown mandatory food drivers fail closed; seasonings/oil/water are not meat.
"""
from dataclasses import replace
from fractions import Fraction as F
import re
import unicodedata

from source.server.meal_plan_calculation import calculate, _finite_decimal, _display_decimal, _number

VERSION = "daily-demo-food-v1"
SHARED_FOOD_G = F(350)
STANDALONE_FOOD_G = F(500)
MAIN_MIN_SHARE = F(1, 2)
MAX_SURPLUS = F(13, 10)
DISH_REFERENCE_G = {'main':F(175), 'vegetable':F(120), 'soup':F(75)}

# Native ingredient identity, not recipe-title substring inference.
# category -> (gross edible fraction, cooking retention by method).
PROFILES = {
    "meat": (F('.98'), {"braise":F('.75'),"roast":F('.72'),"fry":F('.72'),"boil":F('.80'),"steam":F('.85'),"unknown":F('.75')}),
    "chicken": (F('.70'), {"steam":F('.90'),"braise":F('.80'),"roast":F('.75'),"unknown":F('.80')}),
    "fish": (F('.60'), {"braise":F('.85'),"boil":F('.90'),"fry":F('.78'),"unknown":F('.85')}),
    "shrimp": (F('.55'), {"stir_fry":F('.85'),"boil":F('.90'),"unknown":F('.85')}),
    "ribs": (F('.50'), {"boil":F('.85'),"stew":F('.85'),"unknown":F('.85')}),
    "shellfish": (F('.20'), {"boil":F('.90'),"unknown":F('.90')}),
    "tofu": (F('.98'), {"steam":F('.98'),"braise":F('.95'),"unknown":F('.95')}),
    "vegetable": (F('.90'), {"boil":F('.85'),"stir_fry":F('.85'),"braise":F('.85'),"unknown":F('.85')}),
    "mushroom": (F('.95'), {"braise":F('.75'),"stir_fry":F('.75'),"unknown":F('.75')}),
    "ready_starch": (F(1), {"unknown":F(1)}),
    "dry_starch": (F(1), {"unknown":F('2.5')}),
    "dry_mushroom": (F('.95'), {"unknown":F(4)}),
    "dry_seaweed": (F('.95'), {"unknown":F(5)}),
    "dry_shrimp": (F('.95'), {"unknown":F('1.5')}),
    "egg": (F('.88'), {"unknown":F('.98')}),
    "nuts": (F('.95'), {"unknown":F('.95')}),
}

NAMES = {
    "meat":"thit ba chi|thit heo|thit heo xay|thit bo|cha chay",
    "chicken":"thit ga", "fish":"ca basa|ca chep|ca linh|ca loc|ca ngu",
    "shrimp":"tom", "ribs":"suon heo", "shellfish":"hen|cua dong",
    "tofu":"dau phu|dau hu non",
    "vegetable":"bi dao|bi do|bong sung|bong dien dien|bac ha|bau|ca chua|ca rot|ca tim|cai chua|cai ngong|cai thia|cai thao|cai xanh|cu cai trang|dua|thom|gia do|hat sen|khoai tay|kho qua|mong toi|rau muong|rau day|su su|sup lo|tao do|dau que",
    "mushroom":"nam bao ngu|nam huong|nam kim cham|nam rom|nam dui ga",
    "ready_starch":"bun tuoi", "dry_starch":"gao te|mien|bot nang",
    "dry_mushroom":"nam meo kho", "dry_seaweed":"rong bien kho",
    "dry_shrimp":"tom kho", "egg":"trung vit|trung ga", "nuts":"dau phong",
}
KINDS = {name:kind for kind,names in NAMES.items() for name in names.split('|')}
ADJUNCTS = set("muoi|duong|nuoc mam|nuoc mam chay|nuoc tuong|dau an|dau hao|dau hao chay|hat nem|hat nem chay|bot nem ga|bot ngot|nuoc hang|tieu den|tuong ot|toi|hanh tim|hanh la|hanh tay|gung|rieng|sa|que|hoa hoi|ot|tac|me|thi la|dua nao|bot bap|bot mi da dung".split('|'))
# Only these ingredient/count pairs have a DEMO mass assumption. No generic
# piece->grams conversion; unlisted food counts remain unknown.
COUNT_G = {("su su","piece"):F(250), ("ca chua","piece"):F(120),
           ("ca rot","piece"):F(120), ("dua","piece"):F(800),
           ("thom","piece"):F(800), ("dau phu","piece"):F(100),
           ("dau hu non","piece"):F(100), ("trung vit","piece"):F(70),
           ("trung ga","piece"):F(60), ("bac ha","stalk"):F(50)}


def fold(value):
    value=unicodedata.normalize('NFD',value.lower()).replace('đ','d')
    return re.sub(r'\s+',' ',''.join(c for c in value if unicodedata.category(c)!='Mn')).strip()


def estimate(revision, tags=None):
    """Convert compatible per-line measurements, then add prepared solids."""
    role=revision.role
    methods=sorted(set((tags or {}).get('cooking_method',())))
    method=methods[0] if methods else ('boil' if role=='soup' else 'unknown')
    solids=F();broth=F();drivers=[];issues=[];has_starch=False
    if not revision.content_complete or not revision.lines:issues.append('Thiếu danh sách nguyên liệu.')
    for line in revision.lines:
        name=fold(line.name or '')
        if name=='nuoc loc':
            amount=_number(line.amount_min)
            if amount is not None and line.unit in {'ml','l'}:
                broth+=amount*(1000 if line.unit=='l' else 1)
            continue
        if line.requirement=='optional' or line.purpose in {'seasoning','garnish','cooking_medium'} or name in ADJUNCTS or name=='nuoc dua':continue
        kind=KINDS.get(name)
        if kind is None:
            issues.append('Chưa có quy tắc demo cho '+(line.name or 'nguyên liệu không tên')+'.');continue
        amount=_number(line.amount_min)
        if amount is None or line.unit is None or line.measurement_basis not in {'gross','edible','prepared'}:
            issues.append('Thiếu lượng/đơn vị/cơ sở đo: '+(line.name or '')+'.');continue
        # Range uses the lower bound conservatively and is disclosed as such.
        if line.amount_kind not in {'exact','range'} or (line.amount_kind=='range' and (_number(line.amount_max) is None or _number(line.amount_max)<amount)):
            issues.append('Chưa rõ định lượng: '+line.name+'.');continue
        if line.unit in {'g','kg'}:grams=amount*(1000 if line.unit=='kg' else 1)
        elif (name,line.unit) in COUNT_G:grams=amount*COUNT_G[name,line.unit]
        else:
            issues.append('Không quy đổi được đơn vị: '+line.name+'.');continue
        if name=='nam huong' and line.ingredient_form and 'kho' in fold(line.ingredient_form):kind='dry_mushroom'
        edible,retentions=PROFILES[kind]
        # Explicit cleaned forms supersede the generic gross shell/bone guess.
        if line.ingredient_form and any(word in fold(line.ingredient_form) for word in ('boc vo','phi le','bo xuong')):edible=F(1)
        retention=retentions.get(method,retentions['unknown'])
        if line.measurement_basis=='prepared':edible=retention=F(1)
        elif line.measurement_basis=='edible':edible=F(1)
        cooked=grams*edible*retention
        solids+=cooked;has_starch=has_starch or kind in {'dry_starch','ready_starch'}
        drivers.append({'line_id':line.line_id,'name':line.name,'input_g':_finite_decimal(grams),
            'edible_fraction':_finite_decimal(edible),'cooking_factor':_finite_decimal(retention),
            'prepared_g':_finite_decimal(cooked)})
    if not drivers:issues.append('Chưa xác định được thành phần thức ăn chính.')
    context='standalone' if has_starch else 'shared'
    reference=STANDALONE_FOOD_G if has_starch else SHARED_FOOD_G
    dish_reference=STANDALONE_FOOD_G if has_starch else DISH_REFERENCE_G.get(role,SHARED_FOOD_G)
    return {'recipe_id':revision.recipe_id,'role':role,'status':'unknown' if issues else 'estimated',
        'context':context,'prepared_g':_finite_decimal(solids),'broth_ml':_finite_decimal(broth),
        'reference_g':str(reference),'dish_reference_g':str(dish_reference),
        'dish_servings':_display_decimal(solids/dish_reference) if not issues else None,'meal_equivalents':_display_decimal(solids/reference) if not issues else None,
        'source_servings':_finite_decimal(_number(revision.base_servings)) if _number(revision.base_servings) is not None else None,
        'drivers':drivers,'issues':issues}


def assess(profiles, target):
    target=F(str(target));known=bool(profiles) and all(p['status']=='estimated' for p in profiles)
    total=sum((F(p['prepared_g'])/F(p['reference_g']) for p in profiles if p['meal_equivalents'] is not None),F())
    main=sum((F(p['prepared_g'])/F(p['reference_g']) for p in profiles if p['role']=='main' and p['meal_equivalents'] is not None),F())
    status=('unknown' if not known else 'risk' if total<target or main<target*MAIN_MIN_SHARE
            else 'surplus' if total>target*MAX_SURPLUS else 'conditional')
    return {'version':VERSION,'status':status,'requested':_finite_decimal(target),
        'meal_equivalents':_display_decimal(total) if known else None,'main_equivalents':_display_decimal(main),
        'reference_g':str(SHARED_FOOD_G),'standalone_reference_g':str(STANDALONE_FOOD_G),
        'main_min_share':_finite_decimal(MAIN_MIN_SHARE),'max_surplus':_finite_decimal(MAX_SURPLUS),
        'note':'ƯỚC TÍNH theo quy tắc demo; không phải dữ liệu đã kiểm chứng hay khuyến nghị dinh dưỡng.',
        'recipes':profiles}


def calculate_daily(options, catalog, tags=None):
    """Reuse ingredient validation/merging at multiplier ONE, independently of
    source servings. Private neutral bases are plumbing, never serving claims;
    restore original bases in the response. Custom never enters this function.
    """
    revisions={rid:replace(rev,base_servings='1',serving_basis='source_servings',data_status='estimated')
               for rid,rev in catalog.revisions.items()}
    result=calculate(options,replace(catalog,revisions=revisions))
    for item in result['recipes']:
        original=catalog.revisions.get(item['recipe_id'])
        item['original_batch']=True
        if original:
            item['data_status']=original.data_status
            item['data_evidence']=original.data_evidence
        item['base_servings']=(_finite_decimal(_number(original.base_servings)) if original and _number(original.base_servings) is not None else None)
        item['target_servings']=item['base_servings']
        item['reasons']=[r for r in item['reasons'] if r['code']!='MEAL_ALLOCATION_UNAVAILABLE']
        item['status']='INCOMPLETE' if item['reasons'] else 'COMPLETE'
    result['totals_complete']=all(item['status']=='COMPLETE' for item in result['recipes'])
    result['status']='COMPLETE' if result['totals_complete'] else 'INCOMPLETE'
    result['service_assessment']=None
    result['layout_mode']='automatic'
    result['daily_demo']=assess([estimate(catalog.revisions[rid],(tags or {}).get(rid)) for rid in options.recipe_ids if rid in catalog.revisions],options.equivalent_people)
    result['policy_note']='ƯỚC TÍNH demo từ nguyên liệu gốc; mỗi món nấu đúng một công thức, không nhân/chia lượng mua.'
    result['portion_policy_version']=VERSION
    return result


def generate(recipes, options, classification, request_id, metadata, tags, catalog):
    """Reuse authoritative filtering/pins; only Daily ranking/food policy differ."""
    from source.server import meal_plan_v2 as planner
    from source.server.daily_meal_recommendation import required_counts
    from source.server import daily_seasons
    from source.server.meal_plan_calculation import validate
    counts=required_counts(options.people or 4)
    fixed=replace(options,counts=counts)
    payload={'recipe_ids':[recipes[0]['id']] if recipes else [1],'people':options.people or 4}
    if options.adults is not None:payload.update(adults=options.adults,children=options.children)
    target=validate(payload,request_id).equivalent_people
    tags={rid:dict(value) for rid,value in (tags or {}).items()}
    profiles={rid:estimate(rev,tags.get(rid)) for rid,rev in (catalog.revisions.items() if catalog and catalog.available else [])}
    seasonal = ({r['id']: daily_seasons.evaluate(r, catalog.revisions.get(r['id']) if catalog else None,
                                               tags.get(r['id']), options.season) for r in recipes}
                if options.season != 'ALL' else {})
    approved={rid for rid,p in profiles.items() if p['status']=='estimated' and p['role'] in planner.SLOTS}
    unit=10**12
    points={rid:int(F(p['prepared_g'])*(7 if p['context']=='standalone' else 10)*unit) for rid,p in profiles.items() if rid in approved}
    ceiling=lambda n:-(-n.numerator//n.denominator)
    low=ceiling(target*3500*unit);high=int(target*MAX_SURPLUS*3500*unit);main_low=ceiling(target*MAIN_MIN_SHARE*3500*unit)
    seen=set(options.combo_history)
    if options.regenerate and options.current:seen.add(planner._daily_combo_id(options.current.values()))
    found=set();search={'combos':found,'complete':True}
    adjuncts={'garlic','onion','shallot','scallion','salt','sugar','fish_sauce','water','oil','pepper','ginger'}
    for r in recipes:
        t=tags.setdefault(r['id'],{})
        t['main_ingredient']=(set(t.get('main_ingredient',()))-adjuncts)|{f'ingredient:{i}' for i in r.get('daily_prominent_ids',())}
    private=[dict(r,portion_ready=r['id'] in approved,service_capacity=profiles[r['id']]['meal_equivalents'] if r['id'] in approved else None,
                  service_capacity_status='estimated') for r in recipes]
    def qualifies(ids):
        if any(i not in points for i in ids):return False
        total=sum(points[i] for i in ids);main=sum(points[i] for i in ids if classification.categories.get(i)=='main')
        if main<main_low or not low<=total<=high:return False
        key=planner._daily_combo_id(ids);found.add(key)
        return key not in seen
    pins={options.current[k] for k in options.locked}
    def rank(ids):
        primary=[v for rid in ids for v in tags.get(rid,{}).get('main_ingredient',())]
        methods=[v for rid in ids for v in tags.get(rid,{}).get('cooking_method',())]
        error=abs(sum(points[i] for i in ids)-low)
        # Within each 5% food-distance band prefer a varied shared meal rather
        # than an almost-exact mass match made from repeated food/bowl meals.
        base = (len((set(ids)&set(options.current.values()))-pins) if options.regenerate else 0,
                sum(profiles[i]['context']=='standalone' and profiles[i]['role']=='soup' for i in ids),
                error//max(1,low//20),len(primary)-len(set(primary)),len(methods)-len(set(methods)),error)
        if not seasonal:
            return base
        # After qualification, prefer a shared meal before rotation/proximity
        # bands. Season then ranks within the same 5% band. Standalone meals
        # remain a transparent fallback; pins are never seasonal exclusions.
        return (sum(seasonal[i]['standalone'] for i in ids), base[0], base[2],
                -sum(seasonal[i]['score'] for i in ids), *base[3:])
    pools={g:sorted(points[rid] for rid in approved if classification.categories.get(rid)==g) for g in planner.SLOTS}
    medians={g:(values[len(values)//2] if values else 0) for g,values in pools.items()}
    def order(rid,key,assignment):
        filled={**assignment,key:rid};projected=sum(points.get(i,0) for i in filled.values())
        projected+=sum(max(0,counts[g]-sum(k.startswith(g+':') for k in filled))*medians[g] for g in planner.SLOTS)
        distance = abs(projected-low)
        if seasonal:
            return (seasonal[rid]['standalone'], distance//max(1,low//20), -seasonal[rid]['score'], distance)
        return distance
    def possible(assignment):
        if any(i not in points for i in assignment.values()):return False
        main=sum(points[i] for k,i in assignment.items() if k.startswith('main:'))
        if sum(k.startswith('main:') for k in assignment)==counts['main'] and main<main_low:return False
        return sum(points[i] for i in assignment.values())<=high
    result=planner._generate_fixed(private,fixed,classification,request_id,metadata,pairing_metadata=tags,
        _daily_qualification=qualifies,_daily_approved=approved,_daily_search_state=search,
        _daily_rank=rank,_daily_order=order,_daily_partial_ok=possible,_daily_limit=25000)
    result.update(adaptive_daily=True,daily_selection_policy='daily-demo-food-v1',
        daily_combo_search={'found':len(found),'complete':search['complete']},
        daily_layout_reason='ƯỚC TÍNH demo từ lượng thực phẩm sau quy đổi thử nghiệm; không dùng 4 suất mặc định. Mỗi công thức dùng một lần, giữ nguyên lượng mua. Không phải khuyến nghị dinh dưỡng.')
    if result['plan']:
        ids=[i['recipe_id'] for i in result['plan']['items']]
        if seasonal:
            result['season'] = options.season
            result['seasonal_assessment'] = daily_seasons.assessment([seasonal[i] for i in ids], options.season, pins)
        result['daily_combo_id']=planner._daily_combo_id(ids)
        if options.regenerate:
            overlap=len((set(ids)&set(options.current.values()))-pins)
            result['daily_combo_note']=f'Combo mới còn trùng {overlap} món chưa ghim trong phạm vi tìm kiếm.' if overlap else 'Combo mới không trùng món chưa ghim.'
    elif result['reason']['code'] in {'INSUFFICIENT_GROUP','CONSTRAINTS_UNSATISFIED','SEARCH_LIMIT_REACHED','NO_ALTERNATIVE'}:
        message='Chưa tìm được combo đúng cơ cấu có lượng thức ăn phù hợp theo ước tính demo: có thể thiếu, dư nhiều hoặc thiếu dữ liệu quy đổi. Không tự thay đổi lượng nấu.'
        eligible=search.get('eligible_ids',{})
        lower=0;bounded=True
        for group in planner.SLOTS:
            values=sorted(points[i] for i in set().union(*(set(v) for key,v in eligible.items() if key.startswith(group+':'))) if i in points)
            if len(values)<counts[group]:bounded=False;break
            lower+=sum(values[:counts[group]])
        if bounded and lower>high:
            minimum=f'{float(F(lower,3500*unit)):.1f}'.replace('.',',')
            message=f'Cơ cấu này dùng các công thức gốc có ít nhất khoảng {minimum} phần bữa ăn ƯỚC TÍNH, vượt mức dư cho phép cho {options.people or 4} người. Không tự giảm lượng nấu; có thể cần công thức gốc nhỏ hơn.'
        elif not search['complete']:
            message='Chưa tìm được combo phù hợp trong giới hạn 25.000 bước tìm kiếm; chưa kết luận hết ứng viên. Mâm trước được giữ riêng, không tự thay đổi lượng nấu.'
        result=planner.no_plan(result,'NO_ALTERNATIVE' if seen else 'DEMO_PORTION_UNSUITABLE',
            'Chưa tìm được combo khác phù hợp theo ước tính demo; giữ mâm trước.' if seen else
            message,
            suggestions=['Thử điều kiện khác; mỗi món vẫn dùng đúng một công thức gốc.'])
    if seasonal:
        result['season'] = options.season
    return result
