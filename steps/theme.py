"""주식 테마 단위 브리핑 — 오늘 움직인 테마의 핵심 이슈를 기사로 정리한다.

종목 하나하나를 좇는 대신 **테마**를 단위로 본다. 개별 종목 뉴스는 파편적이지만,
같은 테마 종목들의 기사를 모아 놓으면 그날 시장을 움직인 이슈가 드러난다.

- 테마 목록·편입종목: 네이버 금융 테마별 시세 (공개 HTML, 인증키 없음)
  편입 사유까지 딸려오므로 claude 가 테마 성격을 오해할 여지가 준다.
- 기사: 테마 주도 종목들의 뉴스를 모아 중복 제거 (stocknews)
- 요약: 테마당 claude 1회. 이슈 3줄 + 방향 판정.

테마 하나가 실패해도 그 테마만 빠진다.
"""

from __future__ import annotations

import html
import re
from typing import Any

import requests

from . import claude_cli, stocknews
from .common import PipelineError, extract_json, last_close, load_prompt, tidy_line

_LIST_URL = "https://finance.naver.com/sise/theme.naver"
_DETAIL_URL = "https://finance.naver.com/sise/sise_group_detail.naver"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/537.36"}

_VALID_DIR = {"긍정", "부정", "중립"}

_THEME_ROW = re.compile(
    r'<td class="col_type1"><a href="[^"]*no=(\d+)">([^<]+)</a></td>(.*?)</tr>', re.S)
_PCT = re.compile(r'col_type[23]">\s*<span[^>]*>\s*([-+\d.]+)%', re.S)
_STOCK_ROW = re.compile(
    r'<div class="name_area"><a href="/item/main\.naver\?code=([A-Z0-9]+)"[^>]*>([^<]+)</a>'
    r'(.*?)(?=<div class="name_area">|</tbody>)', re.S)
_REASON = re.compile(r'<p class="info_txt">(.*?)</p>', re.S)
_NUM_TD = re.compile(r'<td class="number"[^>]*>(.*?)</td>', re.S)


def _clean(text: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))).strip()


def _to_float(value: str) -> float | None:
    try:
        return float(value.replace(",", "").replace("%", "").replace("+", "").strip())
    except (TypeError, ValueError):
        return None


