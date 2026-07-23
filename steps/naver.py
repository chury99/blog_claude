"""네이버 금융 '인기 검색 종목' 수집.

네이버는 2021년 실시간 급상승 검색어를 폐지했지만, 금융(finance.naver.com)의
인기 검색 종목은 살아 있다. 구글 범용 트렌드와 달리 '지금 투자자들이 검색하는
종목'을 종목코드까지 직접 주므로, 공시와 이름 매칭이 정확하다.
"""

from __future__ import annotations

import re
from typing import Any

import requests

_URL = "https://finance.naver.com/sise/lastsearch2.naver"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/537.36"}
# code=NNNNNN"...>종목명</a>
_ROW = re.compile(r'item/main\.naver\?code=(\d+)"[^>]*>([^<]+)</a>')


def fetch_popular_stocks(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """인기 검색 종목 [{rank, code, name}]. 실패 시 빈 리스트(파이프라인 안 죽임)."""
    if not cfg.get("naver", {}).get("enabled", True):
        return []
    try:
        resp = requests.get(_URL, headers=_UA, timeout=15)
        resp.raise_for_status()
        resp.encoding = "euc-kr"  # 네이버 금융은 euc-kr
        rows = _ROW.findall(resp.text)
    except Exception as e:
        print(f"[naver] 인기 검색 종목 수집 실패 — 건너뜀: {e}")
        return []

    top_n = cfg.get("naver", {}).get("top_n", 15)
    stocks = [
        {"rank": i, "code": code, "name": name.strip()}
        for i, (code, name) in enumerate(rows, 1)
    ][:top_n]
    print(f"[naver] 인기 검색 종목 {len(stocks)}개")
    return stocks


def popular_names(stocks: list[dict[str, Any]]) -> set[str]:
    """🔥 매칭용 — 공백 제거한 종목명 집합."""
    return {s["name"].replace(" ", "") for s in stocks}
