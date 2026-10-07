import pytest
from app.schemas import BrewMethod, BrewRecord
from pydantic import ValidationError


def valid_data(**overrides):
    """A known-good V60 cup; each test breaks exactly one thing."""
    data = {
        "user_id": "esteban",
        "method": "v60",
        "brewed_at": "2026-10-06T07:30:00",
        "coffee_grams": 15,
        "water_ml": 250,
        "water_temp_c": 93,
        "brew_time_seconds": 180,
        "grinder": "manual",
        "grind_setting": 22,
        "bean_name": "Huila washed",
        "overall": 7.5,
        "v60_dripper": "lotus",
    }
    data.update(overrides)
    return data


def espresso_data(**overrides):
    """A known-good espresso: no water_ml, no dripper."""
    return valid_data(
        method="espresso",
        v60_dripper=None,
        water_ml=None,
        coffee_grams=18,
        grinder="manual_espresso",
        grind_setting=12,
        brew_time_seconds=28,
        **overrides,
    )


def test_valid_record_and_computed_ratio():
    record = BrewRecord(**valid_data())
    assert record.method == BrewMethod.V60
    assert record.ratio == pytest.approx(16.67, abs=0.01)
    assert record.sweetness is None  # optional axes default to None
    assert record.is_base_recipe is False
    assert record.effective_yield_grams is None  # espresso only


def test_ratio_is_included_in_serialized_output():
    assert "ratio" in BrewRecord(**valid_data()).model_dump()


@pytest.mark.parametrize(
    "field, value",
    [
        ("overall", 11),
        ("overall", -1),
        ("sweetness", 10.5),
        ("water_temp_c", 120),
        ("water_temp_c", 20),
        ("coffee_grams", 0),
        ("water_ml", 5000),
        ("brew_time_seconds", 0),
        ("grind_setting", -3),
        ("user_id", ""),
        ("bean_name", ""),
    ],
)
def test_out_of_range_values_are_rejected(field, value):
    with pytest.raises(ValidationError):
        BrewRecord(**valid_data(**{field: value}))


def test_unknown_method_is_rejected():
    with pytest.raises(ValidationError):
        BrewRecord(**valid_data(method="chemex"))


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        BrewRecord(**valid_data(sweetnes=5))  # typo on purpose


def test_implausible_ratio_is_rejected():
    # 100 g of coffee with 20 ml of water -> 1:0.2
    with pytest.raises(ValidationError):
        BrewRecord(**valid_data(coffee_grams=100, water_ml=20))


def test_dripper_only_allowed_for_v60():
    with pytest.raises(ValidationError):
        BrewRecord(**valid_data(method="aeropress"))  # still has v60_dripper set


def test_non_v60_without_dripper_is_valid():
    record = BrewRecord(**valid_data(method="aeropress", v60_dripper=None))
    assert record.method == BrewMethod.AEROPRESS


# --- Grinder rules ---


def test_electric_dial_accepts_values_between_marks():
    record = BrewRecord(**valid_data(grinder="electric", grind_setting=17.5))
    assert record.grind_setting == 17.5


def test_electric_dial_accepts_its_maximum():
    assert BrewRecord(**valid_data(grinder="electric", grind_setting=30)).grind_setting == 30


def test_electric_dial_above_30_is_rejected():
    with pytest.raises(ValidationError):
        BrewRecord(**valid_data(grinder="electric", grind_setting=31))


def test_manual_grinder_rejects_fractional_clicks():
    with pytest.raises(ValidationError):
        BrewRecord(**valid_data(grinder="manual", grind_setting=22.5))


# --- Water volume and temperature depend on the method ---


def test_water_ml_required_for_non_espresso():
    with pytest.raises(ValidationError):
        BrewRecord(**valid_data(water_ml=None))


def test_water_temp_required_except_for_moka():
    with pytest.raises(ValidationError):
        BrewRecord(**valid_data(water_temp_c=None))


def test_moka_without_water_temp_is_valid():
    record = BrewRecord(**valid_data(method="moka", v60_dripper=None, water_temp_c=None))
    assert record.water_temp_c is None


# --- Espresso yield ---


def test_espresso_without_yield_assumes_1_to_2():
    record = BrewRecord(**espresso_data())
    assert record.yield_grams is None  # raw value stays "unknown"
    assert record.effective_yield_grams == 36
    assert record.ratio == 2.0


def test_espresso_with_measured_yield_uses_it():
    record = BrewRecord(**espresso_data(yield_grams=40))
    assert record.effective_yield_grams == 40
    assert record.ratio == pytest.approx(2.22, abs=0.01)


def test_yield_only_allowed_for_espresso():
    with pytest.raises(ValidationError):
        BrewRecord(**valid_data(yield_grams=36))