"""오늘의 특징주 — 제목에 '특징주'가 들어간 기사를 모아 종목별로 이슈를 정리한다.

언론사들은 급등락 종목마다 "[특징주] OO, ~에 급등" 형태의 기사를 낸다. 이걸
그대로 신호로 쓰면 그날 시장이 실제로 주목한 종목이 잡힌다. 인기 검색이나 테마
등락률처럼 간접 지표를 거치지 않는다.

파이프라인:
1. 구글 뉴스 RSS 에서 '특징주' 검색 — 네이버 금융 API·큐레이션 피드에는 특징주
   기사가 거의 올라오지 않아 여기서 찾는다(검색 결과 100건 중 30건 안팎이 해당).
2. 제목에서 종목명을 뽑아 네이버 자동완성으로 종목코드를 확인한다. 실제 종목명일
   때만 통과하므로 오탐이 걸러지고, 해외 특징주(유럽·일본 등)는 자연히 빠진다.
3. 같은 종목 기사끼리 묶는다(보통 한 종목에 여러 언론사가 쓴다).
4. 종목별로 현재가·등락률과 네이버 종목 뉴스 본문을 붙여 claude 가 이슈를 정리한다.

종목 하나가 실패해도 그 종목만 빠진다.
"""

from __future__ import annotations

import html
import re
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import requests

from . import claude_cli, stocknews
from .common import PipelineError, extract_json, last_close, load_prompt, tidy_line

_RSS = "https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
_AC = "https://ac.stock.naver.com/ac"
_QUOTE = "https://polling.finance.naver.com/api/realtime/domestic/stock/{code}"
_RISE = "https://finance.naver.com/sise/sise_rise.naver"
_FALL = "https://finance.naver.com/sise/sise_fall.naver"
_MOVER_ROW = re.compile(r'<tr>(.*?)</tr>', re.S)
_MOVER_LINK = re.compile(r'item/main\.naver\?code=([A-Z0-9]+)"[^>]*>([^<]+)</a>')
_MOVER_NUM = re.compile(r'<td class="number">(.*?)</td>', re.S)
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/537.36"}

_VALID_DIR = {"긍정", "부정", "중립"}

_ITEM = re.compile(r"<item>(.*?)</item>", re.S)
_TAG = {t: re.compile(rf"<{t}>(.*?)</{t}>", re.S) for t in ("title", "link", "pubDate", "source")}
# '[특징주]', '[ET특징주]', '[유럽 특징주]' 처럼 대괄호 안에 들어간 형태만 인정한다.
# 이래야 '특징주 기사 선행매매 적발' 같은 특징주를 다룬 기사가 걸러진다.
_BRACKET = re.compile(r"\[[^\]]*특징주[^\]]*\]")
# 이름이 아닌 조각을 버리기 위한 구분자
_SPLIT = re.compile(r"[,·…‧∙|/'\"“”‘’()\[\]<>%↑↓~\s]+")


