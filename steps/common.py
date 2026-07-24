"""파이프라인 단계들이 공유하는 유틸리티."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent

_WEEKDAY_KR = ("월", "화", "수", "목", "금", "토", "일")


class PipelineError(Exception):
    """파이프라인 실행 중 사용자가 고쳐야 하는 문제."""


def holiday_reason(day: date | None = None) -> str | None:
    """휴일이면 사유(주말/공휴일명), 영업일이면 None.

    한국 증시가 쉬는 날(주말·공휴일)에는 새 공시가 없으므로, 08시 자동 실행을
    이 값으로 건너뛴다. 공휴일 판정은 holidays 라이브러리(SouthKorea)를 쓰되,
    없으면 주말만이라도 거른다.
    """
    day = day or date.today()
    try:
        import holidays

        kr = holidays.SouthKorea(years=day.year)
        name = kr.get(day)
        if name:
            return str(name)
    except ImportError:
        print("[warn] holidays 미설치 — 공휴일 판정 없이 주말만 거릅니다.")
    if day.weekday() >= 5:  # 토(5)·일(6)
        return f"주말({_WEEKDAY_KR[day.weekday()]})"
    return None


def load_secret_file(rel_path: str, key: str, *, how_to: str) -> str:
    """config/ 아래 JSON 파일에서 비밀값 하나를 읽는다 (텔레그램과 같은 방식).

    비밀값을 .env(환경변수)가 아니라 파일에 두면 실행할 때 export 가 필요 없다.
    파일은 .gitignore 로 제외된다. how_to 는 값이 없을 때 보여줄 안내문.
    """
    path = ROOT / rel_path
    if not path.exists():
        raise PipelineError(f"설정 파일이 없습니다: {path}\n{how_to}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise PipelineError(f"설정 파일을 읽지 못했습니다 ({path}): {e}") from e

    value = str((data or {}).get(key, "") or "").strip()
    if not value or value.startswith("여기에"):
        raise PipelineError(f"설정 파일에 {key} 값이 없습니다 ({path}).\n{how_to}")

    _warn_if_world_readable(path)
    return value


def _warn_if_world_readable(path: Path) -> None:
    """자격증명 파일이 남에게도 읽히는 권한이면 경고한다."""
    import stat

    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if mode & (stat.S_IRGRP | stat.S_IROTH):
        print(f"[warn] {path} 를 다른 사용자도 읽을 수 있습니다. chmod 600 권장.")


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


def data_dir(cfg: dict[str, Any]) -> Path:
    d = ROOT / cfg["paths"]["data"]
    d.mkdir(parents=True, exist_ok=True)
    return d


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
