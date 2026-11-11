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
    recipe_ids: list[RecipeID] = Field(min_length=1, max_length=6)
    people: StrictInt = Field(ge=1, le=100)

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.recipe_ids)) != len(self.recipe_ids):
            raise ValueError("duplicate recipe ids")
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
        if self.lines and (self.revision_id is None or self.base_servings is None):
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


class CalculationData(Contract):
    dataset_version: Name
    calculation_version: Literal["portion-v1"]
    recipe_ids: list[RecipeID] = Field(min_length=1, max_length=6)
    people: StrictInt = Field(ge=1, le=100)
    status: Status
    totals_complete: bool
    portion_policy_version: Short | None
    recipes: list[Recipe] = Field(min_length=1, max_length=6)
    known_ingredients: list[Ingredient] = Field(max_length=300)

    @model_validator(mode="after")
    def coherent_data(self):
        if len(set(self.recipe_ids)) != len(self.recipe_ids) or [r.recipe_id for r in self.recipes] != self.recipe_ids:
            raise ValueError("recipe selection changed")
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
