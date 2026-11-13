"""Transport schemas for flexible meal slots; business rules stay on TCP."""
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, StrictBool, StrictInt, StrictStr, model_validator
from source.web.meal_plan_contract import Contract, IDs, Name, PositiveID
from source.common.catalog_ids import valid_public_id

def _recipe_id(value: int) -> int:
    if not valid_public_id(value):
        raise ValueError("invalid public recipe ID")
    return value

RecipeID = Annotated[StrictInt, Field(gt=0), AfterValidator(_recipe_id)]
RecipeIDs = Annotated[list[RecipeID], Field(max_length=50)]
DailyComboID = Annotated[StrictStr, Field(pattern=r"^[a-f0-9]{32}$")]
DailyComboHistory = Annotated[list[DailyComboID], Field(max_length=1700)]
Season = Literal['ALL', 'SPRING', 'SUMMER', 'AUTUMN', 'WINTER']

class ShoppingUse(Contract):
    recipe_id: RecipeID
    # Admin-authored/public recipe lines may intentionally have no verified
    # quantity yet. Preserve null through the gateway; never invent an amount.
    quantity: StrictStr | None = Field(max_length=255)
    is_required: bool

Slot = Annotated[StrictStr, Field(pattern=r"^(main|vegetable|soup):[1-6]$")]


class Counts(Contract):
    main: StrictInt = Field(ge=0, le=6)
    vegetable: StrictInt = Field(ge=0, le=6)
    soup: StrictInt = Field(ge=0, le=6)


class Preferences(Contract):
    diet: Literal["non_vegetarian", "vegetarian"] | None = None
    region: Literal["north", "central", "south"] | None = None
    occasion: Literal["daily", "weekend", "guests", "birthday", "tet", "ancestral", "snack", "drinking"] | None = None


class Request(Contract):
    season: Season | None = None
    weather: Literal["hot", "cold", "rain", "sunny"] | None = None
    action: Literal["generate", "regenerate"] = "generate"
    # Omission keeps older V2 clients on the previous automatic/count policy.
    layout_mode: Literal["automatic", "custom"] = "automatic"
    adaptive_daily: bool = False
    ingredient_ids: list[PositiveID] = Field(default_factory=list, max_length=30)
    excluded_ids: list[PositiveID] = Field(default_factory=list, max_length=30)
    max_minutes: StrictInt | None = Field(default=None, ge=1, le=240)
    max_total_minutes: StrictInt | None = Field(default=None, ge=1, le=1440)
    max_missing: StrictInt | None = Field(default=None, ge=0, le=50)
    counts: Counts | None = None
    people: StrictInt | None = Field(default=None, ge=1, le=12)
    adults: StrictInt | None = Field(default=None, ge=0, le=12)
    children: StrictInt | None = Field(default=None, ge=0, le=12)
    current_plan: dict[Slot, RecipeID] = Field(default_factory=dict, max_length=7)
    locked_slots: list[Slot] = Field(default_factory=list, max_length=7)
    replace_slot: Slot | None = None
    avoid_recipe_ids: dict[Literal["main", "vegetable", "soup"], RecipeIDs] = Field(default_factory=dict)
    combo_history: DailyComboHistory | None = None
    preferences: Preferences | None = None

    @model_validator(mode="after")
    def omitted_layout_fields(self):
        if 'season' in self.model_fields_set and self.season is None:
            raise ValueError('omit season or choose one of the supported seasons')
        if self.season not in (None, 'ALL') and not self.adaptive_daily:
            raise ValueError('season preference only supports automatic daily meals')
        if any(name in self.model_fields_set and getattr(self, name) is None for name in ("counts", "people")):
            raise ValueError("omit unspecified layout fields instead of sending null")
        if (self.adults is None) != (self.children is None) or self.adults is not None and self.adults + self.children != self.people:
            raise ValueError("adult and child counts must add up to people")
        daily_previous = set(self.current_plan) == {*(f'main:{i}' for i in range(1,6)), 'vegetable:1', 'soup:1'}
        if not self.adaptive_daily and not daily_previous and (len(self.current_plan) > 6 or len(self.locked_slots) > 6):
            raise ValueError("legacy layouts allow at most six current dishes")
        if self.counts is not None:
            values = self.counts.model_dump()
            total = sum(values.values())
            occasion = self.preferences.occasion if self.preferences else None
            max_per_group = 6 if self.layout_mode == "custom" else 5 if self.adaptive_daily else 4 if occasion in ("guests", "drinking") else 2
            if not 1 <= total <= (7 if self.adaptive_daily else 6) or any(value > max_per_group for value in values.values()):
                raise ValueError("invalid dish count for layout mode")
        if self.adaptive_daily and (self.layout_mode != "automatic" or (self.preferences and self.preferences.occasion not in (None, "daily"))):
            raise ValueError("adaptive_daily only supports automatic daily meals")
        if self.combo_history is not None and (
                not self.adaptive_daily or len(set(self.combo_history)) != len(self.combo_history)):
            raise ValueError("combo history is only valid for adaptive daily meals and must be unique")
        return self


