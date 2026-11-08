"""Stable JSON-safe public IDs. Legacy UINT32 IDs retain their exact values."""
UINT32_MAX = 2**32 - 1
V2_OFFSET = 2**32
MAX_PUBLIC_ID = V2_OFFSET + UINT32_MAX


def valid_public_id(value):
    return type(value) is int and (1 <= value <= UINT32_MAX or V2_OFFSET < value <= MAX_PUBLIC_ID)


def v2_public_id(value):
    if type(value) is not int or not 1 <= value <= UINT32_MAX:
        raise ValueError("v2 identity must fit UINT32 for the public catalog")
    return V2_OFFSET + value


def member_id(member):
    legacy = member.get("legacy_recipe_id")
    return legacy if legacy is not None else v2_public_id(member["recipe_id"])