def _text(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def _to_float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


# ── 1. 특징주 기사 수집 ────────────────────────────────────────────────────


def fetch_articles(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """구글 뉴스에서 '특징주' 기사를 모은다. 실패하면 빈 리스트."""
    conf = cfg.get("highlight", {}) or {}
    query = str(conf.get("query", "특징주"))
    skip = [str(k) for k in (conf.get("exclude_keywords") or [])]
    cutoff = last_close(cfg)

    try:
        resp = requests.get(_RSS.format(query=quote(query)), headers=_UA, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"[highlight] 특징주 기사 수집 실패: {e}")
        return []

    out = []
    for raw in _ITEM.findall(resp.text):
        title = _text(_TAG["title"].search(raw).group(1) if _TAG["title"].search(raw) else "")
        if not title:
            continue
        # 구글 뉴스 제목은 '기사제목 - 언론사' 형태다
        headline, _, press = title.rpartition(" - ")
        headline, press = (headline or title).strip(), press.strip()

        tag = _BRACKET.search(headline)
        if not tag:
            continue  # 특징주를 '다룬' 기사이지 특징주 기사가 아니다
        if any(k in tag.group(0) for k in skip):
            continue  # [유럽 특징주] 등 해외물

        published = None
        found = _TAG["pubDate"].search(raw)
        if found:
            try:
                # RSS 는 UTC 로 준다. 로컬 시각으로 맞춰야 장 마감 기준과 비교된다.
                published = parsedate_to_datetime(_text(found.group(1))) \
                    .astimezone().replace(tzinfo=None)
            except (TypeError, ValueError):
                published = None
        if published and published < cutoff:
            continue

        link = _TAG["link"].search(raw)
        out.append({
            "title": headline,
            "press": press,
            "url": _text(link.group(1)) if link else "",
            "published": published,
            "tag": tag.group(0),
        })
    print(f"[highlight] 특징주 기사 {len(out)}건 ({cutoff:%m-%d %H:%M} 이후)")
    return out


# ── 2. 제목에서 종목 찾기 ──────────────────────────────────────────────────


def _resolve(name: str, cache: dict[str, str | None]) -> str | None:
    """종목명이 실제 국내 상장 종목이면 코드를 준다. 아니면 None."""
    if name in cache:
        return cache[name]
    cache[name] = None
    try:
        resp = requests.get(_AC, headers=_UA, params={"q": name, "target": "stock"}, timeout=8)
        resp.raise_for_status()
        for item in resp.json().get("items", []):
            if item.get("name") == name and item.get("nationCode") == "KOR":
                cache[name] = item["code"]
                break
    except Exception:
        pass  # 이름 하나 못 찾는 건 흔한 일이라 조용히 넘어간다
    return cache[name]


def find_stocks(article: dict[str, Any], cache: dict[str, str | None],
                max_candidates: int = 8) -> list[tuple[str, str]]:
    """기사 제목에서 (종목명, 코드) 목록. 자동완성으로 확인된 것만."""
    tail = _BRACKET.sub(" ", article["title"])
    seen, found = set(), []
    for token in _SPLIT.split(tail):
        token = token.strip()
        if not (1 < len(token) <= 12) or token in seen:
            continue
        seen.add(token)
        if len(seen) > max_candidates:
            break
        code = _resolve(token, cache)
        if code:
            found.append((token, code))
    return found


def group_by_stock(cfg: dict[str, Any],
                   articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """기사들을 종목별로 묶는다. 기사가 많은 종목이 앞에 온다."""
    cache: dict[str, str | None] = {}
    groups: dict[str, dict[str, Any]] = {}
    for article in articles:
        for name, code in find_stocks(article, cache):
            group = groups.setdefault(code, {"code": code, "name": name, "articles": []})
            group["articles"].append(article)
    ranked = sorted(groups.values(), key=lambda g: len(g["articles"]), reverse=True)
    print(f"[highlight] 특징주로 언급된 종목 {len(ranked)}개")
    return ranked


# ── 2-1. 특징주 기사가 모자랄 때: 등락률 상위 종목의 기사로 보강 ─────────────


def fetch_movers(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """등락률 상위·하위 종목. 그날 크게 움직인 종목이 곧 특징주 후보다."""
    conf = (cfg.get("highlight", {}) or {}).get("movers", {}) or {}
    out: list[dict[str, Any]] = []
    for url, want in ((_RISE, int(conf.get("rise_n", 20))),
                      (_FALL, int(conf.get("fall_n", 20)))):
        try:
            resp = requests.get(url, headers=_UA, params={"sosok": 0}, timeout=15)
            resp.raise_for_status()
            resp.encoding = "euc-kr"  # 네이버 금융은 euc-kr
        except Exception as e:
            print(f"[highlight] 등락률 상위 수집 실패 — 건너뜀: {e}")
            continue
        picked = 0
        for block in _MOVER_ROW.findall(resp.text):
            link = _MOVER_LINK.search(block)
            if not link or picked >= want:
                continue
            nums = [_text(n) for n in _MOVER_NUM.findall(block)]
            out.append({
                "code": link.group(1),
                "name": html.unescape(link.group(2)).strip(),
                "ratio": _to_float(nums[2]) if len(nums) > 2 else None,
            })
            picked += 1
    return out


def from_movers(cfg: dict[str, Any], since: Any,
                exclude: set[str]) -> list[dict[str, Any]]:
    """등락률 상위 종목 중 구간 내 기사가 있는 것들을 특징주 후보로 만든다.

    종목 뉴스 API 는 '[마감시황] 코스피 급락' 같은 시장 전체 기사도 종목에 달아준다.
    그런 걸로 종목 이슈를 쓸 수는 없으므로 **제목에 종목명이 든 기사**를 우선하고,
    그런 기사가 없으면 후보에서 뺀다.
    """
    conf = (cfg.get("highlight", {}) or {}).get("movers", {}) or {}
    if not conf.get("enabled", True):
        return []
    per_stock = int(conf.get("news_per_stock", 5))

    out = []
    for stock in fetch_movers(cfg):
        if stock["code"] in exclude:
            continue
        articles = stocknews.fetch(stock["code"], since=since, limit=per_stock)
        named = [a for a in articles if stock["name"] in a["title"]]
        if not named:
            continue  # 종목 이름조차 안 나오는 기사뿐이면 그 종목 이슈가 아니다
        out.append({**stock, "articles": named})
    # 종목명이 제목에 든 기사가 많을수록, 그다음은 등락 폭이 클수록 앞
    out.sort(key=lambda g: (len(g["articles"]), abs(g.get("ratio") or 0)), reverse=True)
    print(f"[highlight] 등락률 상위에서 보강한 종목 {len(out)}개")
    return out


# ── 3. 시세 + 요약 ────────────────────────────────────────────────────────


def fetch_quote(code: str) -> dict[str, Any]:
    """현재가·등락률. 실패하면 빈 값(요약은 그대로 진행)."""
    try:
        resp = requests.get(_QUOTE.format(code=code), headers=_UA, timeout=10)
        resp.raise_for_status()
        data = (resp.json().get("datas") or [{}])[0]
    except Exception as e:
        print(f"[highlight] {code} 시세 조회 실패 — 등락률 없이 진행: {e}")
        return {"price": "", "ratio": None, "trend": "flat"}
    ratio = _to_float(data.get("fluctuationsRatio"))
    return {
        "price": str(data.get("closePrice") or "").strip(),
        "ratio": ratio,
        "trend": "up" if (ratio or 0) > 0 else "down" if (ratio or 0) < 0 else "flat",
        "name": str(data.get("stockName") or "").strip(),
    }


def summarize(cfg: dict[str, Any], group: dict[str, Any]) -> dict[str, Any] | None:
    """종목 하나의 이슈를 3줄로 정리 + 방향 판정. 실패하면 None."""
    conf = cfg.get("highlight", {}) or {}
    sources = group["sources"]
    articles = "\n\n".join(
        f"{n}. ({a['press']}) {a['title']}" + (f"\n{a['snippet']}" if a.get("snippet") else "")
        for n, a in enumerate(sources, 1)
    )
    ratio = group.get("ratio")
    move = f"{ratio:+.2f}%" if isinstance(ratio, (int, float)) else "정보 없음"
    try:
        prompt = load_prompt(cfg, "highlight.txt").format(
            name=group["name"], code=group["code"],
            price=group.get("price") or "정보 없음", move=move, articles=articles)
        result = extract_json(claude_cli.ask(cfg, prompt))
        if not isinstance(result, dict):
            raise PipelineError(f"요약 형식 오류: {result!r}")
        lines = result.get("lines")
        if not isinstance(lines, list) or not lines:
            raise PipelineError(f"요약 줄 오류: {result!r}")
    except Exception as e:
        print(f"[highlight] {group['name']} 요약 실패 — 건너뜀: {e}")
        return None

    direction = result.get("direction", "중립")
    if direction not in _VALID_DIR:
        direction = "중립"
    return dict(
        group,
        direction=direction,
        lines=[tidy_line(str(l)) for l in lines[: int(conf.get("summary_lines", 3))]],
        sources=sources[: int(conf.get("show_in_report", 4))],
    )


def pick(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """특징주 기사 → 종목별 이슈 정리. 요약은 종목당 claude 1회."""
    conf = cfg.get("highlight", {}) or {}
    if not conf.get("enabled", True):
        return []
    want = int(conf.get("top_n", 6))
    naver_n = int(conf.get("naver_news", 3))
    since = last_close(cfg)

    groups = group_by_stock(cfg, fetch_articles(cfg))
    # 특징주 기사는 장중에 몰려서 나온다. 07시처럼 장 마감 뒤 구간만 보는 날에는
    # 거의 안 잡히므로, 모자라면 등락률 상위 종목의 기사로 채운다.
    if len(groups) < want:
        groups += from_movers(cfg, since, {g["code"] for g in groups})
    if not groups:
        return []

    out = []
    for group in groups[:want]:
        quote_data = fetch_quote(group["code"])
        group.update({k: v for k, v in quote_data.items() if k != "name" or not group.get("name")})
        # 특징주 기사(구글)엔 본문이 없다. 네이버 종목 뉴스로 본문 근거를 보탠다.
        extra = stocknews.fetch(group["code"], since=since, limit=naver_n)
        group["sources"] = group["articles"] + extra
        print(f"[highlight] 요약 ({len(out) + 1}/{min(want, len(groups))}) {group['name']} "
              f"— 특징주 {len(group['articles'])}건 + 본문 {len(extra)}건")
        summarized = summarize(cfg, group)
        if summarized:
            out.append(summarized)
    print(f"[highlight] 정리한 종목 {len(out)}개")
    return out