class Item(Contract):
    slot: Slot
    recipe_id: RecipeID
    title: Name
    minutes: StrictInt = Field(ge=1, le=240)
    matched_ids: IDs
    missing_ids: IDs
    missing_count: StrictInt = Field(ge=0, le=50)


class ShoppingItem(Contract):
    ingredient_id: PositiveID
    name: Name
    uses: list[ShoppingUse] = Field(min_length=1, max_length=7)


class Plan(Contract):
    items: list[Item] = Field(min_length=1, max_length=7)
    required_ids: IDs
    matched_ids: IDs
    missing_ids: IDs
    missing_count: StrictInt = Field(ge=0, le=50)
    total_minutes: StrictInt = Field(ge=1, le=1680)
    time_basis: Literal["sum_of_recipe_minutes"]
    shopping_list: list[ShoppingItem] = Field(max_length=50)
    optional_shopping_list: list[ShoppingItem] = Field(max_length=50)
    optional_missing_ids: IDs


class Shortage(Contract):
    group: Literal["main", "vegetable", "soup"]
    requested: StrictInt = Field(ge=0, le=6)
    available: StrictInt = Field(ge=0)


class Reason(Contract):
    code: StrictStr = Field(min_length=1, max_length=80)
    message: StrictStr = Field(min_length=1, max_length=500)
    slots: list[Slot] = Field(max_length=7)
    groups: list[Shortage] = Field(max_length=3)
    suggestions: list[Name] = Field(max_length=3)


class DailyComboSearch(Contract):
    found: StrictInt = Field(ge=0, le=1_000_000)
    complete: StrictBool


class SeasonalItem(Contract):
    recipe_id: RecipeID
    score: StrictInt = Field(ge=-20, le=30)
    reasons: list[StrictStr] = Field(min_length=1, max_length=20)
    standalone: StrictBool


class SeasonalAssessment(Contract):
    season: Season
    score: StrictInt = Field(ge=-140, le=210)
    matched_count: StrictInt = Field(ge=0, le=7)
    neutral_count: StrictInt = Field(ge=0, le=7)
    summary: StrictStr = Field(min_length=1, max_length=1000)
    items: list[SeasonalItem] = Field(min_length=1, max_length=7)


