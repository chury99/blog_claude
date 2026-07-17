"""2단계: claude -p 로 초안 생성 → drafts/YYYYMMDD-slug.md 저장.

파이프라인의 핵심 단계. 생성된 초안은 항상 reviewed: false 로 저장되며,
사람이 검수해 true 로 바꾸기 전에는 발행 단계에서 거부된다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import frontmatter

from . import claude_cli
from .common import PipelineError, drafts_dir, load_prompt, slugify, topics_path, extract_json


def load_topics(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    p = topics_path(cfg)
    if not p.exists():
        raise PipelineError(
            f"주제 파일이 없습니다: {p}\n"
            "  먼저 `python pipeline.py collect` 를 돌리거나,\n"
            "  `python pipeline.py generate --topic \"제목\"` 로 주제를 직접 넣으세요."
        )
    return extract_json(p.read_text(encoding="utf-8"))


def build_prompt(cfg: dict[str, Any], topic: dict[str, Any]) -> str:
    template = load_prompt(cfg, "write.txt")
    return template.format(
        niche=cfg["niche"],
        title=topic["title"],
        angle=topic.get("angle", "실무자 관점에서 구체적으로"),
        language="한국어" if cfg["language"] == "ko" else "English",
        target_words=cfg["generate"]["target_words"],
    )


def write_draft(cfg: dict[str, Any], topic: dict[str, Any], body: str) -> Path:
    slug = topic.get("slug") or slugify(topic["title"])
    filename = f"{date.today():%Y%m%d}-{slug}.md"
    path = drafts_dir(cfg) / filename

    post = frontmatter.Post(
        body,
        title=topic["title"],
        slug=slug,
        angle=topic.get("angle", ""),
        language=cfg["language"],
        created=f"{date.today():%Y-%m-%d}",
        # 안전장치: 사람이 직접 true 로 바꾸기 전엔 발행 불가
        reviewed=False,
        published_url="",
    )
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return path


def generate_one(cfg: dict[str, Any], topic: dict[str, Any]) -> Path:
    prompt = build_prompt(cfg, topic)
    body = claude_cli.ask(cfg, prompt)
    return write_draft(cfg, topic, body)


def run(cfg: dict[str, Any], topic_title: str | None = None) -> list[Path]:
    """topic_title 이 주어지면 그 주제 하나만, 아니면 수집된 주제 전부."""
    if topic_title:
        topics = [{"title": topic_title, "slug": slugify(topic_title)}]
    else:
        topics = load_topics(cfg)

    if not topics:
        raise PipelineError("생성할 주제가 없습니다.")

    written: list[Path] = []
    for i, topic in enumerate(topics, 1):
        print(f"[generate] ({i}/{len(topics)}) {topic['title']}")
        try:
            path = generate_one(cfg, topic)
        except PipelineError as e:
            print(f"[generate] 실패 — 건너뜁니다: {e}")
            continue
        print(f"[generate] 저장: {path.name}")
        written.append(path)

    return written
