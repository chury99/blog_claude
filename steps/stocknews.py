"""종목 뉴스 수집 — 네이버 종목 뉴스 API(공개, 인증키 없음).

테마 이슈 정리(theme.py)와 종목별 요약(feature.py)이 같이 쓴다.
기사는 `n.news.naver.com/mnews/article/{oid}/{aid}` 로 원문이 열린다.
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any

import requests

_API = "https://api.stock.naver.com/news/stock/{code}"
_ARTICLE_URL = "https://n.news.naver.com/mnews/article/{oid}/{aid}"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/537.36"}


def _parse_dt(value: str) -> datetime | None:
    try:
        return datetime.strptime(str(value).strip(), "%Y%m%d%H%M")
    except ValueError:
        return None


def fetch(code: str, *, since: datetime, limit: int = 5) -> list[dict[str, Any]]:
    """`since` 이후 나온 종목 기사(최신순). 실패하면 빈 리스트 — 호출부를 죽이지 않는다."""
    cutoff = since
    try:
        resp = requests.get(_API.format(code=code), headers=_UA,
                            params={"pageSize": 20, "page": 1}, timeout=10)
        resp.raise_for_status()
        clusters = resp.json()
    except Exception as e:
        print(f"[news] {code} 뉴스 수집 실패 — 건너뜀: {e}")
        return []

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for cluster in clusters if isinstance(clusters, list) else []:
        for item in (cluster or {}).get("items", []):
            published = _parse_dt(item.get("datetime", ""))
            # API 가 제목·본문을 HTML 이스케이프해서 준다(&quot; 등). 여기서 풀어야
            # 렌더링 때 한 번만 이스케이프돼 화면에 &quot; 가 그대로 보이지 않는다.
            title = html.unescape(str(item.get("titleFull") or item.get("title") or "")).strip()
            oid, aid = str(item.get("officeId") or ""), str(item.get("articleId") or "")
            if not (published and title and oid and aid) or published < cutoff:
                continue
            if aid in seen:
                continue
            seen.add(aid)
            out.append({
                "title": title,
                "press": str(item.get("officeName") or "").strip(),
                "snippet": html.unescape(str(item.get("body") or "")).strip(),
                "url": _ARTICLE_URL.format(oid=oid, aid=aid),
                "published": published,
            })
    out.sort(key=lambda x: x["published"], reverse=True)
    return out[:limit]