class Data(Contract):
    season: Season = 'ALL'
    seasonal_assessment: SeasonalAssessment | None = None
    daily_selection_policy: Literal["qualified-servings-v1", "daily-demo-food-v1"] | None = None
    weather: Literal["hot", "cold", "rain", "sunny"] | None = None
    dataset_version: Name
    classification_version: Name
    algorithm: Literal["meal-plan-v2"]
    layout_mode: Literal["automatic", "custom"] = "automatic"
    adaptive_daily: bool = False
    daily_layout_reason: StrictStr | None = Field(default=None, max_length=500)
    daily_combo_id: DailyComboID | None = None
    daily_combo_search: DailyComboSearch | None = None
    daily_combo_note: StrictStr | None = Field(default=None, max_length=500)
    counts: Counts
    plan: Plan | None
    # A layout transition can remove up to six old slots and add up to six
    # differently named slots (for example daily -> guest at 12 people).
    changed_slots: list[Slot] = Field(max_length=14)
    warnings: list[Literal["NO_COMPLETE_MEAL_PLAN", "PARTIAL_REGENERATION", "HISTORY_RECYCLED"]] = Field(max_length=2)
    reason: Reason | None
    preferences: Preferences | None = None
    metadata_version: Name | None = None
    people: StrictInt | None = Field(default=None, ge=1, le=12)

    @model_validator(mode="after")
    def coherent(self):
        if self.season != 'ALL':
            seasonal = self.seasonal_assessment
            if not self.adaptive_daily or self.plan is not None and seasonal is None:
                raise ValueError('season metadata requires an automatic daily result')
            if seasonal is not None and (self.plan is None or seasonal.season != self.season
                    or [i.recipe_id for i in seasonal.items] != [i.recipe_id for i in self.plan.items]
                    or seasonal.score != sum(i.score for i in seasonal.items)
                    or seasonal.matched_count != sum(i.score > 0 for i in seasonal.items)
                    or seasonal.neutral_count != sum(i.score <= 0 for i in seasonal.items)):
                raise ValueError('season assessment does not match the current combo')
        elif self.seasonal_assessment is not None:
            raise ValueError('ALL must keep the original unscored season policy')
        if not self.adaptive_daily and (len(self.changed_slots) > 12 or self.reason and len(self.reason.slots) > 6):
            raise ValueError("legacy response exceeds its original slot bounds")
        if (self.preferences is None) != (self.metadata_version is None):
            raise ValueError("missing preference context")
        expected = {f"{g}:{i}" for g, n in self.counts.model_dump().items() for i in range(1, n + 1)}
        occasion = self.preferences.occasion if self.preferences else None
        max_per_group = 6 if self.layout_mode == "custom" else 5 if self.adaptive_daily else 4 if occasion in ("guests", "drinking") else 2
        if (not expected or len(expected) > (7 if self.adaptive_daily else 6) or any(value > max_per_group for value in self.counts.model_dump().values())
                or len(set(self.changed_slots)) != len(self.changed_slots)):
            raise ValueError("invalid counts or changed slots")
        if self.adaptive_daily and (self.layout_mode != "automatic" or occasion not in (None, "daily")):
            raise ValueError("adaptive daily flag is invalid for this layout")
        if self.adaptive_daily and (self.counts.main < 1 or self.counts.main > 5 or
                                    self.counts.vegetable < 1 or self.counts.vegetable > 4 or
                                    self.counts.soup > 4 or len(expected) < 2):
            raise ValueError("invalid adaptive daily structure")
        if not self.adaptive_daily and self.plan and (self.plan.total_minutes > 1440 or any(len(i.uses) > 6 for i in self.plan.shopping_list + self.plan.optional_shopping_list)):
            raise ValueError("legacy plan exceeds six-dish bounds")
        if self.adaptive_daily:
            if self.daily_combo_search is None or (self.plan is None) != (self.daily_combo_id is None):
                raise ValueError("daily combo metadata does not match the plan")
            if self.daily_selection_policy is not None:
                from source.server.daily_meal_recommendation import required_counts
                if self.counts.model_dump() != required_counts(self.people or 4):
                    raise ValueError("qualified daily combo must use the fixed structure")
        elif self.daily_selection_policy is not None or self.daily_combo_id is not None or self.daily_combo_search is not None or self.daily_combo_note is not None:
            raise ValueError("daily combo metadata is invalid for this plan")
        if self.plan is None:
            if self.reason is None or self.changed_slots or "NO_COMPLETE_MEAL_PLAN" not in self.warnings:
                raise ValueError("invalid empty outcome")
        elif (self.reason is not None or {i.slot for i in self.plan.items} != expected
              or len(self.plan.items) != len(expected)
              or len({i.recipe_id for i in self.plan.items}) != len(expected)):
            raise ValueError("invalid plan shape")
        return self


class FilterChoice(Contract):
    code: Name
    label: Name
    enabled: bool
    recipe_count: StrictInt = Field(ge=0)
    role_counts: dict[Literal["main", "vegetable", "soup"], StrictInt]
    reason: StrictStr = Field(min_length=1, max_length=500)
    supported_people: list[Annotated[StrictInt, Field(ge=1, le=12)]] | None = Field(default=None, max_length=12)


class FilterCatalog(Contract):
    dataset_version: Name
    metadata_version: Name
    scope: Literal["positive_required_ingredient_evidence"]
    role_recipe_count: StrictInt = Field(ge=0)
    choices: dict[Literal["diet", "region", "occasion"], list[FilterChoice]]
