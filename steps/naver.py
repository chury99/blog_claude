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
# 한 행 = 순위 + 종목 링크 + 숫자 칸들(검색비율/현재가/전일비/등락률/거래량/…)
_ROW = re.compile(r'<td class="no">(\d+)</td>(.*?)</tr>', re.S)
_LINK = re.compile(r'item/main\.naver\?code=([A-Z0-9]+)"[^>]*>([^<]+)</a>')
_NUM = re.compile(r'<td class="number">(.*?)</td>', re.S)


def _text(chunk: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", chunk)).strip()


def _to_float(value: str) -> float | None:
    try:
        return float(value.replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _parse_rows(text: str) -> list[dict[str, Any]]:
    """행에서 종목과 시세를 뽑는다. 숫자 칸 순서: 검색비율·현재가·전일비·등락률·거래량…

    레버리지·인버스 ETN/ETF 도 그대로 담는다(종목코드에 문자가 섞여 있다).
    인기 검색에 올라온 이상 투자자가 실제로 보고 있는 대상이기 때문.
    """
    out = []
    for rank, body in _ROW.findall(text):
        link = _LINK.search(body)
        if not link:
            continue
        nums = [_text(n) for n in _NUM.findall(body)]
        ratio = _to_float(nums[3]) if len(nums) > 3 else None
        out.append({
            "rank": int(rank),
            "code": link.group(1),
            "name": link.group(2).strip(),
            "price": nums[1] if len(nums) > 1 else "",
            "ratio": ratio,
            "trend": "up" if (ratio or 0) > 0 else "down" if (ratio or 0) < 0 else "flat",
        })
    return out


def fetch_popular_stocks(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """인기 검색 종목 [{rank, code, name, price, ratio, trend}].

    실패 시 빈 리스트(파이프라인 안 죽임).
    """
    if not cfg.get("naver", {}).get("enabled", True):
        return []
    try:
        resp = requests.get(_URL, headers=_UA, timeout=15)
        resp.raise_for_status()
        resp.encoding = "euc-kr"  # 네이버 금융은 euc-kr
        rows = _parse_rows(resp.text)
    except Exception as e:
        print(f"[naver] 인기 검색 종목 수집 실패 — 건너뜀: {e}")
        return []

    stocks = rows[: cfg.get("naver", {}).get("top_n", 15)]
    print(f"[naver] 인기 검색 종목 {len(stocks)}개")
    return stocks


def popular_names(stocks: list[dict[str, Any]]) -> set[str]:
    """🔥 매칭용 — 공백 제거한 종목명 집합."""
    return {s["name"].replace(" ", "") for s in stocks}
