"""Unsplash 풍경 폴백 URL (라이선스: https://unsplash.com/license)."""

from __future__ import annotations


def unsplash_scenic_pool() -> list[tuple[str, str]]:
    """(url, credit_line) 목록."""
    q = "auto=format&fit=crop&w=800&q=80"
    return [
        (
            f"https://images.unsplash.com/photo-1506905925346-21bda4d32df4?{q}",
            "Unsplash License · 산악 풍경(예시)",
        ),
        (
            f"https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?{q}",
            "Unsplash License · 산 능선(예시)",
        ),
        (
            f"https://images.unsplash.com/photo-1501785888041-af3ef285d470?{q}",
            "Unsplash License · 호수(예시)",
        ),
        (
            f"https://images.unsplash.com/photo-1476514525535-07fb3ef4e5c1?{q}",
            "Unsplash License · 호수·산(예시)",
        ),
        (
            f"https://images.unsplash.com/photo-1519681393784-d120267933ba?{q}",
            "Unsplash License · 별·산(예시)",
        ),
        (
            f"https://images.unsplash.com/photo-1469474968028-56623f02e42e?{q}",
            "Unsplash License · 자연(예시)",
        ),
        (
            f"https://images.unsplash.com/photo-1508672019048-805c876b667e?{q}",
            "Unsplash License · 일출(예시)",
        ),
        (
            f"https://images.unsplash.com/photo-1519904981063-b0cf448d479e?{q}",
            "Unsplash License · 설산(예시)",
        ),
        (
            f"https://images.unsplash.com/photo-1511593357081-8d676c8d0502?{q}",
            "Unsplash License · 하이킹(예시)",
        ),
        (
            f"https://images.unsplash.com/photo-1441974231531-c6227db76b6e?{q}",
            "Unsplash License · 숲(예시)",
        ),
        (
            f"https://images.unsplash.com/photo-1506377295352-b31509f512aa?{q}",
            "Unsplash License · 마을·산(예시)",
        ),
        (
            f"https://images.unsplash.com/photo-1493246507139-91e005fad0d3?{q}",
            "Unsplash License · 도시·야경(예시)",
        ),
        (
            f"https://images.unsplash.com/photo-1502602898657-3e471fb7d0d5?{q}",
            "Unsplash License · 랜드마크(예시)",
        ),
        (
            f"https://images.unsplash.com/photo-1516483638261-f4dbaf036963?{q}",
            "Unsplash License · 해안(예시)",
        ),
        (
            f"https://images.unsplash.com/photo-1507525428034-b723cf961d3e?{q}",
            "Unsplash License · 해변(예시)",
        ),
        (
            f"https://images.unsplash.com/photo-1506929562872-bb421503ef21?{q}",
            "Unsplash License · 호수 반영(예시)",
        ),
    ]


def license_safe_image_for_index(idx: int) -> tuple[str, str]:
    pool = unsplash_scenic_pool()
    return pool[idx % len(pool)]
