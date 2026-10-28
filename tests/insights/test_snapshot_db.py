"""Opt-in SQL integration tests. All fixture writes are rolled back."""

import os
import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_INSIGHTS_DB_TESTS") != "1", reason="Set RUN_INSIGHTS_DB_TESTS=1 for the development database")


@pytest.mark.parametrize("sport", ["badminton", "squash", "pickleball", "padel", "tennis"])
def test_daily_snapshots_preserve_genuine_quotes_and_reject_stale_or_estimated_rows(monkeypatch, sport):
    from sqlalchemy import text
    from sqlmodel import Session
    from sportscanner.storage.postgres import database as db
    from sportscanner.storage.postgres import tables

    if os.getenv("ENV") == "prod":
        pytest.fail("These tests must run against the development database")
    db.ensure_slot_history_table(db.engine)
    connection = db.engine.connect()
    outer = connection.begin()
    monkeypatch.setattr(db, "Session", lambda _: Session(bind=connection, join_transaction_mode="create_savepoint"))
    monkeypatch.setattr(db, "engine", connection)
    try:
        venue = connection.execute(text("SELECT composite_key FROM public.sportsvenue LIMIT 1")).scalar_one()
        refreshed = datetime.now(ZoneInfo("Europe/London")).replace(tzinfo=None) + timedelta(seconds=5)
        tomorrow = refreshed.date() + timedelta(days=1)
        uid = "insights-test-" + uuid.uuid4().hex
        connection.execute(text(f"""
            INSERT INTO public.{sport}
                (uid, category, starting_time, ending_time, date, price, spaces, last_refreshed, composite_key, starts_at)
            VALUES (:uid, :sport, '04:17', '04:57', :day, '12', 2, :refreshed, :venue, :starts_at)
        """), dict(uid=uid, sport=sport, day=tomorrow, refreshed=refreshed, venue=venue, starts_at=datetime.combine(tomorrow, time(4, 17))))
        model = getattr(tables, sport.title() + "MasterTable")
        db.snapshot_slot_history(model, refreshed)
        def prices():
            return connection.execute(text("""
                SELECT price_per_hour FROM public.daily_price_snapshot
                WHERE sport=:sport AND composite_key=:venue AND observed_on=:day AND starting_time='04:17' AND duration_min=40
            """), dict(sport=sport, venue=venue, day=refreshed.date())).scalar_one()
        assert prices() == 18
        connection.execute(text(f"UPDATE public.{sport} SET price='16' WHERE uid=:uid"), dict(uid=uid))
        db.snapshot_slot_history(model, refreshed)
        assert prices() == 24
        connection.execute(text(f"UPDATE public.{sport} SET price='~50' WHERE uid=:uid"), dict(uid=uid))
        db.snapshot_slot_history(model, refreshed)
        assert prices() == 24
        connection.execute(text(f"UPDATE public.{sport} SET price='99', last_refreshed=:old WHERE uid=:uid"), dict(uid=uid, old=refreshed-timedelta(days=1)))
        db.snapshot_slot_history(model, refreshed)
        assert prices() == 24
        # London observation days are unique: repeated crawls update one sample.
        assert connection.execute(text("""
            SELECT COUNT(*) FROM public.daily_price_snapshot WHERE sport=:sport AND composite_key=:venue
              AND observed_on=:day AND starting_time='04:17' AND duration_min=40
        """), dict(sport=sport, venue=venue, day=refreshed.date())).scalar_one() == 1
    finally:
        outer.rollback()
        connection.close()


def test_postgres_history_join_excludes_new_venues_and_weights_venues_equally(monkeypatch):
    from sqlalchemy import text
    from sportscanner.insights import service
    from sportscanner.storage.postgres import database as db
    from sportscanner.api.routers.insights.schemas import HistoricalReport

    if os.getenv("ENV") == "prod":
        pytest.fail("Development database only")
    db.ensure_slot_history_table(db.engine)
    token = uuid.uuid4().hex[:5]
    keys = [f"qa{token}{letter}" for letter in "abc"]
    today = datetime.now(ZoneInfo("Europe/London")).date()
    with db.engine.connect() as connection:
        outer = connection.begin()
        try:
            for venue, hour, old, latest in [(keys[0], 8, 10, 20)] + [(keys[1], h, 20, 20) for h in range(8, 20)]:
                for day, price in [(today - timedelta(days=2), old), (today, latest)]:
                    connection.execute(text("""
                        INSERT INTO public.daily_price_snapshot
                        (sport,composite_key,observed_on,dow,starting_time,duration_min,price_per_hour,observed_at,days_ahead)
                        VALUES ('padel',:venue,:day,1,:hour,60,:price,:seen,1)
                    """), dict(venue=venue, day=day, hour=time(hour), price=price, seen=datetime.combine(day, time(12))))
            connection.execute(text("""
                INSERT INTO public.daily_price_snapshot
                (sport,composite_key,observed_on,dow,starting_time,duration_min,price_per_hour,observed_at,days_ahead)
                VALUES ('padel',:venue,:day,1,'08:00',60,1000,:seen,1)
            """), dict(venue=keys[2], day=today, seen=datetime.combine(today, time(12))))
            monkeypatch.setattr(service, "_cache", {})
            monkeypatch.setattr(service, "market_report", lambda *args: {"venues": [{"composite_key": key, "venue_name": key} for key in keys]})
            monkeypatch.setattr(service, "_rows", lambda sql, **params: connection.execute(text(sql), params).mappings().all())
            report = service.historical_report("padel", 28)
            assert report["prices"]["change_percent"] == 50
            assert report["prices"]["series"][1]["index"] is None
            assert report["prices"]["series"][-1]["matched_venues"] == 2
            HistoricalReport(**report)
        finally:
            outer.rollback()
