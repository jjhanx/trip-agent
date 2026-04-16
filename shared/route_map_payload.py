"""일정 지도(Leaflet)·숙소 그룹(이동 불필요 구간)용 페이로드."""

from __future__ import annotations

from typing import Any

# 날짜별 구분 (Leaflet circleMarker 색)
DAY_PALETTE = [
    "#e11d48",
    "#2563eb",
    "#16a34a",
    "#ca8a04",
    "#9333ea",
    "#0891b2",
    "#ea580c",
    "#4f46e5",
    "#db2777",
    "#059669",
    "#d97706",
    "#7c3aed",
]


def compute_stay_groups_from_daily_schedule(daily_schedule: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """연속된 날짜 중 `suggests_hotel_relocation`이 처음 참이 되는 날마다 새 그룹(숙소 거점 전환)."""
    rows = [r for r in daily_schedule if isinstance(r, dict) and (r.get("date") or "").strip()]
    rows.sort(key=lambda x: str(x.get("date") or "")[:10])
    if not rows:
        return []

    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for i, row in enumerate(rows):
        d = str(row.get("date") or "").strip()[:10]
        if not d:
            continue
        if current is None:
            current = {"dates": [d], "rows": [row]}
            continue
        if row.get("suggests_hotel_relocation"):
            groups.append(current)
            current = {"dates": [d], "rows": [row]}
        else:
            current["dates"].append(d)
            current["rows"].append(row)
    if current:
        groups.append(current)

    out: list[dict[str, Any]] = []
    for gi, g in enumerate(groups):
        dates = g["dates"]
        ids: list[str] = []
        seen: set[str] = set()
        for r in g["rows"]:
            for k in ("morning_attraction_id", "afternoon_attraction_id"):
                v = r.get(k)
                if v:
                    sid = str(v)
                    if sid not in seen:
                        seen.add(sid)
                        ids.append(sid)
            for eid in r.get("extra_attraction_ids") or []:
                sid = str(eid)
                if sid not in seen:
                    seen.add(sid)
                    ids.append(sid)
        df, dt = dates[0], dates[-1]
        label = f"{gi + 1}구간: {df} ~ {dt} (같은 숙소 거점으로 묶인 방문일)"
        if len(dates) == 1:
            label = f"{gi + 1}구간: {df} (단일일)"
        out.append(
            {
                "group_index": gi,
                "date_from": df,
                "date_to": dt,
                "dates": dates,
                "attraction_ids": ids,
                "label_ko": label,
            }
        )
    return out


def compute_stay_groups_from_daily_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`collect_daily_attraction_segments` 결과(날짜·points·이동 플래그)로 숙소 그룹."""
    segs = [s for s in segments if isinstance(s, dict) and (s.get("date") or "").strip()]
    segs.sort(key=lambda x: str(x.get("date") or "")[:10])
    if not segs:
        return []

    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for i, seg in enumerate(segs):
        d = str(seg.get("date") or "").strip()[:10]
        if not d:
            continue
        if current is None:
            current = {"dates": [d], "segments": [seg]}
            continue
        if seg.get("suggests_hotel_relocation"):
            groups.append(current)
            current = {"dates": [d], "segments": [seg]}
        else:
            current["dates"].append(d)
            current["segments"].append(seg)
    if current:
        groups.append(current)

    out: list[dict[str, Any]] = []
    for gi, g in enumerate(groups):
        dates = g["dates"]
        pts: list[dict[str, Any]] = []
        seen: set[str] = set()
        for s in g["segments"]:
            for p in s.get("points") or []:
                if not isinstance(p, dict):
                    continue
                pid = str(p.get("id") or "").strip()
                if pid and pid not in seen:
                    seen.add(pid)
                    pts.append(p)
        df, dt = dates[0], dates[-1]
        label = f"{gi + 1}구간: {df} ~ {dt} (같은 숙소 거점으로 묶인 방문일)"
        if len(dates) == 1:
            label = f"{gi + 1}구간: {df} (단일일)"
        out.append(
            {
                "group_index": gi,
                "date_from": df,
                "date_to": dt,
                "dates": dates,
                "points": pts,
                "label_ko": label,
                "overnight_area_hint": (g["segments"][-1] or {}).get("overnight_area_hint"),
            }
        )
    return out


def build_map_payload(
    daily_schedule: list[dict[str, Any]],
    id_to_coord: dict[str, tuple[float, float]],
    id_to_name: dict[str, str],
    overview_polyline: str | None,
) -> dict[str, Any]:
    """프론트 Leaflet용: 날짜별 색, 마커, 전체 경로 폴리라인(인코딩 문자열)."""
    rows = [r for r in daily_schedule if isinstance(r, dict) and (r.get("date") or "").strip()]
    rows.sort(key=lambda x: str(x.get("date") or "")[:10])

    date_list: list[str] = []
    for r in rows:
        d = str(r.get("date") or "").strip()[:10]
        if d and d not in date_list:
            date_list.append(d)

    day_color: dict[str, str] = {}
    for i, d in enumerate(date_list):
        day_color[d] = DAY_PALETTE[i % len(DAY_PALETTE)]

    markers: list[dict[str, Any]] = []

    def add_marker(d: str, aid: str | None, slot_ko: str) -> None:
        if not aid:
            return
        sid = str(aid)
        if sid not in id_to_coord:
            return
        lat, lng = id_to_coord[sid]
        name = (id_to_name.get(sid) or sid).strip() or sid
        dm = d[5:7] if len(d) >= 10 else d
        dd = d[8:10] if len(d) >= 10 else ""
        short = f"{dm}/{dd} {slot_ko}" if dm and dd else f"{d} {slot_ko}"
        markers.append(
            {
                "date": d,
                "attraction_id": sid,
                "slot": slot_ko,
                "lat": lat,
                "lng": lng,
                "color": day_color.get(d, DAY_PALETTE[0]),
                "label": short,
                "title": f"{short}\n{name}",
            }
        )

    for r in rows:
        d = str(r.get("date") or "").strip()[:10]
        if not d:
            continue
        add_marker(d, r.get("morning_attraction_id"), "오전")
        add_marker(d, r.get("afternoon_attraction_id"), "오후")
        for eid in r.get("extra_attraction_ids") or []:
            add_marker(d, str(eid), "추가")

    return {
        "polyline_encoded": (overview_polyline or "").strip() or None,
        "day_color_hex_by_date": day_color,
        "markers": markers,
        "day_order": date_list,
    }
