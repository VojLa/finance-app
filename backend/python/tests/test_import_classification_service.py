from app.modules.imports.classification_service import _canonical, _marker_is


def test_classifier_workflow_metadata_is_removed_from_canonical_payload() -> None:
    payload = {
        "schema_version": 1,
        "source": "manual",
        "amount": "1",
        "deduplication": {"schema_version": 1, "status": "unique"},
        "posting_intent": {"target": "transaction"},
    }

    canonical = _canonical(payload)

    assert canonical == {"schema_version": 1, "source": "manual", "amount": "1"}
    assert _marker_is(payload, "unique")
    assert payload["posting_intent"] == {"target": "transaction"}
