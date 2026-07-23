"""텔레그램 알림.

수집/생성은 자동으로 돌아가고 사람은 자리에 없을 수 있다. 검수할 초안이
준비되면 텔레그램으로 알려주는 용도. 알림 실패는 파이프라인을 죽이지 않는다.

발행 알림은 '발행했다'는 통보일 뿐, 이 모듈이 발행을 승인하지는 않는다.

자격증명은 환경변수가 아니라 설정 파일에서 읽는다(기본 `config/telegram.json`).

    {
      "bot_token": "123456:ABC-DEF...",
      "chat_id": "123456789"
    }

이 파일은 .gitignore 에 있어 커밋되지 않는다. `config/telegram.json.example`
을 복사해 값을 채우거나, `python pipeline.py telegram setup` 으로 자동 생성한다.
"""

from __future__ import annotations

import html
import json
import stat
from pathlib import Path
from typing import Any

import requests

from .common import ROOT, PipelineError

API_BASE = "https://api.telegram.org"

DEFAULT_CONFIG_PATH = ROOT / "config" / "telegram.json"
EXAMPLE_CONFIG_PATH = ROOT / "config" / "telegram.json.example"

TOKEN_KEY = "bot_token"
CHAT_ID_KEY = "chat_id"

DEFAULT_TIMEOUT = 15.0


def _config_path(cfg: dict[str, Any]) -> Path:
    """config.yaml 에서 경로를 덮어쓸 수 있게 한다(미지정 시 기본값)."""
    custom = cfg.get("notify", {}).get("telegram", {}).get("config_path")
    if not custom:
        return DEFAULT_CONFIG_PATH
    p = Path(custom)
    return p if p.is_absolute() else ROOT / p


def setup_hint(path: Path) -> str:
    return (
        f"텔레그램 설정 파일이 없습니다: {path}\n"
        f"  자동 설정: python pipeline.py telegram setup --token <BotFather 토큰>\n"
        f"  수동 설정: cp {EXAMPLE_CONFIG_PATH} {path} 후 값 입력 + chmod 600"
    )


def load_credentials(path: Path) -> tuple[str, str]:
    """설정 파일에서 (토큰, 채팅 ID)를 읽는다."""
    if not path.is_file():
        raise PipelineError(setup_hint(path))

    config = _read_json(path)
    token = str(config.get(TOKEN_KEY, "") or "").strip()
    chat_id = str(config.get(CHAT_ID_KEY, "") or "").strip()

    missing = [k for k, v in ((TOKEN_KEY, token), (CHAT_ID_KEY, chat_id)) if not v]
    if missing:
        raise PipelineError(f"설정 파일에 값이 비어 있습니다 ({path}): {', '.join(missing)}")
    if token.startswith("여기에") or chat_id.startswith("여기에"):
        raise PipelineError(f"설정 파일이 예시 그대로입니다 ({path}). 실제 값으로 바꿔주세요.")

    _warn_if_world_readable(path)
    return token, chat_id


