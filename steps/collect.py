"""1단계: 주제 수집(Google Trends / Reddit) → Claude 필터 → 상위 N개 선정.

수집 소스는 config.yaml 에서 켜고 끈다. 소스가 실패해도
파이프라인 전체를 죽이지 않고 해당 소스만 건너뛴다.
"""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from typing import Any

import requests

from . import claude_cli
from .common import PipelineError, extract_json, load_prompt, slugify, topics_path

_TRENDS_RSS_URL = "https://trends.google.com/trending/rss"


def collect_google_trends(cfg: dict[str, Any]) -> list[str]:
    """국가별 실시간 인기 검색어 RSS 피드. 시드 키워드 없이 그 나라 전체의
    관심사를 그대로 가져온다(related_queries 처럼 특정 주제 근방으로 한정하지 않음).
    """
    conf = cfg["collect"]["sources"]["google_trends"]
    candidates: list[str] = []
    for geo in conf["geos"]:
        try:
            resp = requests.get(_TRENDS_RSS_URL, params={"geo": geo}, timeout=15)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            titles = [
                title.strip()
                for item in root.iter("item")
                if (title := item.findtext("title")) and title.strip()
            ]
            candidates.extend(titles)
            print(f"[collect] Google Trends RSS({geo}): 후보 {len(titles)}개")
        except Exception as e:
            print(f"[collect] Google Trends RSS({geo}) 실패 — 건너뜀: {e}")

    return candidates


def collect_reddit(cfg: dict[str, Any]) -> list[str]:
    conf = cfg["collect"]["sources"]["reddit"]
    try:
        import praw
    except ImportError:
        print("[collect] praw 미설치 — Reddit 건너뜀")
        return []

    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("[collect] REDDIT_CLIENT_ID/SECRET 미설정 — Reddit 건너뜀")
        return []

    candidates: list[str] = []
    try:
        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=os.getenv("REDDIT_USER_AGENT", "content-pipeline/0.1"),
        )
        for sub in conf["subreddits"]:
            for post in reddit.subreddit(sub).hot(limit=conf["limit"]):
                if not post.stickied:
                    candidates.append(post.title)
    except Exception as e:
        print(f"[collect] Reddit 실패 — 건너뜀: {e}")
        return []

    print(f"[collect] Reddit: 후보 {len(candidates)}개")
    return candidates


def filter_with_claude(cfg: dict[str, Any], candidates: list[str]) -> list[dict[str, Any]]:
    top_n = cfg["collect"]["top_n"]
    template = load_prompt(cfg, "filter.txt")
    prompt = template.format(
        niche=cfg["niche"],
        top_n=top_n,
        candidates="\n".join(f"- {c}" for c in candidates),
    )
    topics = extract_json(claude_cli.ask(cfg, prompt))

    if not isinstance(topics, list):
        raise PipelineError(f"필터가 배열이 아닌 값을 반환했습니다: {type(topics)}")

    normalized: list[dict[str, Any]] = []
    for t in topics[:top_n]:
        if not isinstance(t, dict) or "title" not in t:
            continue
        t.setdefault("slug", slugify(t["title"]))
        normalized.append(t)
    return normalized


def run(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[str] = []
    sources = cfg["collect"]["sources"]

    if sources["google_trends"]["enabled"]:
        candidates += collect_google_trends(cfg)
    if sources["reddit"]["enabled"]:
        candidates += collect_reddit(cfg)

    # 중복 제거(순서 유지)
    candidates = list(dict.fromkeys(c.strip() for c in candidates if c.strip()))

    if not candidates:
        raise PipelineError(
            "수집된 후보가 없습니다. config.yaml 의 collect.sources 설정과 "
            "의존성 설치 상태를 확인하세요."
        )

    print(f"[collect] 중복 제거 후 {len(candidates)}개 → Claude 필터링")
    topics = filter_with_claude(cfg, candidates)

    out = topics_path(cfg)
    out.write_text(json.dumps(topics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[collect] 주제 {len(topics)}개 선정 → {out}")
    for t in topics:
        print(f"  - {t['title']}")
    return topics
