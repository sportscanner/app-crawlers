from sportscanner.insights.planning import court_setting, courts_proposed, summarise


def test_courts_proposed_parses_common_phrasings():
    assert (
        courts_proposed(
            "Provision of 12no. padel courts within 2no. buildings", "padel"
        )
        == 12
    )
    assert courts_proposed("erection of seven padel courts and lighting", "padel") == 7
    assert courts_proposed("Installation of 2 x padel courts", "padel") == 2
    assert (
        courts_proposed(
            "three new covered padel courts and two outdoor padel courts", "padel"
        )
        == 5
    )
    assert courts_proposed("Installation of a padel court with fencing", "padel") == 1
    assert courts_proposed("Change of use to padel centre", "padel") is None


def test_court_setting():
    assert court_setting("padel courts with canopy over") == "covered"
    assert court_setting("change of use of warehouse to indoor padel") == "indoor"
    assert court_setting("two outdoor padel courts with floodlights") == "outdoor"
    assert court_setting("two padel courts with floodlights") == "unknown"


def test_summary_approval_rate_counts_only_decided():
    records = [
        {
            "uid": "1",
            "area_name": "Hackney",
            "app_state": "Permitted",
            "start_date": "2026-01-10",
            "decided_date": "2026-03-01",
            "description": "3 padel courts",
        },
        {
            "uid": "2",
            "area_name": "Hackney",
            "app_state": "Conditions",
            "start_date": "2026-02-10",
            "decided_date": "2026-04-01",
            "description": "2 padel courts",
        },
        {
            "uid": "3",
            "area_name": "Ealing",
            "app_state": "Rejected",
            "start_date": "2026-03-10",
            "decided_date": "2026-05-01",
            "description": "4 padel courts",
        },
        {
            "uid": "4",
            "area_name": "Ealing",
            "app_state": "Undecided",
            "start_date": "2026-09-10",
            "decided_date": None,
            "description": "6 padel courts",
        },
        {
            "uid": "5",
            "area_name": "Ealing",
            "app_state": "Withdrawn",
            "start_date": "2026-04-10",
            "decided_date": None,
            "description": "1 padel court",
        },
    ]
    summary = summarise(records, "padel")
    assert summary["total_applications"] == 5
    assert summary["approval_rate"] == 2 / 3
    assert summary["courts_proposed"] == 16
    assert summary["courts_in_pipeline"] == 3 + 2 + 6
    assert summary["by_borough"][0]["borough"] == "Ealing"
    assert summary["applications"][0]["reference"] == "4"


def test_summary_counts_duplicate_registrations_once():
    record = {
        "area_name": "Tower Hamlets",
        "app_state": "Undecided",
        "start_date": "2026-10-14",
        "decided_date": None,
        "description": "Seven  padel courts",
    }
    summary = summarise(
        [
            {**record, "uid": "PA/26/01756"},
            {**record, "uid": "PA/26/01757", "description": "seven padel courts"},
        ],
        "padel",
    )
    assert summary["total_applications"] == 1
    assert summary["courts_proposed"] == 7


def test_only_organisation_names_are_surfaced():
    from sportscanner.insights.planning import _organisation

    assert _organisation("Cestari Architects Ltd") == "Cestari Architects Ltd"
    assert _organisation("  Padel Social Club  ") == "Padel Social Club"
    assert _organisation("Jane Doe") is None
    assert _organisation("See source") is None
    assert _organisation(None) is None


def test_area_search_scopes_by_planning_authority():
    from sportscanner.insights.planning import _area_search_params

    assert _area_search_params("padel", "London")["auth"] == "London"
    assert _area_search_params("padel", "Manchester")["auth"] == "Manchester"
    assert _area_search_params("padel", "Manchester")["search"] == "padel"


def test_summary_marks_a_truncated_uk_scope():
    summary = summarise(
        [], "padel", scope="5 miles around the pin", total_available=12000
    )
    assert summary["scope"] == "5 miles around the pin"
    assert summary["total_available"] == 12000
    assert summary["truncated"] is True


def test_summary_flags_partial_authority_coverage():
    summary = summarise(
        [],
        "padel",
        scope="3 miles around the pin",
        authorities=["Manchester", "Salford"],
        failed_authorities=["Salford"],
    )
    assert summary["partial"] is True
    assert summary["authorities"] == ["Manchester", "Salford"]
    assert summary["failed_authorities"] == ["Salford"]


def test_fetch_records_defaults_to_london_and_searches_each_nearby_authority(
    monkeypatch,
):
    from sportscanner.insights import planning

    calls = []

    def fake_area(topic, authority):
        calls.append(authority)
        return [{"uid": authority}], 1

    monkeypatch.setattr(planning, "_fetch_area", fake_area)
    monkeypatch.setattr(
        planning,
        "_nearby_authorities",
        lambda lat, lon, radius: ["Manchester", "Salford"],
    )

    assert planning._fetch_records("padel") == ([{"uid": "London"}], 1, ["London"], [])
    assert calls == ["London"]

    records, total, authorities, failed = planning._fetch_records(
        "padel", 53.4808, -2.2426, 3
    )
    assert [record["uid"] for record in records] == ["Manchester", "Salford"]
    assert (total, authorities, failed) == (2, ["Manchester", "Salford"], [])


def test_summary_top_agents_and_approved_courts_by_year():
    records = [
        {
            "uid": "1",
            "area_name": "Ealing",
            "app_state": "Permitted",
            "start_date": "2025-01-10",
            "decided_date": "2025-03-01",
            "description": "4 padel courts",
            "other_fields": {
                "agent_name": "Court Planning Ltd",
                "applicant_name": "Jane Doe",
            },
        },
        {
            "uid": "2",
            "area_name": "Ealing",
            "app_state": "Rejected",
            "start_date": "2025-02-10",
            "decided_date": "2025-04-01",
            "description": "2 padel courts",
            "other_fields": {"agent_name": "Court Planning Ltd"},
        },
        {
            "uid": "3",
            "area_name": "Brent",
            "app_state": "Permitted",
            "start_date": "2026-02-10",
            "decided_date": "2026-04-01",
            "description": "3 padel courts with canopy",
            "other_fields": {"agent_name": "John Smith"},
        },
    ]
    summary = summarise(records, "padel")
    assert summary["top_agents"] == [
        {
            "agent": "Court Planning Ltd",
            "applications": 2,
            "approved": 1,
            "decided": 2,
            "courts": 6,
            "approval_rate": 0.5,
        }
    ]
    assert summary["applications"][-1]["applicant"] is None
    assert summary["approved_courts_by_year"] == [
        {"year": 2025, "courts": 4},
        {"year": 2026, "courts": 3},
    ]
    assert summary["courts_by_setting"]["covered"] == 3
