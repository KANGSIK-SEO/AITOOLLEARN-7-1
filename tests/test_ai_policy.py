import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import AIUnavailableError, ensure_ai_allowed


def test_solar_pro4_allowed_before_cutoff():
    assert ensure_ai_allowed("solar-pro4", today=date(2027, 3, 31)) == "solar-pro4"


@pytest.mark.parametrize("model", ["gpt-5", "solar-pro3", "gemini-2.5-pro"])
def test_other_models_blocked(model):
    with pytest.raises(AIUnavailableError) as e:
        ensure_ai_allowed(model, today=date(2026, 9, 28))
    assert e.value.code == "AI_MODEL_NOT_ALLOWED"


@pytest.mark.parametrize("day", [date(2027, 4, 1), date(2027, 4, 2), date(2030, 1, 1)])
def test_all_models_blocked_from_2027_04(day):
    with pytest.raises(AIUnavailableError) as e:
        ensure_ai_allowed("solar-pro4", today=day)
    assert e.value.code == "AI_EXPIRED"
