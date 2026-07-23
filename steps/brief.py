"""3-5단계: 공시 선정(긍정/부정) → 3줄 요약 → 글 조립.

선정과 요약을 분리한 이유: 선정은 제목 목록만으로 한 번에 (본문 150건을
다 읽힐 수 없다), 요약은 선정된 10건만 본문을 확보해 건별로 한다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import frontmatter

from . import claude_cli, dart
from .common import PipelineError, extract_json, load_prompt, posts_dir

_DISCLAIMER = (
    "*이 글은 공시를 자동 수집·요약한 정보이며 투자 권유가 아닙니다. "
    "투자 판단과 책임은 본인에게 있으며, 정확한 내용은 공시 원문을 확인하세요.*"
)


def select(
    cfg: dict[str, Any], pool: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """후보 풀에서 긍정/부정 공시를 고른다. (positive, negative) 반환."""
    conf = cfg["brief"]
    lines = "\n".join(
        f"{d['rcept_no']} | {d['corp_name']} | {d['report_nm']} | {d['rcept_dt']}"
        + (" 🔥" if d.get("hot") else "")
        for d in pool
    )
    prompt = load_prompt(cfg, "select.txt").format(
        positive_count=conf["positive_count"],
        negative_count=conf["negative_count"],
        pool=lines,
    )
    result = extract_json(claude_cli.ask(cfg, prompt))
    if not isinstance(result, dict):
        raise PipelineError(f"선정 결과가 객체가 아닙니다: {type(result)}")

    by_no = {d["rcept_no"]: d for d in pool}

    def _resolve(key: str, limit: int) -> list[dict[str, Any]]:
        out = []
        for row in result.get(key, []):
            if not isinstance(row, dict):
                continue
            d = by_no.get(str(row.get("rcept_no", "")))
            if d is None:
                print(f"[brief] 목록에 없는 rcept_no 무시: {row.get('rcept_no')}")
                continue
            d = dict(d, why=row.get("why", ""))
            out.append(d)
        return out[:limit]

    positive = _resolve("positive", conf["positive_count"])
    negative = _resolve("negative", conf["negative_count"])
    print(f"[brief] 선정: 긍정 {len(positive)}건 / 부정 {len(negative)}건")
    return positive, negative


def summarize(cfg: dict[str, Any], item: dict[str, Any]) -> list[str]:
    """공시 하나를 3줄로. 본문을 못 구하면 제목 기반으로 요약한다."""
    doc_text = dart.fetch_document_text(cfg, item["rcept_no"]) or "(본문 없음)"
    prompt = load_prompt(cfg, "summarize.txt").format(
        summary_lines=cfg["brief"]["summary_lines"],
        corp_name=item["corp_name"],
        report_nm=item["report_nm"],
        doc_text=doc_text,
    )
    result = extract_json(claude_cli.ask(cfg, prompt))
    lines = result.get("lines") if isinstance(result, dict) else None
    if not isinstance(lines, list) or not lines:
        raise PipelineError(f"요약 형식 오류({item['rcept_no']}): {result!r}")
    return [str(l).strip() for l in lines[: cfg["brief"]["summary_lines"]]]


def summarize_all(
    cfg: dict[str, Any], items: list[dict[str, Any]], label: str
) -> list[dict[str, Any]]:
    done = []
    for i, item in enumerate(items, 1):
        print(f"[brief] {label} 요약 ({i}/{len(items)}) {item['corp_name']} — {item['report_nm']}")
        item = dict(item, lines=summarize(cfg, item))
        done.append(item)
    return done


def compose(
    cfg: dict[str, Any],
    trend_stocks: list[dict[str, Any]],
    positive: list[dict[str, Any]],
    negative: list[dict[str, Any]],
) -> str:
    """마크다운 본문 조립."""
    today = date.today()
    parts: list[str] = []

    if trend_stocks:
        names = ", ".join(dict.fromkeys(t["corp_name"] for t in trend_stocks))
        parts.append(f"오늘 검색 트렌드에 오른 종목: **{names}**")

    def _section(title: str, items: list[dict[str, Any]]) -> None:
        parts.append(f"## {title}")
        if not items:
            parts.append("_해당 공시 없음_")
            return
        for i, d in enumerate(items, 1):
            hot = " 🔥" if d.get("hot") else ""
            parts.append(f"### {i}. {d['corp_name']} — {d['report_nm']}{hot}")
            # 불릿은 한 블록으로 묶는다 (섹션 구분자 \n\n 가 사이에 끼면 늘어져 보임)
            parts.append("\n".join(f"- {line}" for line in d["lines"]))
            parts.append(f"[공시 원문 보기]({dart.viewer_url(d['rcept_no'])})")

    _section(f"👍 긍정 공시 {len(positive)}", positive)
    _section(f"👎 부정 공시 {len(negative)}", negative)
    parts.append("---")
    parts.append(_DISCLAIMER)
    return "\n\n".join(parts)


def write_post(
    cfg: dict[str, Any],
    trend_stocks: list[dict[str, Any]],
    positive: list[dict[str, Any]],
    negative: list[dict[str, Any]],
) -> Path:
    today = date.today()
    title = (
        f"오늘의 공시 3줄 요약 ({today:%Y-%m-%d}) — "
        f"긍정 {len(positive)} · 부정 {len(negative)}"
    )
    body = compose(cfg, trend_stocks, positive, negative)
    post = frontmatter.Post(
        body,
        title=title,
        slug=f"disclosure-brief-{today:%Y%m%d}",
        date=f"{today:%Y-%m-%d}",
        trend_stocks=[t["corp_name"] for t in trend_stocks],
        rcept_nos=[d["rcept_no"] for d in positive + negative],
        published_url="",
    )
    path = posts_dir(cfg) / f"{today:%Y%m%d}-brief.md"
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    print(f"[brief] 글 저장: {path.name}")
    return path
