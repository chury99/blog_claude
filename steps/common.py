"""파이프라인 단계들이 공유하는 유틸리티."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent


class PipelineError(Exception):
    """파이프라인 실행 중 사용자가 고쳐야 하는 문제."""


def load_config(path: str | Path = "config.yaml") -> dict[str, Any]:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    if not p.exists():
        raise PipelineError(f"설정 파일이 없습니다: {p}")
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_prompt(cfg: dict[str, Any], name: str) -> str:
    p = ROOT / cfg["paths"]["prompts"] / name
    if not p.exists():
        raise PipelineError(f"프롬프트 파일이 없습니다: {p}")
    return p.read_text(encoding="utf-8")


def drafts_dir(cfg: dict[str, Any]) -> Path:
    d = ROOT / cfg["paths"]["drafts"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def topics_path(cfg: dict[str, Any]) -> Path:
    p = ROOT / cfg["paths"]["topics"]
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def slugify(text: str) -> str:
    """제목을 slug 로.

    한글을 ASCII 로 떨구면 전부 사라져 slug 가 겹치므로 한글은 그대로 살린다.
    (Ghost/브라우저 모두 유니코드 slug 를 처리한다.)
    """
    normalized = unicodedata.normalize("NFC", text).lower()
    # 한글·영숫자만 남기고 나머지는 구분자로
    slug = re.sub(r"[^0-9a-z가-힣ㄱ-ㅎㅏ-ㅣ]+", "-", normalized).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:60].strip("-")
    if slug:
        return slug
    # 제목이 전부 기호인 경우 등 — 내용 기반 fallback 으로 충돌 회피
    return "post-" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def extract_json(text: str) -> Any:
    """LLM 출력에서 JSON 블록을 꺼낸다. 코드펜스나 서두 문장이 섞여 있어도 동작."""
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start = min(
        (i for i in (text.find("["), text.find("{")) if i != -1),
        default=-1,
    )
    if start == -1:
        raise PipelineError(f"응답에서 JSON 을 찾지 못했습니다:\n{text[:500]}")
    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(text[start:])
    except json.JSONDecodeError as e:
        raise PipelineError(f"JSON 파싱 실패: {e}\n원문:\n{text[:500]}") from e
    return obj
