"""4단계: 네이버 인기종목 공시 브리핑을 HTML 로 렌더해 웹서버 폴더에 저장.

출력 폴더/주소는 config.yaml 의 report.web_dir / report.url_base.
저장만 하고 텔레그램 발송은 pipeline 이 한다(알림 로직을 한 곳에 모음).
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from .common import PipelineError

_CSS = """
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { font-family: -apple-system, 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
       margin: 0; padding: 24px; background: #10131a; color: #e3e6ea; line-height: 1.65; }
.wrap { max-width: 860px; margin: 0 auto; }
h1 { font-size: 23px; margin: 0 0 6px; color: #f3f5f7; }
.sub { color: #97a1af; font-size: 13px; margin-bottom: 24px; }
h2 { font-size: 17px; margin: 32px 0 12px; padding-bottom: 6px; color: #f3f5f7;
     border-bottom: 2px solid #3b82f6; }
h2#stock-top { scroll-margin-top: 14px; }
.lead { background: #1a1f29; border: 1px solid #2a303c; border-radius: 10px;
        padding: 16px 20px; margin-bottom: 8px; font-size: 14px; }
.idx { display: inline-block; background: #232a36; border: 1px solid #2a303c; border-radius: 8px;
       padding: 9px 15px; margin: 0 8px 8px 0; min-width: 148px; }
.idx .in { font-size: 12px; color: #8b93a0; }
.idx .ip { font-size: 19px; font-weight: 700; color: #f3f5f7; margin: 2px 0 1px; }
.idx .ic { font-size: 12.5px; font-weight: 600; }
.idx.up .ic { color: #f87171; }
.idx.down .ic { color: #7fb0f5; }
.idx.flat .ic { color: #aab3c0; }
.mkt { font-size: 14px; color: #cdd4de; margin-top: 4px; }
.mkt-src { margin-top: 10px; padding-top: 9px; border-top: 1px dashed #2a303c; }
.mkt-src .t { color: #6b7482; font-size: 11.5px; }
.mkt-src ul { margin: 4px 0 0; padding-left: 17px; }
.mkt-src li { color: #97a1af; font-size: 12.5px; margin: 3px 0; }
.mkt-src li a { color: #97a1af; text-decoration: none; }
.mkt-src li a:hover { color: #60a5fa; text-decoration: underline; }
.mkt-src .pr { color: #6b7482; font-size: 11.5px; }
.asof { display: block; color: #6b7482; font-size: 11.5px; margin-top: 8px; }
.stock { display: inline-block; background: #232a36; color: #cdd4de; border-radius: 8px;
         padding: 5px 11px; margin: 3px 5px 3px 0; font-size: 13px; }
.stock .rk { font-size: 11.5px; margin-left: 6px; font-weight: 700; }
.stock .rk.up { color: #f87171; }
.stock .rk.down { color: #7fb0f5; }
.stock .rk.flat { color: #8b93a0; }
.stock.has { background: #2a2113; color: #fbbf24; border: 1px solid #f59e0b; font-weight: 600; }
a.stock.has { text-decoration: none; cursor: pointer; }
a.stock.has:hover { background: #3a2c15; border-color: #fbbf24; }
.grp { margin-bottom: 22px; scroll-margin-top: 14px; }
.grp .gh { font-size: 16px; font-weight: 700; color: #f3f5f7; margin: 0 0 8px; padding-left: 2px; }
.grp .gh .grk { color: #6b7482; font-size: 13px; margin-right: 6px; }
a.gback { color: #f3f5f7; text-decoration: none; cursor: pointer; }
a.gback:hover { color: #6ee7b7; }
.card { background: #1a1f29; border: 1px solid #2a303c; border-radius: 10px;
        padding: 14px 18px; margin-bottom: 10px; }
.card.pos { border-left: 4px solid #ef4444; }
.card.neg { border-left: 4px solid #3b82f6; }
.card.neu { border-left: 4px solid #6b7482; }
.card .rn { font-size: 15px; font-weight: 700; color: #f3f5f7; margin-bottom: 9px; }
.card .rn .cd { color: #6b7482; font-size: 11.5px; font-weight: 500; margin-left: 6px; }
.px { float: right; font-size: 13px; font-weight: 600; color: #cdd4de; }
.px .pc { margin-left: 7px; }
.px .pc.up { color: #f87171; }
.px .pc.down { color: #7fb0f5; }
.px .pc.flat { color: #aab3c0; }
.dir { font-size: 12px; font-weight: 700; border-radius: 6px; padding: 1px 8px; margin-right: 8px; }
.dir.pos { background: #3a1518; color: #f87171; }
.dir.neg { background: #14243c; color: #7fb0f5; }
.dir.neu { background: #232a36; color: #aab3c0; }
ol.sum { margin: 0; padding-left: 20px; }
ol.sum li { margin: 5px 0; }
ol.sum li .lb { color: #8b93a0; font-size: 11.5px; margin-right: 4px; }
.foot { color: #6b7482; font-size: 12px; margin-top: 30px; padding-top: 14px;
        border-top: 1px solid #2a303c; }
"""

_LABELS = ["무슨 일", "세부·해석", "예상 주가 방향"]
_DIR = {"긍정": ("pos", "🔺 긍정"), "부정": ("neg", "🔻 부정"), "중립": ("neu", "⚪ 중립")}


def _move(stock: dict[str, Any]) -> str:
    """현재가 + 등락률. 국내 관행대로 상승 빨강 / 하락 파랑."""
    ratio = stock.get("ratio")
    if not isinstance(ratio, (int, float)):
        return f'<span class="px">{escape(stock.get("price") or "")}</span>'
    return (f'<span class="px">{escape(stock.get("price") or "")}'
            f'<span class="pc {stock.get("trend", "flat")}">{ratio:+.2f}%</span></span>')


def _stock_chips(stocks: list[dict[str, Any]]) -> str:
    """특징주 한 줄 훑기 — 종목명 + 등락률. 누르면 아래 이슈 요약으로 간다."""
    out = []
    for s in stocks:
        ratio = s.get("ratio")
        move = (f'<span class="rk {s.get("trend", "flat")}">{ratio:+.2f}%</span>'
                if isinstance(ratio, (int, float)) else "")
        out.append(f'<a class="stock has" href="#s{s["code"]}">{escape(s["name"])}{move}</a>')
    return "".join(out)


def _market_section(market: dict[str, Any] | None) -> str:
    """간밤 미국 증시 — 지수 카드 + 흐름 한두 줄. 데이터가 없으면 통째로 뺀다."""
    if not market or not market.get("indices"):
        return ""
    indices = market["indices"]
    cards = "".join(
        f'<div class="idx {i["trend"]}">'
        f'<div class="in">{escape(i["label"])}</div>'
        f'<div class="ip">{escape(i["close"])}</div>'
        f'<div class="ic">{escape(i["diff"])} ({i["ratio"]:+.2f}%)</div>'
        f"</div>"
        for i in indices
    )
    summary = market.get("summary")
    summary_html = f'<div class="mkt">{escape(summary)}</div>' if summary else ""

    src_html = _sources(market.get("sources") or [], "요약 근거 기사")
    traded = next((i["traded_on"] for i in indices if i.get("traded_on")), "")
    state = "마감" if all(i.get("closed") for i in indices) else "장중"
    asof = f'<span class="asof">미국 현지 {traded} {state} 기준 · 네이버 금융</span>' if traded else ""

    return (
        f'<h2>🌏 간밤 미국 증시</h2>\n'
        f'<div class="lead"><div>{cards}</div>{summary_html}{src_html}{asof}</div>\n'
    )


def _market_note(market: dict[str, Any] | None) -> str:
    """시황 요약의 근거를 밝히는 고지. 지수 등락 외의 정보는 쓰지 않았다."""
    if not market or not market.get("summary"):
        return ""
    return ("간밤 미국 증시 시황은 위 지수 등락과 함께 표시한 기사만을 근거로 "
            "정리한 것으로, 기사 원문과 다를 수 있습니다. ")


def _sources(items: list[dict[str, Any]], label: str) -> str:
    """요약이 무엇을 보고 쓰였는지 — 제목을 누르면 기사 원문으로 간다."""
    if not items:
        return ""
    lis = "".join(
        "<li>"
        + (f'<a href="{escape(s["url"], quote=True)}" target="_blank">{escape(s["title"])}</a>'
           if s.get("url") else escape(s["title"]))
        + (f' <span class="pr">{escape(s["press"])}</span>' if s.get("press") else "")
        + "</li>"
        for s in items
    )
    return f'<div class="mkt-src"><span class="t">{label}</span><ul>{lis}</ul></div>'


def _highlight_card(s: dict[str, Any]) -> str:
    """특징주 하나 — 방향 배지 + 이슈 3줄 + 근거 기사."""
    kind, label = _DIR.get(s.get("direction", "중립"), ("neu", "⚪ 중립"))
    lis = "".join(
        f'<li><span class="lb">{_LABELS[j] if j < len(_LABELS) else ""}</span>{escape(l)}</li>'
        for j, l in enumerate(s["lines"])
    )
    return (
        f'<div class="card {kind}">'
        f'<div class="rn"><span class="dir {kind}">{label}</span>{escape(s["name"])}'
        f'<span class="cd">{escape(s["code"])}</span>{_move(s)}</div>'
        f'<ol class="sum">{lis}</ol>'
        f'{_sources(s.get("sources") or [], "특징주 기사")}'
        f"</div>"
    )


def render(cfg: dict[str, Any], now: datetime,
           stocks: list[dict[str, Any]],
           market: dict[str, Any] | None = None) -> str:
    chips = _stock_chips(stocks)
    dirs = Counter(s.get("direction", "중립") for s in stocks)
    n_art = sum(len(s.get("articles") or []) for s in stocks)

    groups = []
    for s in stocks:
        # 종목명을 누르면 맨 위 특징주 목록으로 되돌아간다
        groups.append(
            f'<div class="grp" id="s{s["code"]}"><div class="gh">'
            f'<a class="gback" href="#stock-top">{escape(s["name"])} ↑</a></div>'
            f'{_highlight_card(s)}</div>'
        )
    groups_html = "\n".join(groups) if groups else (
        '<div class="lead">오늘 다룰 만한 특징주 기사가 없습니다.</div>'
    )

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>오늘의 특징주 브리핑 ({now:%Y-%m-%d})</title>
<style>{_CSS}</style></head>
<body><div class="wrap">
<h1>📈 오늘의 특징주 브리핑</h1>
<div class="sub">{now:%Y년 %m월 %d일 %H:%M} 기준 · 특징주 {len(stocks)}종목 · 기사 {n_art}건 · 긍정 {dirs['긍정']} · 부정 {dirs['부정']} · 중립 {dirs['중립']}</div>

{_market_section(market)}
<h2 id="stock-top">📊 오늘의 특징주</h2>
<div class="lead">
<b>{now:%Y-%m-%d %H:%M} 조회</b> 기준, 오늘 언론이 <b>특징주</b> 기사로 다룬 종목입니다.
종목을 누르면 아래 이슈 요약으로 이동합니다.
<div style="margin-top:10px">{chips}</div>
</div>

<h2>🔥 종목별 이슈</h2>
{groups_html}

<div class="foot">
{_market_note(market)}직전 거래일 장 종료({cfg['market_close']}) 이후 나온 기사 중
종목별로 묶은 것을, 함께 표시한 기사만을 근거로 요약했습니다. 제목에 '특징주'가 들어간
기사를 우선하고 모자라면 등락률 상위 종목의 기사로 채웁니다. 종목은 기사 제목에서
찾아 종목코드로 확인한 것이며, 현재가·등락률은 조회 시점 기준이라 지금과 다를 수 있습니다.
긍정·부정 표시는 기사 내용에 따른 기계적 판정이며 기사 원문과 다를 수 있으니, 투자 판단
전 반드시 기사 원문을 확인하세요. 이 글은 투자 권유가 아니고 오류가 있을 수 있습니다.
투자 판단과 책임은 본인에게 있습니다.
</div>
</div></body></html>"""


def save(cfg: dict[str, Any], now: datetime,
         stocks: list[dict[str, Any]],
         market: dict[str, Any] | None = None, *, fname: str | None = None) -> tuple[Path, str]:
    """HTML 을 렌더해 웹 폴더에 저장하고 (파일경로, 웹URL) 을 돌려준다."""
    conf = cfg["report"]
    web_dir = Path(conf["web_dir"])
    if not web_dir.parent.exists():
        raise PipelineError(
            f"리포트 저장 폴더의 상위 경로가 없습니다: {web_dir}\n"
            "  외장 디스크가 마운트됐는지, config.yaml 의 report.web_dir 를 확인하세요."
        )
    web_dir.mkdir(parents=True, exist_ok=True)

    html = render(cfg, now, stocks, market)
    fname = fname or f"{now:%Y%m%d}_오늘의특징주_브리핑.html"
    (web_dir / fname).write_text(html, encoding="utf-8")
    # 한글 원본 URL 그대로 — 인코딩은 클라이언트(텔레그램)에 한 번만 맡긴다
    url = f"{conf['url_base'].rstrip('/')}/{fname}"
    print(f"[report] 저장: {web_dir / fname} ({len(html)}자)")
    return web_dir / fname, url
