"""2단계: DART OpenAPI 에서 최근 공시를 수집한다.

- 목록: list.json (상장사만, 유가/코스닥)
- 본문: document.xml (zip) → 태그 제거한 텍스트. 실패해도 요약 단계가
  제목만으로 진행할 수 있게 None 을 돌려준다.
- 이미 다룬 공시(data/seen.json)는 후보에서 뺀다.

인증키는 .env 의 DART_API_KEY. opendart.fss.or.kr 에서 무료 발급.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import date, timedelta
from typing import Any

import requests

from .common import PipelineError, data_dir, load_secret_file

_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
_DOC_URL = "https://opendart.fss.or.kr/api/document.xml"
_VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

# seen.json 보관 기간 — lookback 보다 넉넉하게
_SEEN_KEEP_DAYS = 14


_HOW_TO = (
    "  1) https://opendart.fss.or.kr 가입 → 인증키 신청 (무료, 즉시 발급)\n"
    "  2) config/dart.json 의 api_key 에 입력\n"
    "     (config/dart.json.example 복사 후 값만 채우면 됨)"
)


def _api_key() -> str:
    return load_secret_file("config/dart.json", "api_key", how_to=_HOW_TO)


def viewer_url(rcept_no: str) -> str:
    return _VIEWER_URL.format(rcept_no=rcept_no)


def fetch_disclosures(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """최근 lookback_days 일의 상장사 공시 목록."""
    key = _api_key()
    conf = cfg["dart"]
    end = date.today()
    begin = end - timedelta(days=conf["lookback_days"])

    out: list[dict[str, Any]] = []
    for cls in conf["corp_cls"]:
        page = 1
        while True:
            resp = requests.get(
                _LIST_URL,
                params={
                    "crtfc_key": key,
                    "bgn_de": f"{begin:%Y%m%d}",
                    "end_de": f"{end:%Y%m%d}",
                    "corp_cls": cls,
                    "page_no": page,
                    "page_count": 100,
                },
                timeout=20,
            )
            resp.raise_for_status()
            body = resp.json()
            status = body.get("status")
            if status == "013":  # 조회 결과 없음
                break
            if status != "000":
                raise PipelineError(
                    f"DART list.json 오류 (status={status}): {body.get('message', '')}"
                )
            for item in body.get("list", []):
                if not item.get("stock_code", "").strip():
                    continue  # 비상장 제외
                out.append(
                    {
                        "rcept_no": item["rcept_no"],
                        "corp_name": item["corp_name"],
                        "report_nm": item["report_nm"].strip(),
                        "rcept_dt": item["rcept_dt"],
                        "corp_cls": cls,
                    }
                )
            if page >= int(body.get("total_page", 1)):
                break
            page += 1
    # rcept_no 기준 중복 제거 (양 시장 조회가 겹칠 일은 없지만 방어적으로)
    uniq = {d["rcept_no"]: d for d in out}
    print(f"[dart] 상장사 공시 {len(uniq)}건 ({begin} ~ {end})")
    return list(uniq.values())


def build_pool(
    cfg: dict[str, Any], trend_stocks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """선정 단계에 넘길 후보 풀. 기수록분 제외, 트렌드 종목 🔥 표시, 상한 적용."""
    seen = load_seen(cfg)
    pool = [d for d in fetch_disclosures(cfg) if d["rcept_no"] not in seen]

    # 정확 일치만 🔥. 부분문자열로 매칭하면 "국전" 이 "한국전력공사" 에 걸리는
    # 식의 오탐이 난다(짧은 회사명이 다른 회사명의 일부가 되는 경우).
    trend_names = {t["corp_name"].replace(" ", "") for t in trend_stocks}
    for d in pool:
        d["hot"] = d["corp_name"].replace(" ", "") in trend_names

    hot_count = sum(d["hot"] for d in pool)
    if hot_count:
        print(f"[dart] 트렌드 매칭 공시 🔥 {hot_count}건")

    # 🔥 우선, 그 안에서는 최신순 → 상한을 잘라도 🔥 는 살아남는다
    pool.sort(key=lambda d: (not d["hot"], -int(d["rcept_dt"])))
    max_pool = cfg["dart"]["max_pool"]
    if len(pool) > max_pool:
        print(f"[dart] 후보 {len(pool)}건 → 상한 {max_pool}건으로 자름")
        pool = pool[:max_pool]
    return pool


def fetch_document_text(cfg: dict[str, Any], rcept_no: str) -> str | None:
    """공시 원문 텍스트. 실패하면 None (요약은 제목 기반으로 진행)."""
    try:
        resp = requests.get(
            _DOC_URL,
            params={"crtfc_key": _api_key(), "rcept_no": rcept_no},
            timeout=30,
        )
        resp.raise_for_status()
        # 오류면 zip 이 아니라 XML 에러 메시지가 온다
        if not resp.content[:2] == b"PK":
            return None
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            # 가장 큰 파일이 본문일 확률이 높다
            name = max(zf.infolist(), key=lambda i: i.file_size).filename
            raw = zf.read(name)
    except Exception as e:
        print(f"[dart] 본문 확보 실패({rcept_no}) — 제목 기반 요약으로 진행: {e}")
        return None

    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return None

    # 태그·엔티티 제거 후 공백 정리
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-zA-Z#0-9]+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    return text[: cfg["dart"]["doc_max_chars"]]


# ---------- 기수록 공시 기록 (중복 게재 방지) ----------

def _seen_path(cfg: dict[str, Any]):
    return data_dir(cfg) / "seen.json"


def load_seen(cfg: dict[str, Any]) -> dict[str, str]:
    """{rcept_no: rcept_dt}"""
    p = _seen_path(cfg)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def mark_seen(cfg: dict[str, Any], items: list[dict[str, Any]]) -> None:
    seen = load_seen(cfg)
    for d in items:
        seen[d["rcept_no"]] = d["rcept_dt"]
    cutoff = f"{date.today() - timedelta(days=_SEEN_KEEP_DAYS):%Y%m%d}"
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    _seen_path(cfg).write_text(
        json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8"
    )
