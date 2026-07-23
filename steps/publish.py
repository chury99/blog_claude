"""6단계: 발행 어댑터.

자동 발행 전제(CONTEXT.md 3-2). 안전장치는 발행 승인이 아니라:
  - config.yaml 의 publish.auto 킬스위치 (daily 가 이 단계를 부를지 결정)
  - 이미 발행된 글(published_url 기록)은 중복 업로드 거부
  - dryrun 어댑터로 무발행 테스트
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import frontmatter

from .common import PipelineError, posts_dir


class Publisher(ABC):
    """발행 대상 플랫폼 어댑터. Ghost 외 플랫폼은 이걸 상속해 추가."""

    # 실제 업로드가 일어나는 어댑터만 True. 글 파일에 published_url 을 기록할지 결정.
    uploads = True

    @abstractmethod
    def push(self, post: frontmatter.Post, live: bool) -> str:
        """글을 업로드하고 결과 URL(또는 식별자)을 돌려준다."""


class DryRunPublisher(Publisher):
    """실제 업로드 없이 무엇이 올라갈지만 보여준다."""

    uploads = False

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
    """Ghost 는 source=html 로 HTML 을 받으므로 변환이 필수다."""
    try:
        import markdown
    except ImportError as e:
        raise PipelineError(
            "markdown 패키지가 필요합니다: pip install markdown\n"
            "  (requirements.txt 에 포함되어 있습니다)"
        ) from e
    return markdown.markdown(md, extensions=["fenced_code", "tables"])


def make_publisher(cfg: dict[str, Any]) -> Publisher:
    adapter = cfg["publish"]["adapter"]
    if adapter == "ghost":
        return GhostPublisher(cfg)
    if adapter == "dryrun":
        return DryRunPublisher()
    raise PipelineError(f"알 수 없는 발행 어댑터: {adapter!r} (ghost | dryrun)")


def find_post(cfg: dict[str, Any], name: str) -> Path:
    d = posts_dir(cfg)
    path = d / name
    if not path.exists() and not name.endswith(".md"):
        path = d / f"{name}.md"
    if not path.exists():
        available = sorted(p.name for p in d.glob("*.md"))
        raise PipelineError(
            f"글을 찾을 수 없습니다: {name}\n"
            + ("  사용 가능: " + ", ".join(available) if available else "  posts/ 가 비어 있습니다.")
        )
    return path


def run(cfg: dict[str, Any], post_path: Path | str, live: bool = True) -> str:
    path = post_path if isinstance(post_path, Path) else find_post(cfg, post_path)
    post = frontmatter.load(path)

    if post.get("published_url"):
        raise PipelineError(
            f"{path.name} 은 이미 발행됐습니다: {post['published_url']}\n"
            "  다시 올리려면 프론트매터의 published_url 을 비우세요."
        )

    publisher = make_publisher(cfg)
    status = "공개 발행" if live else "플랫폼 draft"
    print(f"[publish] {path.name} → {status}")

    url = publisher.push(post, live=live)

    # dryrun 은 실제로 올라간 게 아니므로 발행 기록을 남기지 않는다
    if publisher.uploads:
        post["published_url"] = url
        path.write_text(frontmatter.dumps(post), encoding="utf-8")
    print(f"[publish] 완료: {url}")
    return url
