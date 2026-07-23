"""1단계: 구글 트렌드에서 국내 상장사 관련 검색어를 찾는다.

RSS 는 시드 키워드 없이 그 나라 전체의 실시간 인기 검색어를 돌려준다.
그중 어떤 것이 상장사와 연결되는지는 Claude 가 판단한다
(인물·제품·사건 → 종목 연결은 규칙으로 못 푼다).

트렌드는 '가산점'이지 필수 입력이 아니다 — 주식 관련 검색어가 하나도
없는 날도 정상이며, 그날은 공시 중요도만으로 선정한다.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import requests

from . import claude_cli
from .common import extract_json, load_prompt

_RSS_URL = "https://trends.google.com/trending/rss"


def fetch_titles(cfg: dict[str, Any]) -> list[str]:
    titles: list[str] = []
    for geo in cfg["trends"]["geos"]:
        try:
            resp = requests.get(_RSS_URL, params={"geo": geo}, timeout=15)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            found = [
                t.strip()
                for item in root.iter("item")
                if (t := item.findtext("title")) and t.strip()
            ]
            titles.extend(found)
            print(f"[trends] RSS({geo}): 검색어 {len(found)}개")
        except Exception as e:
            print(f"[trends] RSS({geo}) 실패 — 건너뜀: {e}")
    return list(dict.fromkeys(titles))


def extract_stocks(cfg: dict[str, Any], titles: list[str]) -> list[dict[str, Any]]:
    """검색어 중 국내 상장사와 연결되는 것만 Claude 로 추출."""
    if not titles:
        return []
    prompt = load_prompt(cfg, "trends_stocks.txt").format(
        candidates="\n".join(f"- {t}" for t in titles)
    )
    result = extract_json(claude_cli.ask(cfg, prompt))
    if not isinstance(result, list):
        print(f"[trends] 추출 결과가 배열이 아님 — 무시: {type(result)}")
        return []
    picked = [
        r for r in result
        if isinstance(r, dict) and r.get("keyword") and r.get("corp_name")
    ]
    for p in picked:
        print(f"[trends] 주식 관련: {p['keyword']} → {p['corp_name']} ({p.get('reason', '')})")
    if not picked:
        print("[trends] 주식 관련 검색어 없음 (정상 — 공시 중요도로만 선정)")
    return picked


def run(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    return extract_stocks(cfg, fetch_titles(cfg))
