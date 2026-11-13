"""Admin beverage metadata and advisory seasonal ranking, separate from food policy."""

FIELDS = ('beverage_temperature', 'beverage_light', 'is_non_alcoholic', 'is_visible')
TEMPERATURES = {'unspecified': set(), 'hot': {'serve_hot'}, 'cold': {'serve_cold'},
                'both': {'serve_hot', 'serve_cold'}}
TAG_LABELS = {'serve_hot': 'Dùng nóng', 'serve_cold': 'Dùng lạnh',
              'beverage_light': 'Vị thanh nhẹ', 'non_alcoholic': 'Không cồn'}
SEASONS = {'SPRING': 'Xuân', 'SUMMER': 'Hạ', 'AUTUMN': 'Thu', 'WINTER': 'Đông'}


def validate_settings(payload, role):
    values = {key: payload[key] for key in FIELDS if key in payload}
    if values and role != 'drink':
        raise ValueError('beverage settings are only supported for drinks')
    if 'beverage_temperature' in values:
        temp = values['beverage_temperature']
        if not isinstance(temp, str) or temp not in TEMPERATURES:
            raise ValueError('invalid beverage serving temperature')
    for key in ('beverage_light', 'is_non_alcoholic', 'is_visible'):
        if key in values and type(values[key]) is not bool:
            raise ValueError('invalid beverage boolean setting')
    return values


def tag_changes(payload):
    changes = {}
    if 'beverage_temperature' in payload:
        chosen = TEMPERATURES[payload['beverage_temperature']]
        changes.update({code: code in chosen for code in ('serve_hot', 'serve_cold')})
    for field, code in (('beverage_light', 'beverage_light'), ('is_non_alcoholic', 'non_alcoholic')):
        if field in payload:
            changes[code] = payload[field]
    return changes


def seasonal_score(tags, season):
    """Soft preferences only; never change weather, quantities or hard eligibility."""
    if season not in SEASONS:
        return 0, []
    score, reasons = 0, []
    flags = set(tags.get('dish_type', ()))
    if season.lower() in tags.get('season', ()):
        score += 8
        reasons.append('Admin phân loại phù hợp mùa ' + SEASONS[season] + '.')
    if season == 'SUMMER' and 'serve_cold' in flags:
        score += 3
        reasons.append('Có thể dùng mát theo cách pha đã lưu.')
    if season == 'WINTER' and 'serve_hot' in flags:
        score += 3
        reasons.append('Có thể dùng ấm theo cách pha đã lưu.')
    if season in ('SPRING', 'AUTUMN') and 'beverage_light' in flags:
        score += 2
        reasons.append('Vị thanh nhẹ theo mô tả Admin.')
    if not reasons:
        reasons.append('Lựa chọn bổ sung; chưa có phân loại phù hợp mùa ' + SEASONS[season] + '.')
    return score, reasons
