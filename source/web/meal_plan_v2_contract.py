"""Transport schemas for flexible meal slots; business rules stay on TCP."""
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, StrictInt, StrictStr, model_validator
from source.web.meal_plan_contract import Contract, IDs, Name, PositiveID
from source.common.catalog_ids import valid_public_id

def _recipe_id(value: int) -> int:
    if not valid_public_id(value):
        raise ValueError("invalid public recipe ID")
    return value

RecipeID = Annotated[StrictInt, Field(gt=0), AfterValidator(_recipe_id)]
RecipeIDs = Annotated[list[RecipeID], Field(max_length=50)]

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
    action: Literal["generate", "regenerate"] = "generate"
    # Omission keeps older V2 clients on the previous automatic/count policy.
    layout_mode: Literal["automatic", "custom"] = "automatic"
    ingredient_ids: list[PositiveID] = Field(default_factory=list, max_length=30)
    excluded_ids: list[PositiveID] = Field(default_factory=list, max_length=30)
    max_minutes: StrictInt | None = Field(default=None, ge=1, le=240)
    max_total_minutes: StrictInt | None = Field(default=None, ge=1, le=1440)
    max_missing: StrictInt | None = Field(default=None, ge=0, le=50)
    counts: Counts | None = None
    people: StrictInt | None = Field(default=None, ge=1, le=12)
    current_plan: dict[Slot, RecipeID] = Field(default_factory=dict, max_length=6)
    locked_slots: list[Slot] = Field(default_factory=list, max_length=6)
    replace_slot: Slot | None = None
    avoid_recipe_ids: dict[Literal["main", "vegetable", "soup"], RecipeIDs] = Field(default_factory=dict)
    preferences: Preferences | None = None

    @model_validator(mode="after")
    def omitted_layout_fields(self):
        if any(name in self.model_fields_set and getattr(self, name) is None for name in ("counts", "people")):
            raise ValueError("omit unspecified layout fields instead of sending null")
        if self.counts is not None:
            values = self.counts.model_dump()
            total = sum(values.values())
            occasion = self.preferences.occasion if self.preferences else None
            max_per_group = 6 if self.layout_mode == "custom" else 4 if occasion in ("guests", "drinking") else 2
            if not 1 <= total <= 6 or any(value > max_per_group for value in values.values()):
                raise ValueError("invalid dish count for layout mode")
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
    uses: list[ShoppingUse] = Field(min_length=1, max_length=6)


class Plan(Contract):
    items: list[Item] = Field(min_length=1, max_length=6)
    required_ids: IDs
    matched_ids: IDs
    missing_ids: IDs
    missing_count: StrictInt = Field(ge=0, le=50)
    total_minutes: StrictInt = Field(ge=1, le=1440)
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
    slots: list[Slot] = Field(max_length=6)
    groups: list[Shortage] = Field(max_length=3)
    suggestions: list[Name] = Field(max_length=3)


class Data(Contract):
    dataset_version: Name
    classification_version: Name
    algorithm: Literal["meal-plan-v2"]
    layout_mode: Literal["automatic", "custom"] = "automatic"
    counts: Counts
    plan: Plan | None
    # A layout transition can remove up to six old slots and add up to six
    # differently named slots (for example daily -> guest at 12 people).
    changed_slots: list[Slot] = Field(max_length=12)
    warnings: list[Literal["NO_COMPLETE_MEAL_PLAN", "PARTIAL_REGENERATION", "HISTORY_RECYCLED"]] = Field(max_length=2)
    reason: Reason | None
    preferences: Preferences | None = None
    metadata_version: Name | None = None
    people: StrictInt | None = Field(default=None, ge=1, le=12)

    @model_validator(mode="after")
    def coherent(self):
        if (self.preferences is None) != (self.metadata_version is None):
            raise ValueError("missing preference context")
        expected = {f"{g}:{i}" for g, n in self.counts.model_dump().items() for i in range(1, n + 1)}
        occasion = self.preferences.occasion if self.preferences else None
        max_per_group = 6 if self.layout_mode == "custom" else 4 if occasion in ("guests", "drinking") else 2
        if (not expected or len(expected) > 6 or any(value > max_per_group for value in self.counts.model_dump().values())
                or len(set(self.changed_slots)) != len(self.changed_slots)):
            raise ValueError("invalid counts or changed slots")
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
