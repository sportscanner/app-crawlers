"""Price indices compare each schedule sample to itself on the baseline day.

Each venue gets equal weight. New expensive venues cannot move the index, and
missing samples are never carried forward. The daily average price is a separate
descriptive figure. An index movement can reflect dynamic prices or lead time,
not necessarily an operator changing its tariff.
"""

from collections import defaultdict
from datetime import timedelta
from statistics import mean


def summarise_price_pairs(bounds, pairs):
    """Render pre-aggregated PostgreSQL comparisons without loading raw quotes."""
    first, last = bounds["first_day"], bounds["last_day"]
    if first is None:
        return price_history([])
    by_day = defaultdict(list)
    for pair in pairs:
        by_day[pair["observed_on"]].append(pair)
    series = []
    day = first
    while day <= last:
        matched = [r for r in by_day[day] if r["ratio"] is not None]
        index = mean(float(r["ratio"]) for r in matched) * 100 if matched else None
        series.append({"date": day, "index": round(index, 2) if index is not None else None,
                       "matched_samples": sum(r["ratio_samples"] for r in matched), "matched_venues": len(matched)})
        day += timedelta(days=1)
    changes = [{"composite_key": r["composite_key"], "before": round(float(r["before"]), 2),
                "after": round(float(r["after"]), 2), "matched_samples": r["matched_samples"],
                "change_percent": round((float(r["ratio"]) - 1) * 100, 2) if r["ratio"] is not None else None}
               for r in by_day[last]] if first != last else []
    latest_index = series[-1]["index"]
    return {"baseline": first, "latest": last, "observed_days": bounds["observed_days"], "series": series,
            "change_percent": round(latest_index - 100, 2) if first != last and latest_index is not None else None,
            "venues": sorted(changes, key=lambda v: abs(v["change_percent"] or 0), reverse=True)}


def price_history(rows):
    by_day = defaultdict(dict)
    for row in rows:
        key = (row["composite_key"], row["dow"], row["starting_time"], row["duration_min"])
        by_day[row["observed_on"]][key] = float(row["price_per_hour"])
    dates = sorted(by_day)
    empty = {"baseline": None, "latest": None, "change_percent": None, "series": [], "venues": [], "observed_days": len(dates)}
    if not dates:
        return empty
    baseline = by_day[dates[0]]
    series, changes = [], []
    day = dates[0]
    while day <= dates[-1]:
        sample = by_day.get(day, {})
        matches = baseline.keys() & sample.keys()
        ratios, prices = defaultdict(list), defaultdict(list)
        for key in matches:
            prices[key[0]].append((baseline[key], sample[key]))
            if baseline[key] > 0:
                ratios[key[0]].append(sample[key] / baseline[key])
        index = mean(mean(v) for v in ratios.values()) * 100 if ratios else None
        series.append({
            "date": day, "index": round(index, 2) if index is not None else None,
            "matched_samples": sum(len(v) for v in ratios.values()), "matched_venues": len(ratios),
        })
        if day == dates[-1] and len(dates) > 1:
            for key, pairs in prices.items():
                before, after = mean(p[0] for p in pairs), mean(p[1] for p in pairs)
                changes.append({
                    "composite_key": key, "before": round(before, 2), "after": round(after, 2),
                    "change_percent": round((mean(ratios[key]) - 1) * 100, 2) if key in ratios else None,
                    "matched_samples": len(pairs),
                })
        day += timedelta(days=1)
    latest_index = series[-1]["index"]
    return {
        "baseline": dates[0], "latest": dates[-1], "observed_days": len(dates),
        "change_percent": round(latest_index - 100, 2) if len(dates) > 1 and latest_index is not None else None,
        "series": series, "venues": sorted(changes, key=lambda v: abs(v["change_percent"] or 0), reverse=True),
    }
