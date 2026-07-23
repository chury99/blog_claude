"""3단계: 네이버 인기종목의 공시를 3줄 요약(방향 판정 포함).

선정(긍정 5/부정 5) 단계는 없앴다. 다룰 공시는 '네이버 인기검색종목 중 공시가
있는 종목'으로 정해지므로, 종목코드로 필터만 하면 된다. 방향(긍정/부정/중립)은
공시별로 요약 단계에서 판정한다. 렌더링(HTML)은 report.py 가 맡는다.
"""

from __future__ import annotations

import re
from typing import Any

from . import claude_cli, dart
from .common import PipelineError, extract_json, load_prompt

_VALID_DIR = {"긍정", "부정", "중립"}


def _tidy(line: str) -> str:
    """요약 한 줄 정리. 어미 중복(했다다) 교정 + 음슴체 끝의 마침표 제거."""
    line = line.strip()
    line = re.sub(r"다다(?=[\s.,)\]]|$)", "다", line)
    # 음슴체(…음/함/임)로 끝나는 문장 끝의 마침표는 떼어 통일한다.
    line = re.sub(r"([음함임])\.$", r"\1", line)
    return line


def summarize(cfg: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    """공시 하나를 3줄 요약 + 방향 판정. 본문을 못 구하면 제목 기반으로."""
    doc_text = dart.fetch_document_text(cfg, item["rcept_no"]) or "(본문 없음)"
    prompt = load_prompt(cfg, "summarize.txt").format(
        corp_name=item["corp_name"],
        report_nm=item["report_nm"],
        doc_text=doc_text,
    )
    result = extract_json(claude_cli.ask(cfg, prompt))
    if not isinstance(result, dict):
        raise PipelineError(f"요약 형식 오류({item['rcept_no']}): {result!r}")
    lines = result.get("lines")
    if not isinstance(lines, list) or not lines:
        raise PipelineError(f"요약 줄 오류({item['rcept_no']}): {result!r}")
    direction = result.get("direction", "중립")
    if direction not in _VALID_DIR:
        direction = "중립"
    return dict(
        item,
        direction=direction,
        lines=[_tidy(str(l)) for l in lines[: cfg["brief"]["summary_lines"]]],
    )


def summarize_stocks(
    cfg: dict[str, Any],
    stocks: list[dict[str, Any]],
    by_code: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """인기종목(순위순) 중 공시가 있는 것만, 각 공시를 요약해 묶는다.

    반환: [{rank, name, code, disclosures:[요약된 공시,...]}] (순위순)
    """
    out: list[dict[str, Any]] = []
    todo = [(s, by_code.get(s["code"], [])) for s in stocks]
    total = sum(len(ds) for _, ds in todo)
    done = 0
    for s, ds in todo:
        if not ds:
            continue
        summarized = []
        for d in ds:
            done += 1
            print(f"[brief] 요약 ({done}/{total}) {s['name']} — {d['report_nm']}")
            summarized.append(summarize(cfg, d))
        out.append({**s, "disclosures": summarized})
    print(f"[brief] 공시 있는 인기종목 {len(out)}개 / 공시 {total}건")
    return out
