"""claude CLI 헤드리스(-p) 호출 래퍼.

API 종량 과금 대신 Max 구독 범위의 CLI 를 쓰기 위한 얇은 레이어.
파이프라인에서 클로드를 부르는 곳은 전부 여기를 거친다.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from .common import PipelineError


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

    try:
        proc = subprocess.run(
            [claude_bin, "-p", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise PipelineError(f"claude 호출이 {timeout}초 안에 끝나지 않았습니다.") from e

    if proc.returncode != 0:
        # 미로그인 등 일부 오류는 stderr 가 아니라 stdout 으로 나온다.
        # stderr 만 보면 원인이 안 보이는 빈 에러가 뜬다.
        detail = proc.stderr.strip() or proc.stdout.strip() or "(출력 없음)"
        if "login" in detail.lower():
            detail += (
                "\n  → 터미널에서 `claude` 를 실행하고 /login 으로 로그인하세요.\n"
                "     (파이프라인은 로그인된 CLI 세션을 그대로 빌려 씁니다)"
            )
        raise PipelineError(f"claude 호출 실패 (exit {proc.returncode}):\n{detail}")

    out = proc.stdout.strip()
    if not out:
        raise PipelineError("claude 가 빈 응답을 반환했습니다.")
    return out
