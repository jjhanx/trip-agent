"""선택 명소 + Google Maps Directions 기반 일자별 오전·오후 배정.

항공 도착 공항(또는 목적지 공항 코드)을 출발점으로 두고, Nearest-Neighbor로 방문 순서를 잡은 뒤
날짜마다 오전·오후 슬롯에 순서대로 넣는다. 이동 시간(승용차)과 명소당 추정 체류 시간을 반영해
요약 노트·추가 방문지(extra_attraction_ids)를 채운다.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from shared.directions_parking import (
    driving_minutes_between,
    geocode_address,
    reverse_geocode_city_display_name,
)
from shared.loop_route_planner import (
    add_attraction_markers_to_static_map,
    fetch_loop_route_directions,
    pick_closest_farthest_and_order,
)
from shared.google_place_details import fetch_place_details_raw

logger = logging.getLogger(__name__)


def expand_selected_attractions_for_trip_days(
    selected_objs: list[dict[str, Any]],
    catalog: list[dict[str, Any]] | None,
    n_days: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """선택 명소만으로 하루 오전·오후 슬롯(일수×2)을 채우기에 부족하면, 미선택 카탈로그를 평점·리뷰 수 순으로 보강.

    Returns:
        (merged_attraction_dicts, auto_added_attraction_ids)
    """
    if not n_days or n_days < 1:
        return [dict(x) for x in selected_objs if isinstance(x, dict)], []
    if not catalog:
        return [dict(x) for x in selected_objs if isinstance(x, dict)], []

    slot_target = max(1, 2 * int(n_days))
    sel: list[dict[str, Any]] = [dict(x) for x in selected_objs if isinstance(x, dict)]
    sel_ids: set[str] = {str(x.get("id")) for x in sel if x.get("id")}
    if len(sel) >= slot_target:
        return sel, []

    need = slot_target - len(sel)
    candidates: list[dict[str, Any]] = []
    for a in catalog:
        if not isinstance(a, dict) or not a.get("id"):
            continue
        aid = str(a.get("id"))
        if aid in sel_ids:
            continue
        candidates.append(a)

    def _rating_key(a: dict[str, Any]) -> tuple[float, int]:
        r = float(a.get("rating") or 0.0)
        rev = int(a.get("user_ratings_total") or 0)
        return (-r, -rev)

    candidates.sort(key=_rating_key)
    seen_pid: set[str] = {str(x.get("place_id") or "").strip() for x in sel if x.get("place_id")}
    auto_added: list[str] = []

    for a in candidates:
        if need <= 0:
            break
        pid = str(a.get("place_id") or "").strip()
        if pid and pid in seen_pid:
            continue
        oid = str(a.get("id"))
        if oid in sel_ids:
            continue
        sel.append(dict(a))
        sel_ids.add(oid)
        auto_added.append(oid)
        if pid:
            seen_pid.add(pid)
        need -= 1

    return sel, auto_added


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    import math

    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _first_outbound_leg(selected_flight: dict[str, Any] | None) -> dict[str, Any] | None:
    if not selected_flight or not isinstance(selected_flight, dict):
        return None
    ob = selected_flight.get("outbound")
    if isinstance(ob, dict):
        return ob
    legs = selected_flight.get("legs")
    if isinstance(legs, list) and legs and isinstance(legs[0], dict):
        return legs[0]
    return None


def _arrival_airport_query(
    selected_flight: dict[str, Any] | None,
    destination_airport_code: str | None,
    destination: str,
) -> str:
    leg = _first_outbound_leg(selected_flight)
    if leg and isinstance(leg, dict):
        segs = leg.get("segments")
        if isinstance(segs, list) and segs:
            last = segs[-1]
            if isinstance(last, dict):
                aa = (last.get("arrival_airport") or {}) if isinstance(last.get("arrival_airport"), dict) else {}
                iata = (aa.get("id") or "").strip()
                if len(iata) >= 3:
                    return f"{iata.upper()} airport"
                nm = (aa.get("name") or "").strip()
                if nm:
                    return nm
    code = (destination_airport_code or "").strip().upper()
    if len(code) == 3:
        return f"{code} airport"
    dest = (destination or "").strip()
    if dest:
        return f"{dest} airport"
    return "airport"


def _pace_slot_budgets(pace: str) -> tuple[int, int]:
    p = (pace or "medium").strip().lower()
    if p == "relaxed":
        return (300, 280)
    if p == "packed":
        return (200, 200)
    return (240, 240)


def _estimate_visit_minutes(attr: dict[str, Any], pace: str) -> int:
    pr = attr.get("practical_details") if isinstance(attr.get("practical_details"), dict) else {}
    wh = str(pr.get("walking_hiking") or "")
    cab = str(pr.get("cable_car_lift") or "")
    cat = str(attr.get("category") or "").lower()
    base = 150 if pace == "relaxed" else 120 if pace in ("", "medium") else 100
    for pat in (
        r"(\d+)\s*[-~–]\s*(\d+)\s*(?:시간|hours?)",
        r"(\d+)\s*(?:시간|hours?)",
        r"(\d+)\s*h\b",
    ):
        m = re.search(pat, wh, re.I)
        if m:
            try:
                if m.lastindex and m.lastindex >= 2:
                    lo, hi = int(m.group(1)), int(m.group(2))
                    return min(360, max(60, (lo + hi) * 30))
                return min(360, max(60, int(m.group(1)) * 60))
            except (TypeError, ValueError):
                pass
    if cab.strip():
        base = max(base, 180)
    if any(x in cat for x in ("museum", "박물관", "gallery", "성당", "church")):
        base = max(base, 100)
    return min(300, max(45, base))


def _first_day_arrival_cut_local_minutes(selected_flight: dict[str, Any] | None, first_date: str) -> int | None:
    """첫 여행일 첫 구간 도착 시각(현지) 기준, '오전' 가용 분(대략 12:00까지). 없으면 None(종일)."""
    leg = _first_outbound_leg(selected_flight)
    if not leg:
        return None
    segs = leg.get("segments")
    if not isinstance(segs, list) or not segs:
        t = leg.get("arrival") or leg.get("arrival_time")
        arr_s = str(t or "").strip()
    else:
        last = segs[-1]
        aa = (last.get("arrival_airport") or {}) if isinstance(last, dict) else {}
        arr_s = str(aa.get("time") or last.get("arrival") or "").strip()
    if not arr_s or len(first_date) < 10:
        return None
    if arr_s[:10] != first_date[:10]:
        return None
    try:
        raw = arr_s.replace(" ", "T")
        if len(raw) == 16 and raw[10] == "T":
            raw += ":00"
        dt = datetime.fromisoformat(raw[:19])
        noon = dt.replace(hour=12, minute=0, second=0, microsecond=0)
        if dt >= noon:
            return 0
        return max(0, int((noon - dt).total_seconds() // 60))
    except Exception:
        return None


async def _ensure_coords(attr: dict[str, Any], destination: str, api_key: str) -> dict[str, Any]:
    alat = attr.get("attr_lat")
    alng = attr.get("attr_lng")
    if isinstance(alat, (int, float)) and isinstance(alng, (int, float)):
        return attr
    pid = (attr.get("place_id") or "").strip()
    if pid:
        raw = await fetch_place_details_raw(pid, api_key)
        if raw:
            loc = (raw.get("geometry") or {}).get("location") or {}
            if isinstance(loc.get("lat"), (int, float)) and isinstance(loc.get("lng"), (int, float)):
                attr["attr_lat"] = float(loc["lat"])
                attr["attr_lng"] = float(loc["lng"])
                return attr
    q = f"{(attr.get('name') or '').strip()} {destination}".strip()
    g = await geocode_address(q, api_key)
    if g:
        la, lo, _ = g
        attr["attr_lat"] = float(la)
        attr["attr_lng"] = float(lo)
    return attr


def _nn_order(start_lat: float, start_lng: float, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    remaining = [x for x in items if isinstance(x, dict)]
    ordered: list[dict[str, Any]] = []
    cur_lat, cur_lng = start_lat, start_lng
    while remaining:
        best_i = -1
        best_d = float("inf")
        for i, a in enumerate(remaining):
            alat, alng = a.get("attr_lat"), a.get("attr_lng")
            if not isinstance(alat, (int, float)) or not isinstance(alng, (int, float)):
                best_d = 0.0
                best_i = i
                break
            d = _haversine_km(cur_lat, cur_lng, float(alat), float(alng))
            if d < best_d:
                best_d = d
                best_i = i
        if best_i < 0:
            break
        pick = remaining.pop(best_i)
        ordered.append(pick)
        if isinstance(pick.get("attr_lat"), (int, float)) and isinstance(pick.get("attr_lng"), (int, float)):
            cur_lat, cur_lng = float(pick["attr_lat"]), float(pick["attr_lng"])
    return ordered


async def enrich_route_bundle_with_directions_schedule(
    route_bundle: dict[str, Any],
    selected_objs: list[dict[str, Any]],
    *,
    destination: str,
    origin: str,
    dates: list[str],
    selected_flight: dict[str, Any] | None,
    destination_airport_code: str | None,
    preference: dict[str, Any],
    api_key: str,
    local_transport: str,
    auto_filled_attraction_ids: list[str] | None = None,
) -> dict[str, Any]:
    """route_plan.daily_schedule 등을 Directions 기반으로 채우거나 덮어쓴다."""
    if not (api_key or "").strip() or not dates:
        return route_bundle
    pace = (preference or {}).get("pace") or "medium"
    am_budget, pm_budget = _pace_slot_budgets(pace)

    anchor_q = _arrival_airport_query(selected_flight, destination_airport_code, destination)
    start_geo = await geocode_address(anchor_q, api_key)
    if not start_geo:
        start_geo = await geocode_address(destination, api_key)
    if not start_geo:
        logger.warning("itinerary_route_schedule: could not geocode start anchor %s", anchor_q)
        return route_bundle
    s_lat, s_lng, start_label = float(start_geo[0]), float(start_geo[1]), start_geo[2]

    enriched: list[dict[str, Any]] = []
    for a in selected_objs:
        if not isinstance(a, dict):
            continue
        enriched.append(await _ensure_coords(dict(a), destination, api_key))

    ordered: list[dict[str, Any]] = []
    loop_route_meta: dict[str, Any] = {}
    try:
        ordered, loop_meta = await pick_closest_farthest_and_order(
            s_lat, s_lng, enriched, api_key
        )
        loop_route_meta = dict(loop_meta)
        if ordered:
            dir_meta = await fetch_loop_route_directions(
                s_lat, s_lng, ordered[0], ordered[-1], api_key
            )
            loop_route_meta.update(dir_meta)
            su = loop_route_meta.get("static_map_url")
            loop_route_meta["static_map_url"] = add_attraction_markers_to_static_map(
                su, enriched, api_key
            )
            loop_route_meta["ordered_attraction_ids"] = [
                str(x.get("id")) for x in ordered if x.get("id")
            ]
            loop_route_meta["route_kind_ko"] = (
                "도착 앵커 → (승용차 기준) 가장 가까운 명소 → 가장 먼 명소 → 앵커로 돌아오는 루프. "
                "명소 방문 순서는 이 루프의 주 구간(가까운 쪽→먼 쪽)에 사영해 정렬했습니다."
            )
    except Exception as e:
        logger.warning("loop_route_planner failed, falling back to NN: %s", e)
        ordered = []

    if not ordered:
        ordered = _nn_order(s_lat, s_lng, enriched)
    if not ordered:
        return route_bundle

    # 이동 구간(분): anchor -> a0, a0->a1, ...
    legs_min: list[int | None] = []
    prev_lat, prev_lng = s_lat, s_lng
    for a in ordered:
        alat = a.get("attr_lat")
        alng = a.get("attr_lng")
        if not isinstance(alat, (int, float)) or not isinstance(alng, (int, float)):
            legs_min.append(None)
            continue
        m = await driving_minutes_between(api_key, prev_lat, prev_lng, float(alat), float(alng))
        legs_min.append(m)
        prev_lat, prev_lng = float(alat), float(alng)

    visit_m = [_estimate_visit_minutes(a, pace) for a in ordered]

    n_days = len(dates)
    id_to_name = {str(o.get("id")): str(o.get("name") or "") for o in ordered if o.get("id")}
    id_to_visit = {str(o.get("id")): visit_m[i] for i, o in enumerate(ordered) if o.get("id")}

    cut = _first_day_arrival_cut_local_minutes(selected_flight, dates[0] if dates else "")
    seq_idx = 0
    daily_schedule: list[dict[str, Any]] = []

    id_to_coord: dict[str, tuple[float, float]] = {}
    for o in ordered:
        oid = str(o.get("id") or "").strip()
        if not oid:
            continue
        alat, alng = o.get("attr_lat"), o.get("attr_lng")
        if isinstance(alat, (int, float)) and isinstance(alng, (int, float)):
            id_to_coord[oid] = (float(alat), float(alng))

    for di, d in enumerate(dates):
        am_b, pm_b = am_budget, pm_budget
        can_morning = not (di == 0 and cut == 0)
        morning_id: str | None = None
        afternoon_id: str | None = None
        morning_drive: int | None = None
        between_drive: int | None = None
        extra_ids: list[str] = []

        if can_morning and seq_idx < len(ordered):
            morning_id = str(ordered[seq_idx].get("id") or "") or None
            morning_drive = legs_min[seq_idx] if seq_idx < len(legs_min) else None
            seq_idx += 1

        if seq_idx < len(ordered):
            afternoon_id = str(ordered[seq_idx].get("id") or "") or None
            between_drive = legs_min[seq_idx] if seq_idx < len(legs_min) else None
            seq_idx += 1

        if di == n_days - 1 and seq_idx < len(ordered):
            extra_ids = [
                str(ordered[j].get("id"))
                for j in range(seq_idx, len(ordered))
                if ordered[j].get("id")
            ]
            seq_idx = len(ordered)

        def _name_for(pid: str | None) -> str:
            return id_to_name.get(str(pid), "") if pid else ""

        parts: list[str] = []
        mode_note = "승용차" if (local_transport or "") == "rental_car" else "차량(도로 검색 기준)"
        if di == 0:
            parts.append(f"출발 기준: {start_label} ({anchor_q})")
            if cut == 0:
                parts.append("첫날 항공 도착이 오후로 보여 오전 명소는 비웁니다.")
        if morning_id:
            md = morning_drive
            vm = id_to_visit.get(morning_id, 120)
            parts.append(
                f"오전 {_name_for(morning_id)} — 이동 약 {md if md is not None else '?'}분 ({mode_note}), "
                f"체류 약 {vm}분"
            )
        if afternoon_id:
            bd = between_drive
            vm = id_to_visit.get(afternoon_id, 120)
            parts.append(
                f"오후 {_name_for(afternoon_id)} — 이동 약 {bd if bd is not None else '?'}분 ({mode_note}), "
                f"체류 약 {vm}분"
            )
        if extra_ids:
            parts.append(
                "추가 방문(동선·체류는 현지 상황에 맞게 조정): "
                + ", ".join(_name_for(x) for x in extra_ids if _name_for(x))
            )

        route_notes = " · ".join(parts) if parts else ""

        overnight_hint = f"{destination} 인근 (동선·체류 시간 기준)"
        day_coords: list[tuple[float, float]] = []
        for pid in (
            [morning_id, afternoon_id]
            + ([str(x) for x in extra_ids] if extra_ids else [])
        ):
            if not pid:
                continue
            key = str(pid)
            if key in id_to_coord:
                day_coords.append(id_to_coord[key])
        if day_coords:
            clat = sum(c[0] for c in day_coords) / len(day_coords)
            clng = sum(c[1] for c in day_coords) / len(day_coords)
            city = await reverse_geocode_city_display_name(clat, clng, api_key)
            if city:
                overnight_hint = f"{city} 인근 · 당일 방문 구역 중심"

        warn = ""
        if morning_id and afternoon_id:
            m_visit = id_to_visit.get(morning_id, 120)
            p_visit = id_to_visit.get(afternoon_id, 120)
            travel_am = morning_drive or 0
            travel_mid = between_drive or 0
            if travel_am + m_visit > am_b + 30:
                warn = "오전 슬롯이 설정한 여유 시간보다 빡빡할 수 있습니다. 오후 일정과 조정을 권장합니다."
            elif travel_am + m_visit + travel_mid + p_visit > am_b + pm_b + 60:
                warn = "당일 이동·체류 합이 길어 집중 관광일 수 있습니다."

        row: dict[str, Any] = {
            "date": d,
            "morning_attraction_id": morning_id,
            "afternoon_attraction_id": afternoon_id,
            "extra_attraction_ids": extra_ids,
            "overnight_area_hint": overnight_hint,
            "route_notes": route_notes,
            "morning_drive_from_previous_minutes": morning_drive,
            "between_am_pm_drive_minutes": between_drive,
            "schedule_pace_warning": warn,
        }
        daily_schedule.append(row)

    def _centroid_for_ids(ids: list[str | None]) -> tuple[float, float] | None:
        pts: list[tuple[float, float]] = []
        for i in ids:
            if not i:
                continue
            key = str(i)
            if key in id_to_coord:
                pts.append(id_to_coord[key])
        if not pts:
            return None
        return (
            sum(p[0] for p in pts) / len(pts),
            sum(p[1] for p in pts) / len(pts),
        )

    for di in range(1, len(daily_schedule)):
        prev = daily_schedule[di - 1]
        cur = daily_schedule[di]
        prev_ids: list[str | None] = [
            prev.get("morning_attraction_id"),
            prev.get("afternoon_attraction_id"),
            *([str(x) for x in (prev.get("extra_attraction_ids") or [])]),
        ]
        cur_ids = [cur.get("morning_attraction_id"), cur.get("afternoon_attraction_id")]
        pc = _centroid_for_ids(prev_ids)
        cc = _centroid_for_ids(cur_ids)
        if not pc or not cc:
            continue
        gap = await driving_minutes_between(api_key, pc[0], pc[1], cc[0], cc[1])
        cur["approx_drive_previous_day_region_to_today_minutes"] = gap
        cur["suggests_hotel_relocation"] = bool(gap is not None and gap > 60)

    rp = dict(route_bundle.get("route_plan") or {})
    rp["daily_schedule"] = daily_schedule
    auto_ids = [str(x) for x in (auto_filled_attraction_ids or []) if x]
    if auto_ids:
        rp["auto_filled_attraction_ids"] = auto_ids
    slot_n = max(1, 2 * n_days)
    fill_note = ""
    if auto_ids:
        fill_note = (
            f"선택만으로는 일자별 오전·오후 슬롯(최대 {slot_n}곳)을 채우기에 부족해, "
            f"고르지 않은 후보 중 평점·리뷰 수 순으로 {len(auto_ids)}곳을 자동 포함했습니다. "
        )
    route_note = (
        f"{start_label} 도착 후 루프·경로상 정렬로 명소를 순서대로 방문합니다. "
        if loop_route_meta.get("closest_attraction_id")
        else f"{start_label} 도착 후 Nearest-Neighbor 동선으로 명소를 순서대로 방문합니다. "
    )
    rp["lodging_strategy"] = (
        fill_note
        + route_note
        + f"여행 속도({pace}) 기준 오전·오후 가용 시간을 고려했습니다. "
        "숙소는 당일 명소까지 승용차 약 60분 이내를 우선합니다(불가 시 완화). "
        + (rp.get("lodging_strategy") or "")
    ).strip()
    rp["route_start_label"] = start_label
    rp["route_start_query"] = anchor_q
    if loop_route_meta:
        rp["loop_route"] = loop_route_meta
    out = dict(route_bundle)
    out["route_plan"] = rp
    return out