def fetch_themes(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """테마 목록(기본 정렬 = 전일대비 등락률 내림차순). 실패하면 빈 리스트."""
    conf = cfg.get("theme", {}) or {}
    pages = int(conf.get("list_pages", 1))
    out: list[dict[str, Any]] = []
    for page in range(1, pages + 1):
        try:
            resp = requests.get(_LIST_URL, headers=_UA, params={"page": page}, timeout=15)
            resp.raise_for_status()
            resp.encoding = "euc-kr"  # 네이버 금융은 euc-kr
        except Exception as e:
            print(f"[theme] 테마 목록 {page}쪽 수집 실패 — 건너뜀: {e}")
            continue
        for no, name, body in _THEME_ROW.findall(resp.text):
            pcts = _PCT.findall(body)
            ratio = _to_float(pcts[0]) if pcts else None
            out.append({
                "no": no,
                "name": _clean(name),
                "ratio": ratio,
                "ratio_3d": _to_float(pcts[1]) if len(pcts) > 1 else None,
                "trend": "up" if (ratio or 0) > 0 else "down" if (ratio or 0) < 0 else "flat",
            })
    print(f"[theme] 테마 {len(out)}개 수집")
    return out


def fetch_stocks(no: str, limit: int) -> list[dict[str, Any]]:
    """테마 편입종목(등락률 높은 순). 편입 사유도 함께 가져온다."""
    try:
        resp = requests.get(_DETAIL_URL, headers=_UA,
                            params={"type": "theme", "no": no}, timeout=15)
        resp.raise_for_status()
        resp.encoding = "euc-kr"
    except Exception as e:
        print(f"[theme] 테마 {no} 편입종목 수집 실패 — 건너뜀: {e}")
        return []

    out = []
    for code, name, body in _STOCK_ROW.findall(resp.text):
        nums = [_clean(n) for n in _NUM_TD.findall(body)]
        reason = _REASON.search(body)
        # 숫자 칸 순서: 현재가·전일비·등락률·매수호가·매도호가·거래량…
        ratio = _to_float(nums[2]) if len(nums) > 2 else None
        out.append({
            "code": code,
            "name": _clean(name),
            "price": nums[0] if nums else "",
            "ratio": ratio,
            "trend": "up" if (ratio or 0) > 0 else "down" if (ratio or 0) < 0 else "flat",
            "reason": _clean(reason.group(1)) if reason else "",
        })
    out.sort(key=lambda s: s["ratio"] if s["ratio"] is not None else -999, reverse=True)
    return out[:limit]


def gather_news(cfg: dict[str, Any], stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """테마 주도 종목들의 기사를 모아 중복 제거(최신순)."""
    conf = cfg.get("theme", {}) or {}
    since = last_close(cfg)
    per_stock = int(conf.get("news_per_stock", 3))

    by_url: dict[str, dict[str, Any]] = {}
    for stock in stocks:
        for article in stocknews.fetch(stock["code"], since=since, limit=per_stock):
            by_url.setdefault(article["url"], {**article, "stock": stock["name"]})
    items = sorted(by_url.values(), key=lambda a: a["published"], reverse=True)
    return items[: int(conf.get("max_news", 8))]


def _stock_line(stock: dict[str, Any]) -> str:
    """claude 에 넘길 편입종목 한 줄: 이름(코드) 등락률 — 편입 사유."""
    ratio = stock.get("ratio")
    move = f" {ratio:+.2f}%" if isinstance(ratio, (int, float)) else ""
    reason = f" — {stock['reason'][:90]}" if stock.get("reason") else ""
    return f"- {stock['name']}({stock['code']}){move}{reason}"


def summarize(cfg: dict[str, Any], theme: dict[str, Any], stocks: list[dict[str, Any]],
              news: list[dict[str, Any]]) -> dict[str, Any] | None:
    """테마 하나를 기사 근거로 요약 + 방향 판정. 실패하면 None(그 테마만 빠짐)."""
    conf = cfg.get("theme", {}) or {}
    articles = "\n\n".join(
        f"{n}. ({a['press']} / {a['stock']}) {a['title']}\n{a['snippet']}"
        for n, a in enumerate(news, 1)
    )
    listed = "\n".join(_stock_line(s) for s in stocks)
    ratio = theme.get("ratio")
    move = f"{ratio:+.2f}%" if isinstance(ratio, (int, float)) else "정보 없음"
    try:
        prompt = load_prompt(cfg, "theme.txt").format(
            theme=theme["name"], move=move, stocks=listed, articles=articles)
        result = extract_json(claude_cli.ask(cfg, prompt))
        if not isinstance(result, dict):
            raise PipelineError(f"요약 형식 오류: {result!r}")
        lines = result.get("lines")
        if not isinstance(lines, list) or not lines:
            raise PipelineError(f"요약 줄 오류: {result!r}")
    except Exception as e:
        print(f"[theme] {theme['name']} 요약 실패 — 건너뜀: {e}")
        return None

    direction = result.get("direction", "중립")
    if direction not in _VALID_DIR:
        direction = "중립"
    return dict(
        theme,
        direction=direction,
        lines=[tidy_line(str(l)) for l in lines[: int(conf.get("summary_lines", 3))]],
        stocks=stocks[: int(conf.get("show_stocks", 5))],
        sources=news[: int(conf.get("show_in_report", 3))],
    )


def pick(cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(전체 테마 목록, 요약된 상위 테마들). 요약은 테마당 claude 1회."""
    conf = cfg.get("theme", {}) or {}
    themes = fetch_themes(cfg)
    if not conf.get("enabled", True) or not themes:
        return themes, []

    want = int(conf.get("top_n", 5))
    stock_limit = int(conf.get("stocks_per_theme", 5))
    excluded = [str(k) for k in (conf.get("exclude_keywords") or [])]
    # 기사가 거의 없는 날(연휴 직후 등) 테마 목록 전체를 훑으면 편입종목·뉴스
    # 요청이 수백 건으로 불어난다. 몇 개까지만 들여다볼지 상한을 둔다.
    max_scan = int(conf.get("max_scan", 15))

    out, scanned = [], 0
    for theme in themes:
        if len(out) >= want or scanned >= max_scan:
            break
        # 신규상장·SPAC 같은 건 '이슈 테마'가 아니라 상장 형태에 따른 묶음이라
        # 공통 재료가 없다. 요약해봐야 "개별 종목 이슈"라는 결론만 나오므로
        # claude 를 부르기 전에 거른다.
        if any(k in theme["name"] for k in excluded):
            print(f"[theme] {theme['name']} — 제외 대상(이슈 테마 아님)")
            continue
        scanned += 1
        stocks = fetch_stocks(theme["no"], stock_limit)
        if not stocks:
            continue
        news = gather_news(cfg, stocks)
        if not news:
            # 근거 기사가 없으면 이슈를 쓸 수 없다. 다음 테마로 넘어간다.
            print(f"[theme] {theme['name']} — 최근 기사 없어 건너뜀")
            continue
        print(f"[theme] 요약 ({len(out) + 1}/{want}) {theme['name']} "
              f"— 종목 {len(stocks)} · 기사 {len(news)}건")
        summarized = summarize(cfg, theme, stocks, news)
        if summarized:
            out.append(summarized)
    print(f"[theme] 정리한 테마 {len(out)}개")
    return themes, out
