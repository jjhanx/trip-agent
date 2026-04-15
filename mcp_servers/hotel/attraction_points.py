"""일정·명소 카탈로그에서 숙소 최적화용 좌표 목록을 만든다."""

from __future__ import annotations

from typing import Any


def collect_attraction_latlngs(
    catalog: list[dict[str, Any]] | None,
    selected_itinerary: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """명소 id별 위경도. 일정에 나오는 id만 쓰고, 일정이 비어 있으면 좌표가 있는 카탈로그 전부.

    각 항목: {\"id\", \"name\", \"lat\", \"lng\"}
    """
    cat = catalog if isinstance(catalog, list) else []
    if not cat and isinstance(selected_itinerary, dict):
        nested = selected_itinerary.get("itinerary_attraction_catalog")
        if isinstance(nested, list):
            cat = nested
    by_id: dict[str, dict[str, Any]] = {}
    for a in cat:
        if not isinstance(a, dict):
            continue
        aid = str(a.get("id") or "").strip()
        if not aid:
            continue
        lat, lng = a.get("attr_lat"), a.get("attr_lng")
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            continue
        by_id[aid] = {
            "id": aid,
            "name": str(a.get("name") or "").strip() or aid,
            "lat": float(lat),
            "lng": float(lng),
        }

    itin = selected_itinerary if isinstance(selected_itinerary, dict) else {}
    want_ids: set[str] = set()

    rp = itin.get("route_plan")
    if isinstance(rp, dict):
        for row in rp.get("daily_schedule") or []:
            if not isinstance(row, dict):
                continue
            for k in ("morning_attraction_id", "afternoon_attraction_id"):
                v = row.get(k)
                if v:
                    want_ids.add(str(v))
            for eid in row.get("extra_attraction_ids") or []:
                want_ids.add(str(eid))

    for row in itin.get("daily_plan") or []:
        if not isinstance(row, dict):
            continue
        for k in ("morning_attraction_id", "afternoon_attraction_id"):
            v = row.get(k)
            if v:
                want_ids.add(str(v))
        for eid in row.get("extra_attraction_ids") or []:
            want_ids.add(str(eid))

    if want_ids:
        out = [by_id[i] for i in sorted(want_ids) if i in by_id]
        return out

    return list(by_id.values())
