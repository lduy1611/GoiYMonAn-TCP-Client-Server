"""Daily-only SOFT ranking for a teaching demo, not verified crop seasons.

Signals come from existing ingredient identities, Admin cooking tags, roles,
or explicit cooking words in recipe titles when tags are absent. Never write
tags back, change weather, relax filters, or calculate/scale food quantities.
ALL deliberately contributes nothing and emits no new response fields.
"""
import re
import unicodedata

SEASONS = ('ALL', 'SPRING', 'SUMMER', 'AUTUMN', 'WINTER')
LABELS = dict(zip(SEASONS, ('Tất cả mùa', 'Xuân', 'Hạ', 'Thu', 'Đông')))
METHODS = {
    'SPRING': {'steam': 3, 'boil': 2, 'salad': 1, 'fry': -1},
    'SUMMER': {'boil': 3, 'steam': 2, 'salad': 2, 'fry': -2, 'roast': -1},
    'AUTUMN': {'braise': 3, 'steam': 2, 'stew': 1},
    'WINTER': {'stew': 4, 'braise': 3, 'boil': 1, 'salad': -1},
}
METHOD_LABELS = {'steam': 'hấp', 'boil': 'luộc/nấu', 'salad': 'gỏi/trộn',
                 'fry': 'chiên', 'roast': 'nướng/rang', 'braise': 'kho', 'stew': 'hầm',
                 'stir_fry': 'xào'}
INGREDIENTS = {
    'SPRING': {'cai thao', 'cai xanh', 'cai ngong', 'cai thia', 'dau que', 'sup lo'},
    'SUMMER': {'bau', 'bi dao', 'kho qua', 'mong toi', 'rau day', 'rau muong', 'ca chua'},
    'AUTUMN': {'bi do', 'hat sen', 'nam huong', 'nam rom', 'nam bao ngu', 'cu cai trang', 'ca rot'},
    'WINTER': {'suon heo', 'thit bo', 'cu cai trang', 'khoai tay', 'cai thao', 'nam huong'},
}
# Only a fallback for missing cooking tags; words are matched with boundaries.
TITLE_METHODS = {'hấp': 'steam', 'luộc': 'boil', 'hầm': 'stew', 'kho': 'braise',
                 'chiên': 'fry', 'nướng': 'roast', 'rang': 'roast', 'gỏi': 'salad',
                 'xào': 'stir_fry'}


def cooking_methods(title, tags=None):
    """Admin tags win. Preserve Vietnamese tones for lexical cooking words.

    Accent folding is appropriate for ingredient identity, not for distinguishing
    kho (braise), khô (dried) and khổ (bitter). Ambiguous ASCII titles do not
    establish braising; no instruction/yield inference is introduced here.
    """
    methods = set((tags or {}).get('cooking_method', ()))
    if methods:
        return methods
    title = unicodedata.normalize('NFC', (title or '').casefold())
    result = {code for word, code in TITLE_METHODS.items()
              if re.search(r'\b'+word+r'\b', title)}
    if title.isascii():
        result.discard('braise')
    return result


def standalone_meal(title):
    """A leading dish phrase, not an ingredient substring or a broth name."""
    return bool(re.match(r'^(?:com|bun|mien|chao|pho|banh canh)\b', normalized(title)))


def normalized(value):
    value = unicodedata.normalize('NFD', (value or '').casefold().replace('đ', 'd'))
    return re.sub(r'\s+', ' ', ''.join(c for c in value if unicodedata.category(c) != 'Mn')).strip()


def evaluate(recipe, revision, tags, season):
    """Explainable integer priority. Zero/negative is allowed, never excluded."""
    if season == 'ALL':
        return {'recipe_id': recipe['id'], 'score': 0, 'reasons': [], 'standalone': False}
    methods = cooking_methods(recipe.get('title'), tags)
    source = 'phân loại cách nấu'
    if not (tags or {}).get('cooking_method'):
        source = 'cách nấu trong tên món'
    score = 0
    reasons = []
    for method in sorted(methods):
        points = METHODS[season].get(method, 0)
        score += points
        if points:
            reasons.append(('Ưu tiên ' if points > 0 else 'Ít ưu tiên ')+METHOD_LABELS[method]+' theo '+source+'.')
    lines = revision.lines if revision else ()
    matched = sorted({line.name for line in lines if line.requirement != 'optional'
                      and line.purpose not in {'seasoning', 'garnish', 'cooking_medium'}
                      and normalized(line.name) in INGREDIENTS[season]})
    if matched:
        score += min(3, len(matched))
        reasons.append('Có '+', '.join(matched)+', thuộc nhóm nguyên liệu ưu tiên thử nghiệm mùa '+LABELS[season]+'.')
    role = revision.role if revision else recipe.get('role')
    standalone = standalone_meal(recipe.get('title'))
    # Soup alone is not evidence of a summer/winter characteristic. Require
    # the existing ingredient signals, or an explicit warming winter method.
    soup_signal = bool(matched) or season == 'WINTER' and bool(methods & {'stew', 'braise'})
    if role == 'soup' and not standalone and season in {'SUMMER', 'WINTER'} and soup_signal:
        score += 1
        reasons.append('Canh có tín hiệu nguyên liệu/cách nấu ưu tiên thử nghiệm mùa '+LABELS[season]+'.')
    if standalone:
        reasons.append('Món ăn riêng/thay bữa: ít ưu tiên ghép với mâm cơm truyền thống; vẫn giữ ngữ cảnh khẩu phần riêng.')
    if not reasons:
        reasons.append('Chưa có tín hiệu ưu tiên mùa từ dữ liệu hiện có; có thể dùng như món trung tính.')
    return {'recipe_id': recipe['id'], 'score': score, 'reasons': reasons, 'standalone': standalone}


def assessment(items, season, locked_ids=()):
    matched = sum(item['score'] > 0 for item in items)
    neutral = len(items)-matched
    pinned = sum(item['recipe_id'] in locked_ids and item['score'] <= 0 for item in items)
    summary = f'Mùa {LABELS[season]}: {matched}/{len(items)} món có tín hiệu ưu tiên theo quy tắc demo.'
    if neutral:
        summary += f' Dùng thêm {neutral} món chưa có tín hiệu ưu tiên để giữ cơ cấu, bộ lọc và khẩu phần.'
    if pinned:
        summary += f' Giữ {pinned} món ghim dù chưa hợp ưu tiên mùa.'
    if any(item['standalone'] for item in items):
        summary += ' Có món ăn riêng; không coi suất món này như món ăn kèm cơm.'
    return {'season': season, 'score': sum(item['score'] for item in items),
            'matched_count': matched, 'neutral_count': neutral, 'summary': summary, 'items': items}
