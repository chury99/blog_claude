"""간밤 미국 증시 시황 — 주요 지수 + 뉴스 기반 흐름 요약.

한국 장이 열리기 전 아침 리포트라 미국 마감이 그날의 배경이 된다. 지수와 뉴스는
네이버 금융 세계증시 API(공개, 인증키 없음)에서 받고, 흐름 요약은 claude 가
"지수 등락 + 실제 기사 헤드라인·발췌"를 근거로 쓴다(하루 1회 호출).

지수 숫자만으로는 왜 움직였는지를 쓸 수 없다. claude 는 간밤 뉴스를 모르기
때문에, 원인은 반드시 여기서 넘긴 기사에서만 나와야 한다.

수집·요약 어느 쪽이 실패해도 예외를 올리지 않는다. 시황은 곁들이는 정보라
이것 때문에 공시 브리핑 전체를 거를 이유가 없다 — 실패하면 그 부분만 빠진다.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

import requests

from . import claude_cli
from .common import extract_json, last_close, load_prompt, tidy_line

_INDEX_API = "https://api.stock.naver.com/index/{code}/basic"
# 네이버 금융 > 뉴스 > 해외증시. 여기 기사는 일반 네이버 뉴스라 링크가 열린다
# (세계증시 API 의 로이터 기사는 내용은 좋지만 공개 퍼머링크가 없어 못 쓴다).
_NEWS_LIST = "https://finance.naver.com/news/news_list.naver"
_NEWS_PARAMS = {"mode": "LSS3D", "section_id": "101", "section_id2": "258",
                "section_id3": "403"}
_ARTICLE_URL = "https://n.news.naver.com/mnews/article/{oid}/{aid}"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/537.36"}

# 미국 시장 전체를 다루는 기사(마감 시황·금리·유가)를 아시아·개별 종목 기사보다
# 앞세운다. 해외증시 목록엔 중국·일본 기사도 섞이는데, 그게 목록을 채우면
# '간밤 미국 증시가 왜 움직였나'를 쓸 근거가 사라진다.
_US_MARKET = (
    "뉴욕증시", "뉴욕 증시", "월가", "다우", "나스닥", "S&P", "연준", "Fed",
    "미 증시", "美증시", "美 증시", "국채", "유가", "마감",
)

_ITEM = re.compile(r'class="articleSubject">\s*<a href="([^"]+)"[^>]*title="([^"]*)"')
_SUMMARY = re.compile(r'class="articleSummary">(.*?)<span class="press">', re.S)
_PRESS = re.compile(r'<span class="press">([^<]*)</span>')
_WDATE = re.compile(r'<span class="wdate">([^<]*)</span>')
_BODY = re.compile(r'<(article|div)[^>]*id="dic_area"[^>]*>(.*?)</\1>', re.S)
# 사진 설명·저작권 문구는 본문이 아니라 요약에 섞이면 곤란하다
_CAPTION = re.compile(r"\[[^\[\]]{0,60}(?:연합뉴스|로이터|AFP|재판매|DB 금지)[^\[\]]{0,60}\]")


def _to_float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


# ── 지수 ──────────────────────────────────────────────────────────────────


def _fetch_index(spec: dict[str, Any]) -> dict[str, Any] | None:
    code = str(spec.get("code", "")).strip()
    label = spec.get("label") or code
    if not code:
        return None
    try:
        resp = requests.get(
            _INDEX_API.format(code=quote(code, safe="")), headers=_UA, timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[market] {label} 지수 수집 실패 — 건너뜀: {e}")
        return None

    close = str(data.get("closePrice") or "").strip()
    ratio = _to_float(data.get("fluctuationsRatio"))
    if not close or ratio is None:
        print(f"[market] {label} 응답에 시세가 없어 건너뜀")
        return None

    # 네이버는 상승분에 부호를 안 붙인다(하락은 '-43.74'). 표시용으로 +를 채운다.
    diff = str(data.get("compareToPreviousClosePrice") or "").strip()
    if ratio > 0 and diff and not diff.startswith("+"):
        diff = f"+{diff}"

    return {
        "code": code,
        "label": spec.get("label") or data.get("indexName") or code,
        "close": close,
        "diff": diff,
        "ratio": ratio,
        "trend": "up" if ratio > 0 else "down" if ratio < 0 else "flat",
        # '2026-07-27T16:52:48-04:00' → '2026-07-27' (현지 기준 거래일)
        "traded_on": str(data.get("localTradedAt") or "")[:10],
        "closed": str(data.get("marketStatus") or "").upper() == "CLOSE",
    }


def fetch_us_indices(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """설정에 적힌 미국 지수들의 마감 시세. 실패한 지수는 빠진다."""
    conf = cfg.get("market", {}) or {}
    if not conf.get("enabled", True):
        return []
    out = [x for x in (_fetch_index(s) for s in conf.get("us_indices", []) or []) if x]
    print(f"[market] 미국 지수 {len(out)}개 수집")
    return out


# ── 뉴스 ──────────────────────────────────────────────────────────────────


def _clean(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def _us_score(title: str) -> int:
    """미국 시장 전체 기사일수록 높은 점수. 정렬에만 쓴다."""
    return sum(k in title for k in _US_MARKET)


def _parse_page(text: str) -> list[dict[str, Any]]:
    """해외증시 목록 HTML 에서 기사들을 뽑는다. 한 항목은 다음 항목 직전까지."""
    out = []
    marks = list(_ITEM.finditer(text))
    for n, m in enumerate(marks):
        href, raw_title = m.group(1), m.group(2)
        oid = re.search(r"office_id=(\d+)", href)
        aid = re.search(r"article_id=(\d+)", href)
        title = _clean(raw_title)
        if not (oid and aid and title):
            continue
        block = text[m.end(): marks[n + 1].start() if n + 1 < len(marks) else len(text)]
        summary = _SUMMARY.search(block)
        press = _PRESS.search(block)
        wdate = _WDATE.search(block)
        try:
            published = datetime.strptime(_clean(wdate.group(1)), "%Y-%m-%d %H:%M")
        except (AttributeError, ValueError):
            continue  # 날짜를 못 읽으면 묵은 기사인지 판단할 수 없다
        out.append({
            "title": title,
            "press": _clean(press.group(1)) if press else "",
            "snippet": _clean(summary.group(1)) if summary else "",
            "url": _ARTICLE_URL.format(oid=oid.group(1), aid=aid.group(1)),
            "published": published,
        })
    return out


def _fetch_body(url: str, max_chars: int) -> str:
    """기사 본문. 목록 발췌(100자 남짓)만으로는 상세한 요약을 쓸 수 없다."""
    try:
        resp = requests.get(url, headers=_UA, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"[market] 기사 본문 수집 실패 — 발췌만 씁니다: {e}")
        return ""
    found = _BODY.search(resp.text)
    if not found:
        return ""
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", found.group(2), flags=re.S)
    body = re.sub(r"<br\s*/?>", "\n", body)
    body = _CAPTION.sub("", _clean(body))
    body = re.sub(r"[ \t]+", " ", body)
    return re.sub(r"\n{2,}", "\n", body).strip()[:max_chars]


def fetch_us_news(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """해외증시 기사를 모아 중복 제거 후, 미국 시장 전체 기사를 앞세워 돌려준다."""
    conf = (cfg.get("market", {}) or {}).get("news", {}) or {}
    if not conf.get("enabled", True):
        return []

    max_items = int(conf.get("max_items", 6))
    # 국내 기사와 같은 구간(직전 거래일 장 종료 이후)을 쓴다. 미국 마감 시황은
    # 새벽 5~7시에 올라오므로 이 구간에 들어온다.
    cutoff = last_close(cfg)

    by_url: dict[str, dict[str, Any]] = {}
    for page in range(1, int(conf.get("pages", 3)) + 1):
        try:
            resp = requests.get(_NEWS_LIST, headers=_UA,
                                params={**_NEWS_PARAMS, "page": page}, timeout=15)
            resp.raise_for_status()
            resp.encoding = "euc-kr"  # 네이버 금융은 euc-kr
        except Exception as e:
            print(f"[market] 해외증시 뉴스 {page}쪽 수집 실패 — 건너뜀: {e}")
            continue
        for item in _parse_page(resp.text):
            if item["published"] < cutoff:
                continue  # 간밤 시황과 무관한 묵은 기사
            by_url.setdefault(item["url"], item)

    # 미국 시장 전체 기사 우선, 그 안에서는 최신순
    items = sorted(
        by_url.values(),
        key=lambda x: (-_us_score(x["title"]), -x["published"].timestamp()),
    )[:max_items]

    # 상위 기사만 본문까지 받는다(나머지는 발췌로 충분하고, 요청도 아낀다)
    body_max = int(conf.get("body_max_chars", 1500))
    bodies = 0
    for item in items[: int(conf.get("body_count", 3))]:
        item["body"] = _fetch_body(item["url"], body_max)
        bodies += bool(item["body"])
    print(f"[market] 미국 증시 기사 {len(items)}건 수집 (본문 {bodies}건)")
    return items


# ── 요약 ──────────────────────────────────────────────────────────────────


def summarize(cfg: dict[str, Any], indices: list[dict[str, Any]],
              news: list[dict[str, Any]]) -> str | None:
    """지수 등락과 기사를 근거로 흐름을 짧게 요약. 실패하면 None."""
    if not indices:
        return None
    if not news:
        # 근거 기사가 없으면 원인을 쓸 수 없다. 숫자만 싣는 편이 낫다.
        print("[market] 근거 기사가 없어 시황 요약을 건너뜁니다.")
        return None

    listed = "\n".join(
        f"- {i['label']}: {i['close']} ({i['diff']}, {i['ratio']:+.2f}%)" for i in indices
    )
    articles = "\n\n".join(
        f"{n}. ({a['press']}) {a['title']}\n{a.get('body') or a['snippet']}"
        for n, a in enumerate(news, 1)
    )
    try:
        prompt = load_prompt(cfg, "us_market.txt").format(indices=listed, articles=articles)
        result = extract_json(claude_cli.ask(cfg, prompt))
        summary = tidy_line(str((result or {}).get("summary", "")))
    except Exception as e:
        print(f"[market] 시황 요약 실패 — 지수 숫자만 싣습니다: {e}")
        return None
    if not summary:
        print("[market] 시황 요약이 비어 있어 지수 숫자만 싣습니다.")
        return None
    print(f"[market] 시황 요약: {summary}")
    return summary


def brief_us(cfg: dict[str, Any]) -> dict[str, Any] | None:
    """리포트에 실을 미국 시황 한 덩어리. 지수를 하나도 못 받으면 None."""
    indices = fetch_us_indices(cfg)
    if not indices:
        return None
    news = fetch_us_news(cfg)
    summary = summarize(cfg, indices, news)
    show = int((cfg.get("market", {}).get("news", {}) or {}).get("show_in_report", 3))
    return {
        "indices": indices,
        "summary": summary,
        # 요약이 무엇을 근거로 했는지 리포트에서 밝히기 위한 목록
        "sources": news[:show] if summary else [],
    }
