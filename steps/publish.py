"""4단계: 발행 어댑터.

안전장치가 3중으로 걸려 있다 (CONTEXT.md 3-4 참고 — 완전 무인 발행 금지):
  1. pipeline.py 에서 `publish` 서브커맨드를 명시적으로 부를 때만 이 단계가 돈다.
  2. 초안 프론트매터의 reviewed 가 true 여야 한다. 사람이 직접 바꿔야 한다.
  3. 그래도 기본은 Ghost draft 상태로 올라간다. 실제 공개는 --live 를 추가로 줘야 한다.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import frontmatter

from .common import PipelineError, drafts_dir


class Publisher(ABC):
    """발행 대상 플랫폼 어댑터. Ghost 외 플랫폼은 이걸 상속해 추가."""

    @abstractmethod
    def push(self, post: frontmatter.Post, live: bool) -> str:
        """초안을 업로드하고 결과 URL(또는 식별자)을 돌려준다."""


class DryRunPublisher(Publisher):
    """실제 업로드 없이 무엇이 올라갈지만 보여준다."""

    def push(self, post: frontmatter.Post, live: bool) -> str:
        status = "published" if live else "draft"
        print(f"[dryrun] title={post['title']!r} status={status} "
              f"body={len(post.content)}자")
        return "dryrun://not-uploaded"


class GhostPublisher(Publisher):
    """Ghost Admin API 어댑터. 인증은 JWT(키의 secret 으로 HS256 서명)."""

    def __init__(self, cfg: dict[str, Any]):
        self.api_url = cfg["publish"]["ghost"]["api_url"].rstrip("/")
        self.api_version = cfg["publish"]["ghost"]["api_version"]
        self.key = os.getenv("GHOST_ADMIN_API_KEY", "")

        if "CHANGE-ME" in self.api_url:
            raise PipelineError("config.yaml 의 publish.ghost.api_url 을 설정하세요.")
        if not self.key or ":" not in self.key:
            raise PipelineError(
                "GHOST_ADMIN_API_KEY 가 없거나 형식이 잘못됐습니다 (<id>:<secret>).\n"
                "  .env 에 설정하세요. (.env.example 참고)"
            )

    def _token(self) -> str:
        import jwt

        key_id, secret = self.key.split(":", 1)
        now = datetime.now(timezone.utc)
        payload = {
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "aud": "/admin/",
        }
        return jwt.encode(
            payload,
            bytes.fromhex(secret),
            algorithm="HS256",
            headers={"kid": key_id, "alg": "HS256", "typ": "JWT"},
        )

    def push(self, post: frontmatter.Post, live: bool) -> str:
        import requests

        url = f"{self.api_url}/ghost/api/admin/posts/?source=html"
        body = {
            "posts": [
                {
                    "title": post["title"],
                    "slug": post.get("slug", ""),
                    "html": _markdown_to_html(post.content),
                    "status": "published" if live else "draft",
                }
            ]
        }
        resp = requests.post(
            url,
            json=body,
            headers={
                "Authorization": f"Ghost {self._token()}",
                "Accept-Version": self.api_version,
            },
            timeout=30,
        )
        if resp.status_code >= 400:
            raise PipelineError(f"Ghost 업로드 실패 ({resp.status_code}): {resp.text[:500]}")

        created = resp.json()["posts"][0]
        return created.get("url") or created["id"]


def _markdown_to_html(md: str) -> str:
    """Ghost 는 source=html 로 HTML 을 받는다.

    markdown 패키지가 있으면 변환하고, 없으면 Ghost 가 그대로 렌더하도록
    <pre> 로 감싸지 않고 원문을 넘긴다(검수 단계에서 확인 가능).
    """
    try:
        import markdown
    except ImportError:
        return md
    return markdown.markdown(md, extensions=["fenced_code", "tables"])


def make_publisher(cfg: dict[str, Any]) -> Publisher:
    adapter = cfg["publish"]["adapter"]
    if adapter == "ghost":
        return GhostPublisher(cfg)
    if adapter == "dryrun":
        return DryRunPublisher()
    raise PipelineError(f"알 수 없는 발행 어댑터: {adapter!r} (ghost | dryrun)")


def find_draft(cfg: dict[str, Any], name: str) -> Path:
    d = drafts_dir(cfg)
    path = d / name if not name.endswith(".md") else d / name
    if not path.exists():
        path = d / f"{name}.md"
    if not path.exists():
        available = sorted(p.name for p in d.glob("*.md"))
        raise PipelineError(
            f"초안을 찾을 수 없습니다: {name}\n"
            + ("  사용 가능: " + ", ".join(available) if available else "  drafts/ 가 비어 있습니다.")
        )
    return path


def run(cfg: dict[str, Any], draft_name: str, live: bool = False) -> str:
    path = find_draft(cfg, draft_name)
    post = frontmatter.load(path)

    # 안전장치 2: 사람 검수 확인
    if not post.get("reviewed"):
        raise PipelineError(
            f"{path.name} 은 아직 검수되지 않았습니다.\n"
            "  초안을 읽고 실전 데이터를 채운 뒤, 프론트매터의 reviewed 를 true 로 바꾸세요.\n"
            "  (CONTEXT.md 3-4: 완전 무인 발행 금지)"
        )

    if post.get("published_url"):
        raise PipelineError(
            f"{path.name} 은 이미 발행됐습니다: {post['published_url']}\n"
            "  다시 올리려면 프론트매터의 published_url 을 비우세요."
        )

    publisher = make_publisher(cfg)
    status = "공개 발행" if live else "플랫폼 draft"
    print(f"[publish] {path.name} → {status}")

    url = publisher.push(post, live=live)

    post["published_url"] = url
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    print(f"[publish] 완료: {url}")
    return url
