"""Data contracts for BrewOptimizer AI (Sprint 1).

Every layer (API, DuckDB, optimizer, agent) goes through these models, so a
bad value is rejected here instead of silently poisoning the optimizer.
"""

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

# Espresso convention: 1 g of ground coffee -> 2 g of liquid (18 g in, 36 g out).
DEFAULT_ESPRESSO_YIELD_FACTOR = 2.0
# The electric grinder's dial is numbered 0-30 (labels every 5, marks in between).
ELECTRIC_GRINDER_MAX_SETTING = 30


class BrewMethod(StrEnum):
    V60 = "v60"
    AEROPRESS = "aeropress"
    ESPRESSO = "espresso"
    FRENCH_PRESS = "french_press"
    MOKA = "moka"


class V60Dripper(StrEnum):
    # Physical variants of the V60 you own. The ridge pattern changes flow rate,
    # so the same recipe tastes different. Names are generic on purpose; rename
    # them once you confirm the exact models.
    STRAIGHT_RIBS = "straight_ribs"
    SPIRAL_RIBS = "spiral_ribs"
    LOTUS = "lotus"


class Grinder(StrEnum):
    # Settings are NOT comparable between grinders, so the grinder is part of
    # the recipe. 20 clicks on one grinder != 20 on another.
    ELECTRIC = "electric"
    MANUAL = "manual"
    MANUAL_ESPRESSO = "manual_espresso"


class RoastLevel(StrEnum):
    LIGHT = "light"
    MEDIUM = "medium"
    DARK = "dark"


class BrewRecord(BaseModel):
    """One brewed cup: the recipe used plus how it tasted."""

    # extra="forbid": a typo like "sweetnes" raises an error instead of being
    # silently ignored (which would lose data without anyone noticing).
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    user_id: str = Field(min_length=1, max_length=50)
    method: BrewMethod
    brewed_at: datetime
    # True for the starting recipes used to seed the optimizer (cold start).
    is_base_recipe: bool = False

    # --- Recipe (the variables the optimizer will tune) ---
    coffee_grams: float = Field(ge=1, le=100)
    # Optional only for espresso, where you measure the liquid out, not the water in.
    water_ml: float | None = Field(default=None, ge=20, le=1500)
    # Liquid weight out. Espresso only; optional because 1:2 is the usual target.
    yield_grams: float | None = Field(default=None, ge=5, le=200)
    # Lower bound 60 C excludes cold brew; upper bound is water's boiling point.
    # Optional only for moka, where the stove sets the temperature, not you.
    water_temp_c: float | None = Field(default=None, ge=60, le=100)
    brew_time_seconds: int = Field(ge=10, le=900)
    grinder: Grinder
    # Clicks (manual grinders, whole numbers) or dial position (electric, 0-30,
    # may fall between numbers). One generic field avoids two nearly equal columns.
    grind_setting: float = Field(ge=0, le=100)

    # --- Context (not tuned, but a different bean is a different problem) ---
    bean_name: str = Field(min_length=1, max_length=100)
    roast_level: RoastLevel | None = None
    # Only meaningful when method == V60.
    v60_dripper: V60Dripper | None = None

    # --- Taste axes, 0-10. Optional because you are not expert tasters:
    # you can log only the overall score and fill the rest later.
    overall: float = Field(ge=0, le=10)
    sweetness: float | None = Field(default=None, ge=0, le=10)
    acidity: float | None = Field(default=None, ge=0, le=10)
    bitterness: float | None = Field(default=None, ge=0, le=10)
    body: float | None = Field(default=None, ge=0, le=10)

    @computed_field  # derived value: never stored, so it can never disagree with the inputs
    @property
    def effective_yield_grams(self) -> float | None:
        """Espresso only: the measured yield, or the 1:2 default when not measured.

        The raw yield_grams stays None when you did not measure it: we keep
        "unknown" and "assumed" separate instead of overwriting missing data.
        """
        if self.method != BrewMethod.ESPRESSO:
            return None
        if self.yield_grams is not None:
            return self.yield_grams
        return round(self.coffee_grams * DEFAULT_ESPRESSO_YIELD_FACTOR, 1)

    @computed_field
    @property
    def ratio(self) -> float:
        """Liquid per gram of coffee (16.0 means 1:16).

        Espresso uses liquid out (the industry brew ratio); other methods use
        water in. The validator below guarantees the needed value exists.
        """
        if self.method == BrewMethod.ESPRESSO:
            liquid = self.effective_yield_grams
        else:
            liquid = self.water_ml
        return round(liquid / self.coffee_grams, 2)

    @model_validator(mode="after")
    def check_cross_field_rules(self) -> Self:
        # Field-level limits cannot see other fields, so cross-field rules live here.
        is_espresso = self.method == BrewMethod.ESPRESSO

        # Required-ness that depends on the method.
        if self.water_ml is None and not is_espresso:
            raise ValueError("water_ml is required unless method is 'espresso'")
        if self.water_temp_c is None and self.method != BrewMethod.MOKA:
            raise ValueError("water_temp_c is required unless method is 'moka'")

        # Fields that only make sense for one method.
        if self.yield_grams is not None and not is_espresso:
            raise ValueError("yield_grams only applies when method is 'espresso'")
        if self.v60_dripper is not None and self.method != BrewMethod.V60:
            raise ValueError("v60_dripper only applies when method is 'v60'")

        # Grinder rules: the dial stops at 30; clicks cannot be fractional.
        if self.grinder == Grinder.ELECTRIC:
            if self.grind_setting > ELECTRIC_GRINDER_MAX_SETTING:
                raise ValueError(f"electric grinder dial goes up to {ELECTRIC_GRINDER_MAX_SETTING}")
        elif self.grind_setting != int(self.grind_setting):
            raise ValueError("manual grinders count whole clicks")

        # 1:1 to 1:25 covers everything from espresso to a weak filter coffee;
        # outside that range it is almost surely a typo (e.g. 250 ml entered as 25).
        if not 1 <= self.ratio <= 25:
            raise ValueError(f"ratio 1:{self.ratio} is outside the plausible range 1:1 - 1:25")
        return self