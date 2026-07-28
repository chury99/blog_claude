"""claude CLI 헤드리스(-p) 호출 래퍼.

API 종량 과금 대신 Max 구독 범위의 CLI 를 쓰기 위한 얇은 레이어.
파이프라인에서 클로드를 부르는 곳은 전부 여기를 거친다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .common import ROOT, PipelineError

_TOKEN_FILE = "config/claude.json"
_WORKDIR = "blog_claude_cli"


def _neutral_cwd() -> str:
    """claude 를 프로젝트 밖 빈 폴더에서 돌리기 위한 작업 디렉터리.

    프로젝트 폴더에서 부르면 claude 가 저장소(CLAUDE.md·소스·git 상태)를 컨텍스트로
    끌어와서, 요약 대신 "저장소가 이런 상태다" 같은 엉뚱한 응답을 내놓을 때가 있다.
    요약에 저장소는 필요 없으므로 빈 폴더에서 부른다.
    """
    path = Path(tempfile.gettempdir()) / _WORKDIR
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _load_oauth_token() -> str | None:
    """config/claude.json 의 장기 토큰을 읽는다. 없으면 None (키체인 로그인으로 폴백).

    cron 무인 실행은 GUI 세션이 아니라 키체인 접근·토큰 자동 갱신이 막힌다.
    그래서 OAuth 액세스 토큰이 며칠 만에 만료되면 `Not logged in` 으로 죽는다.
    `claude setup-token` 으로 발급한 장기 토큰(1년)을 이 파일에 두면 그 문제를
    피한다. 파일이 없으면 기존처럼 로그인된 CLI 세션(키체인)을 그대로 빌려 쓴다.
    """
    path = ROOT / _TOKEN_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    token = str((data or {}).get("oauth_token", "") or "").strip()
    if not token or token.startswith("여기에"):
        return None
    return token


def resolve_bin(cfg: dict[str, Any]) -> str:
    claude_bin = cfg["generate"]["claude_bin"]
    resolved = shutil.which(claude_bin)
    if resolved is None:
        raise PipelineError(
            f"claude CLI 를 찾을 수 없습니다: {claude_bin!r}\n"
            "  - 설치: npm install -g @anthropic-ai/claude-code\n"
            "  - 또는 config.yaml 의 generate.claude_bin 에 절대경로 지정"
        )
    return resolved


def ask(cfg: dict[str, Any], prompt: str) -> str:
    """claude -p 로 프롬프트를 보내고 stdout 을 돌려준다."""
    claude_bin = resolve_bin(cfg)
    timeout = cfg["generate"]["timeout"]

    # 장기 토큰이 있으면 환경변수로 주입한다. cron 은 키체인 로그인을 못 빌리므로
    # 이게 없으면 토큰 만료 시 Not logged in 으로 죽는다.
    env = os.environ.copy()
    token = _load_oauth_token()
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token

    try:
        proc = subprocess.run(
            [claude_bin, "-p", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
            cwd=_neutral_cwd(),
        )
    except subprocess.TimeoutExpired as e:
        raise PipelineError(f"claude 호출이 {timeout}초 안에 끝나지 않았습니다.") from e

    if proc.returncode != 0:
        # 미로그인 등 일부 오류는 stderr 가 아니라 stdout 으로 나온다.
        # stderr 만 보면 원인이 안 보이는 빈 에러가 뜬다.
        detail = proc.stderr.strip() or proc.stdout.strip() or "(출력 없음)"
        if "login" in detail.lower():
            detail += (
                "\n  → cron 무인 실행은 키체인 로그인을 못 빌리고 토큰이 며칠 만에"
                " 만료됩니다.\n"
                "     `claude setup-token` 으로 장기 토큰을 발급해"
                f" {_TOKEN_FILE} 의 oauth_token 에 넣으세요.\n"
                "     (대화형 실행은 로그인된 CLI 세션을 그대로 빌려 써도 됩니다)"
            )
        raise PipelineError(f"claude 호출 실패 (exit {proc.returncode}):\n{detail}")

    out = proc.stdout.strip()
    if not out:
        raise PipelineError("claude 가 빈 응답을 반환했습니다.")
    return out
