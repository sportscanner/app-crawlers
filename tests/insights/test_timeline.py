from datetime import date

from sportscanner.insights import service


def test_operator_key_groups_club_names():
    assert service._operator_key("Padium Canary Wharf") == "padium"
    assert service._operator_key("Padium Cardiff") == "padium"
    assert service._operator_key("Rocket Padel Ilford") == "rocket"
    assert service._operator_key("Rocket Padel Beckton") == "rocket"
    assert service._operator_key("Padel XTRA Beckenham") == "xtra"


def test_planning_matches_prioritises_name_and_postcode():
    venue = {
        "venue_name": "Padium Canary Wharf",
        "organisation": "Padel Mates",
        "postcode": "E14 5AB",
    }
    applications = [
        {
            "distance_miles": 0.05,
            "description": "Unrelated office refurbishment",
            "postcode": "E14 5AB",
            "applicant": None,
            "agent": None,
            "borough": "Tower Hamlets",
        },
        {
            "distance_miles": 0.3,
            "description": "Provision of padel courts for Padium",
            "postcode": None,
            "applicant": "Padium",
            "agent": None,
            "borough": "Tower Hamlets",
        },
        {
            "distance_miles": 0.4,
            "description": "Unrelated residential extension",
            "postcode": None,
            "applicant": None,
            "agent": None,
            "borough": "Tower Hamlets",
        },
    ]
    matches = service._planning_matches(venue, applications)
    assert [match["description"] for match in matches] == [
        "Provision of padel courts for Padium",
        "Unrelated office refurbishment",
    ]


def test_planning_events_use_first_submitted_and_approved():
    applications = [
        {
            "submitted": date(2022, 8, 4),
            "decided": None,
            "status": "Undecided",
            "description": "First application",
            "reference": "A",
            "url": "https://example.com/a",
            "courts": 7,
        },
        {
            "submitted": date(2022, 9, 1),
            "decided": date(2023, 4, 27),
            "status": "Permitted",
            "description": "Second application",
            "reference": "B",
            "url": "https://example.com/b",
            "courts": 7,
        },
    ]
    events = service._planning_events(applications)
    assert [event["title"] for event in events] == [
        "First planning application approved",
        "First planning application submitted",
    ]
    assert events[0]["date"] == "2023-04-27"
    assert events[1]["date"] == "2022-08-04"
    assert events[0]["reference"] == "B"


def test_club_timeline_combines_tracked_and_planning(monkeypatch):
    monkeypatch.setattr(
        service,
        "_first_tracked_dates",
        lambda sport, keys: {keys[0]: date(2026, 10, 25)},
    )
    monkeypatch.setattr(
        service,
        "applications_within",
        lambda *args: [
            {
                "distance_miles": 0.03,
                "submitted": date(2022, 8, 4),
                "decided": date(2023, 4, 27),
                "status": "Permitted",
                "description": "Padium padel courts",
                "reference": "PA/22/01528/NC",
                "url": "https://example.com",
                "courts": 7,
                "postcode": None,
                "applicant": "Padium",
                "agent": None,
                "borough": "Tower Hamlets",
            }
        ],
    )
    events = service._club_timeline(
        "padel",
        {
            "composite_key": "5bdd1d6c",
            "venue_name": "Padium Canary Wharf",
            "organisation": "Padel Mates",
            "postcode": "E14 5AB",
            "latitude": 51.5,
            "longitude": -0.02,
        },
    )
    assert [event["kind"] for event in events] == ["tracked", "planning", "planning"]
    assert events[0]["date"] == "2026-10-25"
    assert events[1]["title"] == "First planning application approved"
