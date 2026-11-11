"""Web transport validation only; selection and shopping calculations remain on TCP."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

Slot = Literal["main", "vegetable", "soup"]
PositiveID = Annotated[StrictInt, Field(gt=0)]
IDs = Annotated[list[PositiveID], Field(max_length=50)]
Name = Annotated[StrictStr, Field(min_length=1, max_length=255)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CurrentPlan(Contract):
    main: PositiveID
    vegetable: PositiveID
    soup: PositiveID


class MealPlanRequest(Contract):
    ingredient_ids: list[PositiveID] = Field(default_factory=list, max_length=30)
    excluded_ids: list[PositiveID] = Field(default_factory=list, max_length=30)
    max_minutes: StrictInt | None = Field(default=None, ge=1, le=240)
    max_total_minutes: StrictInt | None = Field(default=None, ge=1, le=720)
    max_missing: StrictInt | None = Field(default=None, ge=0, le=50)
    current_plan: CurrentPlan | None = None
    locked_slots: list[Slot] = Field(default_factory=list, max_length=2)
    avoid_recipe_ids: dict[Slot, Annotated[list[PositiveID], Field(max_length=50)]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_relationships(self):
        if set(self.ingredient_ids) & set(self.excluded_ids):
            raise ValueError("selected and excluded ingredients overlap")
        if len(set(self.locked_slots)) != len(self.locked_slots) or self.locked_slots and self.current_plan is None:
            raise ValueError("invalid locked slots")
        if self.current_plan and len(set(self.current_plan.model_dump().values())) != 3:
            raise ValueError("current recipe ids must be distinct")
        if (any(len(set(ids)) != len(ids) for ids in self.avoid_recipe_ids.values())
                or sum(map(len, self.avoid_recipe_ids.values())) > 50
                or any(self.avoid_recipe_ids.values()) and self.current_plan is None):
            raise ValueError("invalid recipe history")
        return self


class MealItem(Contract):
    slot: Slot
    recipe_id: PositiveID
    title: Name
    minutes: StrictInt = Field(ge=1, le=240)
    matched_ids: IDs
    missing_ids: IDs
    missing_count: StrictInt = Field(ge=0, le=50)


class ShoppingUse(Contract):
    recipe_id: PositiveID
    # A recipe can intentionally have an unquantified ingredient. Preserve
    # that absence as null instead of inventing a shopping amount.
    quantity: StrictStr | None = Field(max_length=255)
    is_required: bool


class ShoppingItem(Contract):
    ingredient_id: PositiveID
    name: Name
    uses: list[ShoppingUse] = Field(min_length=1, max_length=3)


class MealPlan(Contract):
    items: list[MealItem] = Field(min_length=3, max_length=3)
    required_ids: IDs
    matched_ids: IDs
    missing_ids: IDs
    missing_count: StrictInt = Field(ge=0, le=50)
    total_minutes: StrictInt = Field(ge=3, le=720)
    time_basis: Literal["sum_of_recipe_minutes"]
    shopping_list: list[ShoppingItem] = Field(max_length=50)
    optional_shopping_list: list[ShoppingItem] = Field(max_length=50)
    optional_missing_ids: IDs

    @model_validator(mode="after")
    def check_slots(self):
        if {item.slot for item in self.items} != {"main", "vegetable", "soup"} or len({item.recipe_id for item in self.items}) != 3:
            raise ValueError("invalid meal slots")
        return self


class MealReason(Contract):
    code: StrictStr = Field(min_length=1, max_length=80)
    message: StrictStr = Field(min_length=1, max_length=500)
    slots: list[Slot] = Field(max_length=3)


class MealPlanData(Contract):
    dataset_version: StrictStr = Field(min_length=1, max_length=255)
    classification_version: StrictStr = Field(min_length=1, max_length=80)
    algorithm: Literal["meal-plan-v1"]
    plan: MealPlan | None
    changed_slots: list[Slot] = Field(max_length=3)
    warnings: list[Literal["PARTIAL_REGENERATION", "NO_COMPLETE_MEAL_PLAN", "HISTORY_RECYCLED"]] = Field(max_length=2)
    reason: MealReason | None

    @model_validator(mode="after")
    def check_outcome(self):
        if len(set(self.changed_slots)) != len(self.changed_slots):
            raise ValueError("duplicate changed slots")
        if self.plan is None and (self.reason is None or self.changed_slots or "NO_COMPLETE_MEAL_PLAN" not in self.warnings):
            raise ValueError("missing empty outcome details")
        if self.plan is not None and self.reason is not None:
            raise ValueError("unexpected failure reason")
        return self
