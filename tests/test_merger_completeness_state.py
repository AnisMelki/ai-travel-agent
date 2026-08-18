from datetime import UTC, date, datetime

from app.schema.state_conversation import (
    ConversationStatus,
    FlightConversationState,
    FlightRequestPatch,
)
from app.service.conversation_service.merger_completeness_state import (
    FlightRequestCompletenessChecker,
    FlightStateMerger,
)


def _make_state(**overrides) -> FlightConversationState:
    defaults = {
        "conversation_id": "conv-1",
        "created_at": datetime(2020, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2020, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return FlightConversationState(**defaults)


# ---------------------------------------------------------------------------
# FlightStateMerger
# ---------------------------------------------------------------------------


def test_merge_preserves_existing_values_when_patch_fields_are_none():
    state = _make_state(
        origin="paris",
        destination="london",
        departure_date=date(2026, 9, 1),
        origin_code="CDG",
        destination_code="LHR",
    )
    merger = FlightStateMerger()

    merged = merger.merge(state, FlightRequestPatch())

    assert merged.origin == "paris"
    assert merged.destination == "london"
    assert merged.departure_date == date(2026, 9, 1)
    assert merged.origin_code == "CDG"
    assert merged.destination_code == "LHR"


def test_merge_updates_value_when_patch_contains_new_field():
    state = _make_state()
    merger = FlightStateMerger()

    merged = merger.merge(state, FlightRequestPatch(departure_date=date(2026, 9, 1)))

    assert merged.departure_date == date(2026, 9, 1)


def test_merge_normalizes_origin_and_destination():
    state = _make_state()
    merger = FlightStateMerger()

    merged = merger.merge(
        state, FlightRequestPatch(origin="  PARIS  ", destination="London")
    )

    assert merged.origin == "paris"
    assert merged.destination == "london"


def test_merge_resets_origin_code_when_origin_changes():
    state = _make_state(origin="paris", origin_code="CDG")
    merger = FlightStateMerger()

    merged = merger.merge(state, FlightRequestPatch(origin="london"))

    assert merged.origin_code is None


def test_merge_resets_destination_code_when_destination_changes():
    state = _make_state(destination="london", destination_code="LHR")
    merger = FlightStateMerger()

    merged = merger.merge(state, FlightRequestPatch(destination="paris"))

    assert merged.destination_code is None


def test_merge_resets_origin_code_even_when_origin_value_is_unchanged():
    # merge() doesn't diff against the current value; any patch-supplied
    # origin is treated as a change, so resubmitting the same city still
    # clears a previously resolved origin_code.
    state = _make_state(origin="paris", origin_code="CDG")
    merger = FlightStateMerger()

    merged = merger.merge(state, FlightRequestPatch(origin="paris"))

    assert merged.origin_code is None


def test_merge_resets_destination_code_even_when_destination_value_is_unchanged():
    state = _make_state(destination="london", destination_code="LHR")
    merger = FlightStateMerger()

    merged = merger.merge(state, FlightRequestPatch(destination="london"))

    assert merged.destination_code is None


def test_merge_preserves_origin_code_when_origin_not_in_patch():
    state = _make_state(origin="paris", origin_code="CDG")
    merger = FlightStateMerger()

    merged = merger.merge(state, FlightRequestPatch(destination="london"))

    assert merged.origin_code == "CDG"


def test_merge_preserves_destination_code_when_destination_not_in_patch():
    state = _make_state(destination="london", destination_code="LHR")
    merger = FlightStateMerger()

    merged = merger.merge(state, FlightRequestPatch(origin="paris"))

    assert merged.destination_code == "LHR"


def test_merge_partial_patch_preserves_unrelated_fields_and_airport_codes():
    state = _make_state(
        origin="paris",
        destination="london",
        departure_date=date(2026, 9, 1),
        return_date=date(2026, 9, 10),
        origin_code="CDG",
        destination_code="LHR",
        status=ConversationStatus.READY,
    )
    merger = FlightStateMerger()

    merged = merger.merge(state, FlightRequestPatch(departure_date=date(2026, 9, 5)))

    assert merged.departure_date == date(2026, 9, 5)
    assert merged.origin == "paris"
    assert merged.destination == "london"
    assert merged.return_date == date(2026, 9, 10)
    assert merged.origin_code == "CDG"
    assert merged.destination_code == "LHR"
    assert merged.status == ConversationStatus.READY


def test_merge_increments_version():
    state = _make_state(version=3)
    merger = FlightStateMerger()

    merged = merger.merge(state, FlightRequestPatch())

    assert merged.version == 4


def test_merge_updates_updated_at_timestamp():
    state = _make_state(updated_at=datetime(2020, 1, 1, tzinfo=UTC))
    merger = FlightStateMerger()

    merged = merger.merge(state, FlightRequestPatch())

    assert merged.updated_at.tzinfo is not None
    assert merged.updated_at > state.updated_at


def test_merge_returns_new_state_instance_and_does_not_mutate_original():
    state = _make_state(origin="paris")
    merger = FlightStateMerger()

    merged = merger.merge(state, FlightRequestPatch(origin="london"))

    assert merged is not state
    assert state.origin == "paris"


# ---------------------------------------------------------------------------
# FlightRequestCompletenessChecker
# ---------------------------------------------------------------------------


def test_missing_fields_empty_when_all_required_fields_present():
    state = _make_state(
        origin="paris", destination="london", departure_date=date(2026, 9, 1)
    )
    checker = FlightRequestCompletenessChecker()

    assert checker.missing_fields(state) == []


def test_missing_fields_lists_missing_required_fields_in_declared_order():
    state = _make_state(origin="paris")
    checker = FlightRequestCompletenessChecker()

    assert checker.missing_fields(state) == ["destination", "departure_date"]


def test_is_complete_true_when_no_fields_missing():
    state = _make_state(
        origin="paris", destination="london", departure_date=date(2026, 9, 1)
    )
    checker = FlightRequestCompletenessChecker()

    assert checker.is_complete(state) is True


def test_is_complete_false_when_a_required_field_is_missing():
    state = _make_state(origin="paris", destination="london")
    checker = FlightRequestCompletenessChecker()

    assert checker.is_complete(state) is False