def _read_json(path: Path) -> dict[str, Any]:
    """저장된 설정을 읽는다. 값이 비어 있어도 그대로 돌려준다."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PipelineError(f"설정 파일을 읽지 못했습니다 ({path}): {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PipelineError(
            f"설정 파일이 올바른 JSON이 아닙니다 ({path}): {exc.msg} (line {exc.lineno})"
        ) from exc
    return data if isinstance(data, dict) else {}


def _warn_if_world_readable(path: Path) -> None:
    """자격증명 파일이 남에게도 읽히는 권한이면 경고한다."""
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if mode & (stat.S_IRGRP | stat.S_IROTH):
        print(f"[notify] 경고: {path} 를 다른 사용자도 읽을 수 있습니다. chmod 600 권장.")


def save_credentials(token: str, chat_id: str, path: Path) -> Path:
    """설정 파일에 자격증명을 쓰고 본인만 읽도록 권한을 조인다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({TOKEN_KEY: token, CHAT_ID_KEY: str(chat_id)},
                   indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def _get(method: str, token: str) -> Any:
    try:
        resp = requests.get(f"{API_BASE}/bot{token}/{method}", timeout=DEFAULT_TIMEOUT)
        body = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise PipelineError(f"텔레그램 API 호출 실패({method}): {exc}") from exc
    if not body.get("ok"):
        # 오류 메시지에 토큰이 섞이지 않도록 API가 준 설명만 전달한다
        raise PipelineError(f"텔레그램 API 실패({method}): {body.get('description', '알 수 없는 오류')}")
    return body.get("result")


def get_me(token: str) -> dict[str, Any]:
    """봇 정보 조회. 토큰이 유효한지 확인하는 용도."""
    return _get("getMe", token)


def detect_chat_ids(token: str) -> dict[str, str]:
    """봇이 받은 메시지에서 chat_id 를 찾는다. {chat_id: 표시이름}.

    봇에게 아직 아무도 말을 걸지 않았으면 빈 딕셔너리다
    (텔레그램은 봇이 먼저 대화를 시작할 수 없다).
    """
    found: dict[str, str] = {}
    for update in _get("getUpdates", token) or []:
        chat = (update.get("message") or update.get("channel_post") or {}).get("chat") or {}
        if (chat_id := chat.get("id")) is None:
            continue
        found[str(chat_id)] = (
            chat.get("title")
            or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
            or chat.get("username")
            or chat.get("type", "")
        )
    return found


def send_message(token: str, chat_id: str, text: str) -> dict[str, Any]:
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(
            f"{API_BASE}/bot{token}/sendMessage", json=payload, timeout=DEFAULT_TIMEOUT
        )
        body = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise PipelineError(f"텔레그램 전송 실패: {exc}") from exc
    if not body.get("ok"):
        raise PipelineError(
            f"텔레그램 전송 실패 (HTTP {resp.status_code}): "
            f"{body.get('description', '알 수 없는 오류')}"
        )
    return body.get("result", {})


def send(cfg: dict[str, Any], text: str) -> bool:
    """알림 전송. 꺼져 있거나 실패해도 False 만 돌려주고 넘어간다."""
    if not cfg.get("notify", {}).get("telegram", {}).get("enabled"):
        return False
    try:
        token, chat_id = load_credentials(_config_path(cfg))
        send_message(token, chat_id, text)
        return True
    except Exception as e:  # 알림 때문에 파이프라인이 죽으면 안 된다
        print(f"[notify] 텔레그램 전송 실패 — 무시하고 진행: {e}")
        return False


def escape(text: str) -> str:
    """HTML 파스모드로 보낼 때 사용자/LLM 생성 문자열을 안전하게."""
    return html.escape(text)


def check(cfg: dict[str, Any]) -> None:
    """저장된 설정으로 연결 + 실제 발송 확인. 설정 문제는 에러로 올린다."""
    path = _config_path(cfg)
    token, chat_id = load_credentials(path)
    bot = get_me(token)
    print(f"[notify] 봇 연결 OK: {bot.get('first_name')} (@{bot.get('username')})")
    send_message(token, chat_id, "✅ 블로그 파이프라인 알림 연결 완료")
    print(f"[notify] 테스트 메시지 발송 OK (chat_id={chat_id})")
    print(f"[notify] 설정 파일: {path}")


def setup(cfg: dict[str, Any], token: str | None = None, chat_id: str | None = None) -> None:
    """토큰을 저장하고, 봇에게 온 메시지에서 chat_id 를 찾아 설정 파일에 기록한다."""
    path = _config_path(cfg)
    token = (token or _read_json(path).get(TOKEN_KEY, "")).strip()
    if not token:
        raise PipelineError(
            "봇 토큰이 없습니다. --token 으로 넘기거나 설정 파일에 먼저 적어주세요.\n"
            "  @BotFather 에게 /newbot 으로 발급받을 수 있습니다."
        )

    bot = get_me(token)
    print(f"[notify] 봇 확인: {bot.get('first_name')} (@{bot.get('username')})")

    chat_id = (chat_id or "").strip()
    if not chat_id:
        found = detect_chat_ids(token)
        if not found:
            save_credentials(token, "", path)
            raise PipelineError(
                f"토큰은 {path} 에 저장했습니다.\n"
                "  chat_id 를 찾지 못했습니다. 텔레그램은 봇이 먼저 말을 걸 수 없으므로,\n"
                f"  1) 텔레그램에서 @{bot.get('username')} 을 열고\n"
                "  2) 아무 메시지나 한 번 보낸 뒤 (예: 안녕)\n"
                "  3) 다시 실행하세요: python pipeline.py telegram setup"
            )
        if len(found) > 1:
            listed = "\n".join(f"    {cid}  {label}" for cid, label in found.items())
            raise PipelineError(
                f"여러 대화가 발견됐습니다. --chat-id 로 하나를 지정하세요:\n{listed}"
            )
        chat_id, label = next(iter(found.items()))
        print(f"[notify] chat_id 발견: {chat_id} ({label})")

    saved = save_credentials(token, chat_id, path)
    print(f"[notify] 저장 완료: {saved}")
    send_message(token, chat_id, "✅ 블로그 파이프라인 알림 연결 완료")
    print("[notify] 테스트 메시지 발송 OK")
