from app.routes.chameleon import _normalize_chameleon_resource


def test_normalize_chameleon_lease_resource_preserves_reservations():
    slice_obj = {"id": "chi-slice-1", "site": "CHI@UC"}
    resource = _normalize_chameleon_resource({
        "type": "lease",
        "id": "lease-1",
        "name": "deploy-lease",
        "site": "CHI@UC",
        "status": "PENDING",
        "start_date": "2026-06-07 12:00",
        "end_date": "2026-06-07 16:00",
        "reservations": [
            {
                "id": "reservation-1",
                "resource_type": "physical:host",
                "status": "PENDING",
                "min": 1,
                "max": 1,
            },
        ],
    }, slice_obj)

    assert resource["type"] == "lease"
    assert resource["status"] == "PENDING"
    assert resource["start_date"] == "2026-06-07 12:00"
    assert resource["end_date"] == "2026-06-07 16:00"
    assert resource["reservations"] == [
        {
            "id": "reservation-1",
            "resource_type": "physical:host",
            "status": "PENDING",
            "min": 1,
            "max": 1,
        },
    ]
