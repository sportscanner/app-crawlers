from datetime import datetime, date, timezone

def get_utc_timestamps(date_obj: date):
    """
    Convert a given Python date object to fromUTC and toUTC values.

    :param date_obj: date, a Python date object
    :return: tuple (fromUTC, toUTC)
    """
    from_utc = int(datetime.combine(date_obj, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    to_utc = int(datetime.combine(date_obj, datetime.max.time(), tzinfo=timezone.utc).timestamp())

    return from_utc, to_utc


def convert_sUTC_to_datetime(sUTC):
    return datetime.utcfromtimestamp(sUTC).strftime('%Y-%m-%d'), datetime.utcfromtimestamp(sUTC).strftime('%H:%M')


if __name__ == "__main__":
    # Example usage
    sUTC_values = [1740902400, 1740906000, 1740909600]
    converted_dates = [convert_sUTC_to_datetime(s) for s in sUTC_values]

    # Example usage
    date = "02-03-2025"
    from_utc, to_utc = get_utc_timestamps(date)
    print(f"fromUTC: {from_utc}, toUTC: {to_utc}")

    print(converted_dates)
