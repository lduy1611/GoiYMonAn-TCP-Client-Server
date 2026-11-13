"""Transport validation only. Approved data and all portion math live on TCP."""
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator
from source.common.catalog_ids import MAX_PUBLIC_ID, valid_public_id


def _public_id(value):
    if not valid_public_id(value):
        raise ValueError("invalid public catalog ID")
    return value

ID = Annotated[StrictInt, Field(ge=1, le=4294967295)]
RecipeID = Annotated[StrictInt, Field(ge=1, le=MAX_PUBLIC_ID), AfterValidator(_public_id)]
CatalogID = Annotated[StrictInt, Field(ge=1, le=MAX_PUBLIC_ID), AfterValidator(_public_id)]
Name = Annotated[StrictStr, Field(min_length=1, max_length=255)]
Short = Annotated[StrictStr, Field(min_length=1, max_length=80)]
Number = Annotated[StrictStr, Field(max_length=96, pattern=r"^(?:0|[1-9][0-9]{0,40})(?:\.[0-9]{1,50})?$")]
Status = Literal["COMPLETE", "INCOMPLETE"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CalculationRequest(Contract):
    layout_mode: Literal["automatic", "custom"] = "automatic"
    recipe_ids: list[RecipeID] = Field(min_length=1, max_length=7)
    people: StrictInt = Field(ge=1, le=100)
    adults: StrictInt | None = Field(default=None, ge=0, le=100)
    children: StrictInt | None = Field(default=None, ge=0, le=100)
    occasion: Literal["daily", "weekend", "guests", "drinking", "snack"] = "daily"

    @model_validator(mode="after")
    def distinct(self):
        if len(self.recipe_ids) > 6 and (self.occasion != "daily" or self.layout_mode != "automatic"):
            raise ValueError("seven dishes require automatic daily policy")
        if len(set(self.recipe_ids)) != len(self.recipe_ids):
            raise ValueError("duplicate recipe ids")
        if (self.adults is None) != (self.children is None):
            raise ValueError("adult and child counts must be supplied together")
        if self.adults is not None and self.adults + self.children != self.people:
            raise ValueError("adult and child counts must equal people")
        return self


class Quantity(Contract):
    amount_kind: Literal["exact", "range"]
    quantity_value: Number | None
    quantity_min: Number
    quantity_max: Number
    precision: Literal["exact", "outward_6dp"]

    @model_validator(mode="after")
    def coherent_quantity(self):
        low, high = Decimal(self.quantity_min), Decimal(self.quantity_max)
        if low < 0 or high <= 0 or low > high:
            raise ValueError("invalid amount bounds")
        if self.amount_kind == "exact":
            if self.quantity_value != self.quantity_min or self.quantity_min != self.quantity_max or self.precision != "exact":
                raise ValueError("invalid exact amount")
        elif self.quantity_value is not None or low == high:
            raise ValueError("invalid range")
        return self


class Line(Quantity):
    line_id: ID
    ingredient_id: CatalogID
    unit: Short
    requirement: Literal["required", "optional", "unknown"] = "required"


class Reason(Contract):
    code: Short
    message: Annotated[StrictStr, Field(min_length=1, max_length=500)]
    line_id: ID | None


class Recipe(Contract):
    original_batch: bool = False
    data_status: Literal["verified", "estimated", "needs_review"] = "needs_review"
    data_evidence: StrictStr = Field(default="", max_length=2000)
    recipe_id: RecipeID
    revision_id: ID | None
    status: Status
    base_servings: Number | None
    target_servings: Number | None
    lines: list[Line] = Field(max_length=50)
    reasons: list[Reason] = Field(max_length=64)

    @model_validator(mode="after")
    def coherent_recipe(self):
        if len({line.line_id for line in self.lines}) != len(self.lines):
            raise ValueError("duplicate ingredient lines")
        if (self.base_servings is None) != (self.target_servings is None):
            raise ValueError("incomplete portion basis")
        if self.base_servings is not None and (Decimal(self.base_servings) <= 0 or Decimal(self.target_servings) <= 0):
            raise ValueError("invalid portion basis")
        if self.lines and (self.revision_id is None or self.base_servings is None and not self.original_batch):
            raise ValueError("lines have no approved revision basis")
        if self.status == "COMPLETE":
            if self.reasons or not self.lines:
                raise ValueError("invalid complete recipe")
        elif not self.reasons:
            raise ValueError("incomplete recipe needs reasons")
        return self


class Use(Quantity):
    recipe_id: RecipeID
    revision_id: ID
    line_id: ID
    requirement: Literal["required", "optional", "unknown"] = "required"


class Ingredient(Quantity):
    ingredient_id: CatalogID
    name: Name
    ingredient_form: Short | None
    measurement_basis: Literal["gross", "edible", "prepared", "unknown"]
    purpose: Literal["main", "seasoning", "cooking_medium", "garnish", "unknown", "consumed"]
    unit: Short
    requirement: Literal["required", "optional", "unknown"] = "required"
    mergeable: bool
    uses: list[Use] = Field(min_length=1, max_length=300)


class PortionGroup(Contract):
    role: Short
    label: Name
    target: Number | None
    unit: Short
    measurement_basis: Literal["gross", "prepared"]
    status: Status
    reason: StrictStr | None


class ServiceRecipe(Contract):
    recipe_id: RecipeID
    source_servings: Number | None
    target_servings: Number | None
    status: Literal["verified", "estimated", "unknown"]


class ServiceGroup(Contract):
    role: Short
    label: Name
    requested_servings: Number
    source_capacity: Number | None
    adjustment_factor: Number | None
    status: Literal["verified", "estimated", "unknown"]
    recipes: list[ServiceRecipe] = Field(min_length=1, max_length=7)


class ServiceAssessment(Contract):
    assessment_status: Literal["conditional", "risk", "surplus", "unknown"] | None = None
    limitations: list[Name] = Field(default_factory=list, max_length=6)
    meal_capacity: Number | None = None
    method: Literal["source_servings_by_role"]
    requested_servings: Number
    groups: list[ServiceGroup] = Field(max_length=6)
    note: Name


class DemoDriver(Contract):
    line_id: ID
    name: Name
    input_g: Number
    edible_fraction: Number
    cooking_factor: Number
    prepared_g: Number


class DemoRecipe(Contract):
    recipe_id: RecipeID
    role: Short
    status: Literal["estimated", "unknown"]
    context: Literal["shared", "standalone"]
    prepared_g: Number
    broth_ml: Number
    reference_g: Number
    dish_reference_g: Number
    dish_servings: Number | None
    meal_equivalents: Number | None
    source_servings: Number | None
    drivers: list[DemoDriver] = Field(max_length=50)
    issues: list[Name] = Field(max_length=51)


class DailyDemo(Contract):
    version: Literal["daily-demo-food-v1"]
    status: Literal["conditional", "risk", "surplus", "unknown"]
    requested: Number
    meal_equivalents: Number | None
    main_equivalents: Number
    reference_g: Number
    standalone_reference_g: Number
    main_min_share: Number
    max_surplus: Number
    note: Name
    recipes: list[DemoRecipe] = Field(max_length=7)


class CalculationData(Contract):
    daily_demo: DailyDemo | None = None
    layout_mode: Literal["automatic"] | None = None
    dataset_version: Name
    calculation_version: Literal["portion-v1"]
    recipe_ids: list[RecipeID] = Field(min_length=1, max_length=7)
    people: StrictInt = Field(ge=1, le=100)
    adults: StrictInt = Field(ge=0, le=100)
    children: StrictInt = Field(ge=0, le=100)
    child_equivalent: Number
    equivalent_people: Number
    occasion: Literal["daily", "weekend", "guests", "drinking", "snack"]
    policy_note: Name
    portion_groups: list[PortionGroup] = Field(max_length=6)
    service_assessment: ServiceAssessment | None = None
    status: Status
    totals_complete: bool
    portion_policy_version: Short | None
    recipes: list[Recipe] = Field(min_length=1, max_length=7)
    known_ingredients: list[Ingredient] = Field(max_length=300)

    @model_validator(mode="after")
    def coherent_data(self):
        if self.daily_demo is not None:
            if (self.occasion != "daily" or self.layout_mode != "automatic"
                    or self.daily_demo.requested != self.equivalent_people
                    or [r.recipe_id for r in self.daily_demo.recipes] != self.recipe_ids):
                raise ValueError("demo food policy is only valid for automatic daily meals")
        elif any(r.original_batch for r in self.recipes):
            raise ValueError("original batch marker requires daily demo policy")
        if len(self.recipe_ids) > 6 and (self.occasion != "daily" or self.layout_mode != "automatic"):
            raise ValueError("seven dishes require automatic daily policy")
        if len(set(self.recipe_ids)) != len(self.recipe_ids) or [r.recipe_id for r in self.recipes] != self.recipe_ids:
            raise ValueError("recipe selection changed")
        if self.adults + self.children != self.people or Decimal(self.child_equivalent) <= 0 or Decimal(self.child_equivalent) > 1:
            raise ValueError("invalid people equivalence")
        complete = all(r.status == "COMPLETE" for r in self.recipes)
        if self.totals_complete != complete or (self.status == "COMPLETE") != complete:
            raise ValueError("invalid completeness flags")
        lines = {(r.recipe_id, r.revision_id, line.line_id): line for r in self.recipes for line in r.lines}
        seen = set()
        groups = set()
        for ingredient in self.known_ingredients:
            group = (ingredient.ingredient_id, ingredient.ingredient_form, ingredient.measurement_basis,
                     ingredient.purpose, ingredient.unit, ingredient.requirement)
            complete_group = (ingredient.ingredient_form is not None
                              and ingredient.measurement_basis != "unknown"
                              and ingredient.purpose != "unknown"
                              and ingredient.requirement != "unknown")
            if ingredient.mergeable:
                if not complete_group or group in groups:
                    raise ValueError("invalid or duplicate merged ingredient group")
                groups.add(group)
            elif len(ingredient.uses) != 1:
                raise ValueError("unmergeable ingredient lines must remain separate")
            for use in ingredient.uses:
                key = (use.recipe_id, use.revision_id, use.line_id)
                line = lines.get(key)
                if (key in seen or line is None or line.ingredient_id != ingredient.ingredient_id
                        or line.unit != ingredient.unit
                        or line.requirement != ingredient.requirement
                        or any(getattr(use, k) != getattr(line, k) for k in Quantity.model_fields)):
                    raise ValueError("invalid ingredient provenance")
                seen.add(key)
        if set(lines) != seen or lines and self.portion_policy_version is None:
            raise ValueError("missing ingredient provenance or portion policy")
        return self
