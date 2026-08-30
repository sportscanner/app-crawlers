from sportscanner.crawlers.parsers.better.core.strategy import _derive_indoor


def test_derive_indoor_tennis_reads_court_name():
    # Confirmed live against Islington Tennis Centre / Lee Valley: Better's
    # raw slot `name` field carries "Tennis Court - Indoor"/"- Outdoor" for
    # venues with mixed court types.
    assert _derive_indoor("Tennis", "Tennis Court - Indoor") is True
    assert _derive_indoor("Tennis", "Tennis Court - Outdoor") is False


def test_derive_indoor_tennis_unrecognised_name_is_unknown():
    assert _derive_indoor("Tennis", "Tennis Court") is None


def test_derive_indoor_pickleball_always_indoor():
    # Every Better pickleball court is a converted sports-hall court - no
    # indoor/outdoor split exists in the activity-slug config.
    assert _derive_indoor("Pickleball", "Pickleball 40 min") is True


def test_derive_indoor_not_applicable_for_badminton_and_squash():
    assert _derive_indoor("Badminton", "Badminton Court 1") is None
    assert _derive_indoor("Squash", "Squash Court 1") is None
