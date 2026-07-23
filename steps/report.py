"""4단계: 네이버 인기종목 공시 브리핑을 HTML 로 렌더해 웹서버 폴더에 저장.

출력 폴더/주소는 config.yaml 의 report.web_dir / report.url_base.
저장만 하고 텔레그램 발송은 pipeline 이 한다(알림 로직을 한 곳에 모음).
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from . import dart
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
h2#naver-top { scroll-margin-top: 14px; }
.lead { background: #1a1f29; border: 1px solid #2a303c; border-radius: 10px;
        padding: 16px 20px; margin-bottom: 8px; font-size: 14px; }
.stock { display: inline-block; background: #232a36; color: #cdd4de; border-radius: 8px;
         padding: 5px 11px; margin: 3px 5px 3px 0; font-size: 13px; }
.stock .rk { color: #6b7482; font-size: 11px; margin-right: 5px; }
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
.card .rn { font-size: 14px; font-weight: 600; color: #f3f5f7; margin-bottom: 4px; }
.card .dt { font-size: 12px; color: #8b93a0; margin-bottom: 8px; }
.dir { font-size: 12px; font-weight: 700; border-radius: 6px; padding: 1px 8px; margin-right: 8px; }
.dir.pos { background: #3a1518; color: #f87171; }
.dir.neg { background: #14243c; color: #7fb0f5; }
.dir.neu { background: #232a36; color: #aab3c0; }
ol.sum { margin: 0; padding-left: 20px; }
ol.sum li { margin: 5px 0; }
ol.sum li .lb { color: #8b93a0; font-size: 11.5px; margin-right: 4px; }
.src { display: inline-block; margin-top: 9px; font-size: 12.5px; }
.src a { color: #60a5fa; text-decoration: none; }
.foot { color: #6b7482; font-size: 12px; margin-top: 30px; padding-top: 14px;
        border-top: 1px solid #2a303c; }
"""

_LABELS = ["핵심", "세부·해석", "예상 주가 방향"]
_DIR = {"긍정": ("pos", "🔺 긍정"), "부정": ("neg", "🔻 부정"), "중립": ("neu", "⚪ 중립")}


def _fmt_date(dt: str) -> str:
    return f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}" if len(dt) == 8 else dt


def _stock_chips(stocks: list[dict[str, Any]], covered_codes: set[str]) -> str:
    out = []
    for s in stocks:
        inner = f'<span class="rk">{s["rank"]}</span>{escape(s["name"])}'
        if s["code"] in covered_codes:
            # 공시 있는 종목은 아래 해당 공시로 바로 이동
            out.append(f'<a class="stock has" href="#s{s["code"]}">{inner} 📄</a>')
        else:
            out.append(f'<span class="stock">{inner}</span>')
    return "".join(out)


def _disc_card(d: dict[str, Any]) -> str:
    kind, label = _DIR.get(d.get("direction", "중립"), ("neu", "⚪ 중립"))
    lis = "".join(
        f'<li><span class="lb">{_LABELS[j] if j < len(_LABELS) else ""}</span>{escape(l)}</li>'
        for j, l in enumerate(d["lines"])
    )
    url = dart.viewer_url(d["rcept_no"])
    return (
        f'<div class="card {kind}">'
        f'<div class="rn"><span class="dir {kind}">{label}</span>{escape(d["report_nm"])}</div>'
        f'<div class="dt">📅 공시일 {_fmt_date(d.get("rcept_dt", ""))}</div>'
        f'<ol class="sum">{lis}</ol>'
        f'<div class="src">📄 <a href="{url}" target="_blank">공시 원문 보기</a></div>'
        f"</div>"
    )


def render(cfg: dict[str, Any], now: datetime,
           stocks: list[dict[str, Any]], covered: list[dict[str, Any]]) -> str:
    covered_codes = {c["code"] for c in covered}
    chips = _stock_chips(stocks, covered_codes)
    n_disc = sum(len(c["disclosures"]) for c in covered)

    groups = []
    for c in covered:
        cards = "\n".join(_disc_card(d) for d in c["disclosures"])
        # 종목명을 누르면 맨 위 인기검색 종목 목록으로 되돌아간다
        groups.append(
            f'<div class="grp" id="s{c["code"]}"><div class="gh"><span class="grk">'
            f'{c["rank"]}위</span>'
            f'<a class="gback" href="#naver-top">{escape(c["name"])} ↑</a></div>{cards}</div>'
        )
    groups_html = "\n".join(groups) if groups else (
        '<div class="lead">인기 검색 종목 중 최근 공시가 있는 종목이 없습니다.</div>'
    )

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>네이버 인기종목 공시 브리핑 ({now:%Y-%m-%d})</title>
<style>{_CSS}</style></head>
<body><div class="wrap">
<h1>📈 네이버 인기종목 공시 브리핑</h1>
<div class="sub">{now:%Y년 %m월 %d일 %H:%M} 기준 · 인기종목 TOP {len(stocks)} 중 공시 {len(covered)}종목 · 공시 {n_disc}건</div>

<h2 id="naver-top">📈 네이버 인기 검색 종목 TOP {len(stocks)}</h2>
<div class="lead">
<b>{now:%Y-%m-%d %H:%M} 조회</b> 기준, 투자자들이 지금 네이버에서 가장 많이 찾아본 종목입니다.
<b>📄</b> 표시가 최근 공시가 있어 아래에서 정리한 <b>{len(covered)}개</b> 종목입니다.
<div style="margin-top:10px">{chips}</div>
</div>

<h2>📄 인기종목 공시 정리</h2>
{groups_html}

<div class="foot">
네이버 금융 인기 검색 종목 중 최근 {cfg['dart']['lookback_days']}일 내 공시가 있는 종목을,
금융감독원 전자공시(DART) 원문을 근거로 요약했습니다. 단순 절차성 공시(임원 소유상황
보고 등)는 제외했습니다. 이 글은 투자 권유가 아니며 오류가 있을 수 있으니, 투자 판단
전 반드시 공시 원문을 확인하세요. 투자 판단과 책임은 본인에게 있습니다.
</div>
</div></body></html>"""


def save(cfg: dict[str, Any], now: datetime,
         stocks: list[dict[str, Any]], covered: list[dict[str, Any]]) -> tuple[Path, str]:
    """HTML 을 렌더해 웹 폴더에 저장하고 (파일경로, 웹URL) 을 돌려준다."""
    conf = cfg["report"]
    web_dir = Path(conf["web_dir"])
    if not web_dir.parent.exists():
        raise PipelineError(
            f"리포트 저장 폴더의 상위 경로가 없습니다: {web_dir}\n"
            "  외장 디스크가 마운트됐는지, config.yaml 의 report.web_dir 를 확인하세요."
        )
    web_dir.mkdir(parents=True, exist_ok=True)

    html = render(cfg, now, stocks, covered)
    fname = f"{now:%Y%m%d}_네이버인기종목_공시브리핑.html"
    (web_dir / fname).write_text(html, encoding="utf-8")
    # 한글 원본 URL 그대로 — 인코딩은 클라이언트(텔레그램)에 한 번만 맡긴다
    url = f"{conf['url_base'].rstrip('/')}/{fname}"
    print(f"[report] 저장: {web_dir / fname} ({len(html)}자)")
    return web_dir / fname, url
