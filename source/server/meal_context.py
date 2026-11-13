"""Metadata-based meal advice and explicit custom selections; no name inference."""
from collections import Counter
from source.common.protocol import ProtocolError
from source.server import meal_plan_v2 as planner
from source.server.meal_plan import build_shopping_lists, default_classification
from source.server.meal_plan_calculation import calculate, validate as calculation_options

WEATHER = {'hot':'Nóng', 'cold':'Lạnh', 'rain':'Mưa', 'sunny':'Nắng'}
METHODS = {'steam':'hấp','boil':'luộc','salad':'gỏi/trộn','braise':'kho/rim',
           'grill':'nướng','roast':'rang','fry':'chiên','stir_fry':'xào','stew':'hầm'}
WEIGHTS = {'hot':{'steam':3,'boil':3,'salad':4,'fry':-2},
           'cold':{'braise':4,'stew':4,'boil':2,'salad':-1},
           'rain':{'braise':3,'steam':2,'stew':2,'grill':-1},
           'sunny':{'salad':3,'steam':2,'boil':2,'fry':-1}}


def weather_score(tags, weather):
    if weather not in WEATHER:
        return 0, []
    reasons=[]
    score=0
    if weather in tags.get('weather', ()):
        score+=6
        reasons.append('Admin phân loại phù hợp thời tiết '+WEATHER[weather].lower())
    for method in sorted(tags.get('cooking_method', ())):
        value=WEIGHTS[weather].get(method,0)
        score+=value
        if value>0:
            reasons.append('Ưu tiên cách '+METHODS.get(method,method)+' khi '+WEATHER[weather].lower())
    return score,reasons


def _materialize(repository, connection, result, selected):
    if result['plan']:
        details=[repository.get_recipe(connection,i['recipe_id']) for i in result['plan']['items']]
        result['plan'].update(build_shopping_lists(details,selected))
    return result


