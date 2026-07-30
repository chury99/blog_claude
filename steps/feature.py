"""오늘의 특징주 — 인기 검색 종목의 뉴스를 종목별로 요약(방향 판정 포함).

공시(DART) 기반 브리핑을 뉴스 기반으로 바꾸면서 생긴 단계다. 다룰 종목은 예전과
같이 '네이버 인기 검색 종목'으로 정해지고, 근거만 공시에서 뉴스로 바뀌었다.
공시와 달리 뉴스는 종목마다 매일 나오므로, 최근 기사가 있는 종목만 고른다.

기사는 네이버 종목 뉴스 API(공개, 인증키 없음)에서 받는다. 본문 발췌가 140자쯤
딸려오는데 제목과 합치면 방향 판정에는 충분하다.

종목 하나가 실패해도 그 종목만 빠진다 — 한 종목 때문에 브리핑 전체를 거를 이유가 없다.
"""

from __future__ import annotations

from typing import Any

from . import claude_cli, stocknews
from .common import PipelineError, extract_json, last_close, load_prompt, tidy_line

_VALID_DIR = {"긍정", "부정", "중립"}


def fetch_news(cfg: dict[str, Any], code: str) -> list[dict[str, Any]]:
    """종목 하나의 최근 기사. 실패하면 빈 리스트."""
    conf = cfg.get("feature", {}) or {}
    return stocknews.fetch(code, since=last_close(cfg), limit=int(conf.get("max_news", 5)))


def summarize(cfg: dict[str, Any], stock: dict[str, Any],
              news: list[dict[str, Any]]) -> dict[str, Any] | None:
    """종목 하나를 기사 근거로 요약 + 방향 판정. 실패하면 None(그 종목만 빠짐)."""
    articles = "\n\n".join(
        f"{n}. ({a['press']}) {a['title']}\n{a['snippet']}"
        for n, a in enumerate(news, 1)
    )
    ratio = stock.get("ratio")
    move = f"{ratio:+.2f}%" if isinstance(ratio, (int, float)) else "정보 없음"
    try:
        prompt = load_prompt(cfg, "feature.txt").format(
            name=stock["name"], code=stock["code"], price=stock.get("price") or "정보 없음",
            move=move, articles=articles,
        )
        result = extract_json(claude_cli.ask(cfg, prompt))
        if not isinstance(result, dict):
            raise PipelineError(f"요약 형식 오류: {result!r}")
        lines = result.get("lines")
        if not isinstance(lines, list) or not lines:
            raise PipelineError(f"요약 줄 오류: {result!r}")
    except Exception as e:
        print(f"[feature] {stock['name']} 요약 실패 — 건너뜀: {e}")
        return None

    direction = result.get("direction", "중립")
    if direction not in _VALID_DIR:
        direction = "중립"
    return dict(
        stock,
        direction=direction,
        lines=[tidy_line(str(l)) for l in lines[: int(cfg.get("feature", {}).get("summary_lines", 3))]],
        sources=news[: int(cfg.get("feature", {}).get("show_in_report", 3))],
    )


def pick(cfg: dict[str, Any], stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """인기 검색 종목 중 최근 기사가 있는 상위 N개를 요약해 돌려준다(순위순)."""
    conf = cfg.get("feature", {}) or {}
    if not conf.get("enabled", True):
        return []
    want = int(conf.get("top_n", 6))

    # 요약은 종목당 claude 1회다. 기사가 있는 종목만, 순위 높은 쪽부터 필요한 만큼만
    # 부른다 — 20개를 다 부르면 호출이 그만큼 나간다.
    candidates: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for stock in stocks:
        news = fetch_news(cfg, stock["code"])
        if news:
            candidates.append((stock, news))
        if len(candidates) >= want:
            break

    out = []
    for n, (stock, news) in enumerate(candidates, 1):
        print(f"[feature] 요약 ({n}/{len(candidates)}) {stock['name']} — 기사 {len(news)}건")
        summarized = summarize(cfg, stock, news)
        if summarized:
            out.append(summarized)
    print(f"[feature] 특징주 {len(out)}종목")
    return out
