"""API 사용량 추적 및 무료 한도 관리."""

import json
from datetime import datetime
from pathlib import Path

# 무료 한도 (초과 전에 중단)
LIMITS = {
    "amadeus": {"monthly": 1800, "warn_at": 1500},  # 2000 중 200 여유
    "kiwi": {"per_minute": 90, "warn_at": 70},  # 100 중 10 여유
    "rapidapi": {"monthly": 90, "warn_at": 70},  # 100 중 10 여유
}

_USAGE_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "flight_api_usage.json"


def _ensure_data_dir():
    _USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_usage() -> dict:
    _ensure_data_dir()
    if not _USAGE_FILE.exists():
        return {"amadeus": [], "kiwi": [], "rapidapi": [], "warnings_shown": []}
    try:
        with open(_USAGE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"amadeus": [], "kiwi": [], "rapidapi": [], "warnings_shown": []}


def _save_usage(data: dict):
    _ensure_data_dir()
    with open(_USAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _current_month() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def _current_minute() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M")


def can_use_amadeus() -> tuple[bool, str | None]:
    """(사용가능여부, 경고메시지)"""
    data = _load_usage()
    month = _current_month()
    count = sum(1 for t in data.get("amadeus", []) if t.startswith(month))
    limit = LIMITS["amadeus"]["monthly"]
    warn_at = LIMITS["amadeus"]["warn_at"]
    if count >= limit:
        return False, f"Amadeus 월 한도({limit}회) 초과. Mock 데이터만 사용됩니다."
    if count >= warn_at:
        return True, f"Amadeus 한도 경고: {count}/{limit}회 사용됨."
    return True, None


def can_use_kiwi() -> tuple[bool, str | None]:
    data = _load_usage()
    minute = _current_minute()
    count = sum(1 for t in data.get("kiwi", []) if t == minute)
    limit = LIMITS["kiwi"]["per_minute"]
    warn_at = LIMITS["kiwi"]["warn_at"]
    if count >= limit:
        return False, f"Kiwi 분당 한도({limit}회) 초과. 잠시 후 다시 시도해 주세요."
    if count >= warn_at:
        return True, f"Kiwi 분당 한도 경고: {count}/{limit}회 사용됨."
    return True, None


def can_use_rapidapi() -> tuple[bool, str | None]:
    data = _load_usage()
    month = _current_month()
    count = sum(1 for t in data.get("rapidapi", []) if t.startswith(month))
    limit = LIMITS["rapidapi"]["monthly"]
    warn_at = LIMITS["rapidapi"]["warn_at"]
    if count >= limit:
        return False, f"RapidAPI 월 한도({limit}회) 초과. Mock 데이터만 사용됩니다."
    if count >= warn_at:
        return True, f"RapidAPI 한도 경고: {count}/{limit}회 사용됨."
    return True, None


def record_amadeus():
    data = _load_usage()
    data.setdefault("amadeus", []).append(_current_minute())
    data["amadeus"] = data["amadeus"][-10000:]  # 최근 1만 건만 유지
    _save_usage(data)


def record_kiwi():
    data = _load_usage()
    data.setdefault("kiwi", []).append(_current_minute())
    data["kiwi"] = data["kiwi"][-5000:]
    _save_usage(data)


def record_rapidapi():
    data = _load_usage()
    data.setdefault("rapidapi", []).append(_current_minute())
    data["rapidapi"] = data["rapidapi"][-5000:]
    _save_usage(data)


def get_usage_summary() -> dict:
    """현재 사용량 요약."""
    data = _load_usage()
    month = _current_month()
    minute = _current_minute()
    return {
        "amadeus": {
            "month": sum(1 for t in data.get("amadeus", []) if t.startswith(month)),
            "limit": LIMITS["amadeus"]["monthly"],
        },
        "kiwi": {
            "per_minute": sum(1 for t in data.get("kiwi", []) if t == minute),
            "limit": LIMITS["kiwi"]["per_minute"],
        },
        "rapidapi": {
            "month": sum(1 for t in data.get("rapidapi", []) if t.startswith(month)),
            "limit": LIMITS["rapidapi"]["monthly"],
        },
    }