def assess(repository, connection, payload, request_id, version):
    allowed={'request','query','propose','add_recipe_id','remove_slot','adults','children'}
    if not isinstance(payload,dict) or set(payload)-allowed or not isinstance(payload.get('request'),dict):
        raise ProtocolError('INVALID_PAYLOAD','invalid meal assessment request',request_id)
    query=payload.get('query','')
    if not isinstance(query,str) or len(query)>80 or type(payload.get('propose',False)) is not bool:
        raise ProtocolError('INVALID_PAYLOAD','invalid meal assessment options',request_id)
    request=dict(payload['request'])
    if request.get('adaptive_daily') is True and ('adults' in payload or 'children' in payload):
        request.update(adults=payload.get('adults'),children=payload.get('children'))
    options=planner.validate(request,request_id)
    if not repository.ingredient_ids_exist(connection, options.filters.selected|options.filters.excluded):
        raise ProtocolError('INVALID_PAYLOAD','unknown ingredient',request_id)
    recipes=(repository.unified.recipes_for_ranking(connection,include_drinks=True)
             if getattr(repository,"unified_catalog_mode",False) else repository.recipes_for_ranking(connection))
    by_id={r['id']:r for r in recipes}
    classification=repository.meal_classification_for_connection(connection,default_classification())
    catalog=repository.meal_preference_catalog(connection,recipes,classification)
    tags=repository.meal_pairing_metadata(connection,list(by_id))
    current=dict(options.current)
    locks=set(options.locked)
    if any(rid not in by_id for rid in current.values()):
        raise ProtocolError('INVALID_PAYLOAD','unknown recipe',request_id)
    if 'add_recipe_id' in payload or 'remove_slot' in payload:
        if options.layout_mode!='custom':
            raise ProtocolError('INVALID_PAYLOAD','manual changes require custom layout',request_id)
        if 'add_recipe_id' in payload:
            rid=payload['add_recipe_id']
            if type(rid) is not int or rid not in by_id or rid in current.values() or len(current)>=6:
                raise ProtocolError('INVALID_PAYLOAD','cannot add this recipe',request_id)
            role=classification.categories.get(rid)
            if role not in planner.SLOTS:
                raise ProtocolError('INVALID_PAYLOAD','unsupported custom recipe role',request_id)
            index=1+sum(k.startswith(role+':') for k in current)
            current[f'{role}:{index}']=rid
        else:
            target=payload['remove_slot']
            if not isinstance(target,str) or target not in current or target in locks or len(current)<=1:
                raise ProtocolError('INVALID_PAYLOAD','cannot remove this slot; unpin it first',request_id)
            del current[target]
            rebuilt={};new_locks=set()
            for group in planner.SLOTS:
                for index,(key,rid) in enumerate(((k,v) for k,v in current.items() if k.startswith(group+':')),1):
                    new=f'{group}:{index}';rebuilt[new]=rid
                    if key in locks:new_locks.add(new)
            current,locks=rebuilt,new_locks
        request.update(current_plan=current,locked_slots=sorted(locks),counts={g:sum(k.startswith(g+':') for k in current) for g in planner.SLOTS})
        options=planner.validate(request,request_id)
    # Reuse the planner's authoritative hard filters, including strict vegetarian
    # evidence, recipe roles, exclusions, meat requirement and region.
    forced={**request,'current_plan':current,'locked_slots':list(current),'action':'generate'}
    forced.pop('replace_slot',None);forced.pop('avoid_recipe_ids',None)
    checked=planner.generate(recipes,planner.validate(forced,request_id),classification,request_id,catalog,pairing_metadata=tags,
        **({"daily_catalog":repository.calculation_catalog(connection,list(by_id))} if options.adaptive_daily else {}))
    checked=_materialize(repository,connection,checked,options.filters.selected)
    checked['dataset_version']=version
    ids=list(current.values())
    primary=Counter(code for rid in ids for code in tags.get(rid,{}).get('main_ingredient',()))
    methods=Counter(code for rid in ids for code in tags.get(rid,{}).get('cooking_method',()))
    warnings=[];reasons=[]
    if not checked['plan']:
        warnings.append(checked['reason']['message'])
    repeated=[k for k,n in primary.items() if n>1]
    primary_labels={}
    if repeated and getattr(repository,'unified_catalog_mode',False):
        from source.database.unified_catalog_migration import _query
        primary_labels={r['code']:r['label'] for r in _query(connection,"SELECT code,label FROM recipe_tags WHERE tag_type='main_ingredient' AND deleted_at IS NULL")}
    if repeated:warnings.append('Trùng nhãn nguyên liệu chính: '+', '.join(primary_labels.get(k,k) for k in repeated))
    elif primary:reasons.append('Không lặp nhãn nguyên liệu chính đã biết trong mâm.')
    repeated_methods=[METHODS.get(k,k) for k,n in methods.items() if n>1]
    if repeated_methods:warnings.append('Lặp cách chế biến: '+', '.join(repeated_methods))
    elif methods:reasons.append('Các phương pháp chế biến đã biết không lặp nhau.')
    if any(k in methods for k in ('fry','braise')) and any(k in methods for k in ('boil','steam','salad')):
        reasons.append('Có cách chiên/kho kết hợp hấp/luộc/gỏi theo metadata; chưa suy ra lượng dầu hay giá trị dinh dưỡng.')
    missing_tags=sum(not tags.get(rid,{}).get('main_ingredient') or not tags.get(rid,{}).get('cooking_method') for rid in ids)
    if missing_tags:warnings.append(f'{missing_tags} món thiếu nhãn nguyên liệu chính hoặc cách nấu; chưa thể đánh giá đầy đủ độ đa dạng.')
    roles=[classification.categories.get(rid) for rid in ids]
    occasion=options.preferences.get('occasion','daily')
    if 'vegetable' not in roles and occasion!='drinking':warnings.append('Mâm chưa có món rau riêng.')
    if 'soup' not in roles and occasion!='drinking':warnings.append('Mâm chưa có canh/lẩu; cân nhắc bổ sung nếu phù hợp.')
    if 'soup' in roles and any(r in roles for r in ('main','vegetable')):reasons.append('Có món canh/lẩu kết hợp các món còn lại; chưa khẳng định độ khô/ướt của từng món thiếu metadata.')
    if options.layout_mode=='custom':reasons.append('Mâm do bạn tự chọn; hệ thống kiểm tra điều kiện bắt buộc, cấu trúc và khẩu phần theo dữ liệu hiện có.')
    elif occasion=='drinking':reasons.append('Mồi nhậu ưu tiên món dùng chung; không yêu cầu canh. Khẩu phần dùng chính sách Mồi nhậu.')
    elif occasion=='guests':reasons.append('Đãi khách dùng cấu trúc khai vị, món chính, rau và canh theo số người khi ghép tự động.')
    else:reasons.append('Hằng ngày ưu tiên kết hợp món chính, rau và canh theo số người.')
    item_reasons=[]
    for key,rid in current.items():
        score,why=weather_score(tags.get(rid,{}),options.weather)
        role_label={'main':'món chính','vegetable':'món rau','soup':'canh/lẩu','side':'ăn kèm'}.get(classification.categories.get(rid))
        if role_label:why.append('Vai trò trong dữ liệu Admin: '+role_label+'.')
        if by_id[rid].get('portion_ready'):why.append('Có cấu trúc định lượng dùng được; độ tin cậy nguồn được hiển thị riêng.')
        known_primary=tags.get(rid,{}).get('main_ingredient',())
        if known_primary and all(primary[code]==1 for code in known_primary):
            why.append('Các nhãn nguyên liệu chính đã biết của món này không lặp trong mâm.')
        item_reasons.append({'slot':key,'recipe_id':rid,'title':by_id[rid]['title'],'weather_score':score,'reasons':why})
    if options.weather:
        count=sum(i['weather_score']>0 for i in item_reasons)
        reasons.append(f'{count}/{len(ids)} món có tín hiệu ưu tiên cho thời tiết {WEATHER[options.weather].lower()}; thời tiết không loại món bắt buộc.')
    calculation=None
    if ids:
        cp={'recipe_ids':ids,'people':options.people or 4,'occasion':occasion}
        if 'adults' in payload or 'children' in payload:cp.update(adults=payload.get('adults'),children=payload.get('children'))
        if options.adaptive_daily:
            from source.server.daily_demo_portions import calculate_daily
            cp['layout_mode']='automatic'
            calculation=calculate_daily(calculation_options(cp,request_id),repository.calculation_catalog(connection,ids),tags)
        else:
            calculation=calculate(calculation_options(cp,request_id),repository.calculation_catalog(connection,ids))
        if calculation['totals_complete']:reasons.append('Tính được lượng nguyên liệu theo phân bổ khẩu phần; xem riêng nhãn xác minh/ước tính/cần duyệt.')
        else:
            issues=[by_id[r['recipe_id']]['title']+': '+(r['reasons'][0]['message'] if r['reasons'] else 'thiếu dữ liệu')
                    for r in calculation['recipes'] if r['status']!='COMPLETE']
            warnings.append('Chưa tính đủ khẩu phần: '+'; '.join(issues))
    candidates=[]
    for r in recipes:
        role=classification.categories.get(r['id'])
        if role not in planner.SLOTS or r['id'] in ids or query.casefold() not in r['title'].casefold():continue
        if set(r['all_ids'])&options.filters.excluded:continue
        if options.filters.max_minutes and r['minutes']>options.filters.max_minutes:continue
        if options.preferences.get('diet')=='vegetarian' and r['id'] not in catalog.vegetarian_ids:continue
        if any(r['id'] not in catalog.eligible_ids(k,v) for k,v in options.preferences.items() if k in ('region','occasion')):continue
        candidates.append({'recipe_id':r['id'],'title':r['title'],'role':role,'portion_ready':bool(r.get('portion_ready'))})
    candidates.sort(key=lambda r:(not r['portion_ready'],r['title']))
    proposal=None;proposal_reasons=[]
    if payload.get('propose'):
        counts=dict(options.counts)
        # Offer missing basic groups when there is room; never remove a pin.
        for group in ('vegetable','soup','main'):
            if not counts[group]:
                if sum(counts.values())>=6:
                    donor=next((g for g in sorted(counts,key=lambda g:-counts[g])
                                if counts[g]>1 and f'{g}:{counts[g]}' not in locks),None)
                    if donor:counts[donor]-=1
                if sum(counts.values())<6:counts[group]=1
        pr={**request,'counts':counts,'layout_mode':'custom','current_plan':current,'locked_slots':sorted(locks),'action':'generate'}
        if options.adaptive_daily:
            # Daily suggestions must remain qualified fixed-layout combos;
            # never route them through Custom's allocation/selection policy.
            from source.server.daily_meal_recommendation import required_counts
            pr.update(counts=required_counts(options.people or 4),layout_mode='automatic',action='regenerate')
            if options.adults is not None:
                pr.update(adults=options.adults,children=options.children)
        pr.pop('replace_slot',None);pr.pop('avoid_recipe_ids',None)
        proposal=planner.generate(recipes,planner.validate(pr,request_id),classification,request_id,catalog,pairing_metadata=tags,
            **({'daily_catalog':repository.calculation_catalog(connection,list(by_id))} if options.adaptive_daily else {}))
        if proposal['plan'] and {i['slot']:i['recipe_id'] for i in proposal['plan']['items']}==current:
            proposal=planner.no_plan(proposal,'NO_IMPROVEMENT','Chưa tìm được phương án cải thiện giữ nguyên các món ghim và điều kiện bắt buộc.')
        if proposal['plan'] and not options.adaptive_daily:
            def quality(recipe_ids,valid):
                rr=[classification.categories.get(rid) for rid in recipe_ids]
                pp=[code for rid in recipe_ids for code in tags.get(rid,{}).get('main_ingredient',())]
                mm=[code for rid in recipe_ids for code in tags.get(rid,{}).get('cooking_method',())]
                return (int(not valid),sum(g not in rr for g in planner.SLOTS),len(pp)-len(set(pp)),
                        len(mm)-len(set(mm)),sum(not tags.get(rid,{}).get('main_ingredient') or not tags.get(rid,{}).get('cooking_method') for rid in recipe_ids),
                        sum(not by_id[rid].get('portion_ready',False) for rid in recipe_ids),
                        -sum(weather_score(tags.get(rid,{}),options.weather)[0] for rid in recipe_ids))
            before=quality(ids,checked['plan'] is not None)
            after=quality([i['recipe_id'] for i in proposal['plan']['items']],True)
            if after>=before:
                proposal=planner.no_plan(proposal,'NO_IMPROVEMENT','Chưa tìm được đề xuất cải thiện rõ ràng theo metadata và điều kiện hiện tại; giữ nguyên mâm.')
            else:
                labels=['Đáp ứng lại điều kiện bắt buộc.','Bổ sung nhóm món còn thiếu.',
                        'Giảm trùng nhãn nguyên liệu chính.','Giảm lặp phương pháp chế biến.',
                        'Giảm số món thiếu metadata phối món.','Giảm số món thiếu định lượng dùng được.',
                        'Tăng mức phù hợp thời tiết theo metadata.']
                proposal_reasons=[label for index,label in enumerate(labels) if after[index]<before[index]]
        proposal=_materialize(repository,connection,proposal,options.filters.selected)
        proposal['dataset_version']=version
    drinks=[]
    if getattr(repository,'unified_catalog_mode',False):
        seasonal_drinks=options.layout_mode=='automatic' and occasion=='daily' and options.season!='ALL'
        drink_metadata=repository.beverage_metadata(connection,[r['id'] for r in recipes if classification.categories.get(r['id'])=='drink']) if seasonal_drinks else {}
        for r in recipes:
            rid=r['id']
            if classification.categories.get(rid)!='drink' or set(r['all_ids'])&options.filters.excluded:continue
            dt=tags.get(rid,{})
            if 'non_alcoholic' not in dt.get('dish_type',()):continue
            if options.preferences.get('diet')=='vegetarian':
                if catalog.vegetarian_assessments.get(rid,{}).get('status')!='VERIFIED':continue
            score,why=weather_score(dt,options.weather)
            if occasion in dt.get('occasion',()):score+=2;why.append('Admin phân loại phù hợp kiểu mâm đã chọn.')
            if any(method in methods for method in ('fry','stir_fry')) and 'hot' in dt.get('weather',()) and options.weather!='cold':
                score+=2
                why.append('Mâm có món chiên/xào; gợi ý đồ uống mát theo phân loại Admin, tùy khẩu vị.')
            if any(set(tags.get(food,{}).get('dish_type',())) & {'spicy','oily'} for food in ids) and 'hot' in dt.get('weather',()) and options.weather!='cold':
                score+=2
                why.append('Mâm có nhãn cay/nhiều dầu do Admin quản lý; ưu tiên đồ uống mát theo khẩu vị.')
            if occasion=='drinking':why.append('Đồ uống không cồn dùng chung; không tính vào số món hoặc lượng thức ăn.')
            if seasonal_drinks:
                from source.server.beverages import seasonal_score
                extra,season_why=seasonal_score(drink_metadata.get(rid,{}),options.season)
                score+=extra
                why=season_why+why
            drinks.append({'recipe_id':rid,'title':r['title'],'score':score,'reason':' '.join(why) or 'Đồ uống không cồn dùng chung; chưa có định lượng phục vụ được xác minh.',
                           'people':options.people or 4,'amount':None,'quantity_note':'Chỉ gợi ý; chưa có định lượng đồ uống được xác minh.'})
        drinks.sort(key=lambda d:(-d['score'],d['recipe_id']))
    # Keep this advisory response below the TCP frame budget. Ingredient amounts
    # remain in CALCULATE_MEAL_PLAN; only explicit edits need a full selected plan.
    if calculation:
        calculation={k:calculation[k] for k in ('status','totals_complete','portion_groups')}
    if 'add_recipe_id' not in payload and 'remove_slot' not in payload and checked['plan']:
        checked={**checked,'plan':{'items':checked['plan']['items']}}
    # Small groups get one suggestion; larger groups get two alternatives.
    # This is a presentation policy, not an invented beverage volume.
    drink_limit=1 if (options.people or 4)<=3 else 2
    return {'dataset_version':version,'selection':checked,'locked_slots':sorted(locks),
            'reasons':reasons,'warnings':warnings,'items':item_reasons,'beverages':drinks[:drink_limit],
            'candidates':candidates[:20],'proposal':proposal,'proposal_reasons':proposal_reasons,'calculation':calculation}
