#!/usr/bin/env python3
"""콘텐츠 자동화 파이프라인 — CLI 진입점.

  [1. 주제수집] → [2. 초안생성] → [3. 사람검수 ⏸️] → [4. 발행]

3단계는 코드가 아니라 사람이 한다. 파이프라인은 2단계에서 멈추는 게 정상이다.

사용법:
  python pipeline.py collect
  python pipeline.py generate --topic "제목"
  python pipeline.py review
  python pipeline.py publish 20260717-my-slug --live
"""

from __future__ import annotations

import argparse
import sys

import frontmatter
from dotenv import load_dotenv

from steps import collect, generate, notify, publish
from steps.common import PipelineError, drafts_dir, load_config


def cmd_collect(args, cfg) -> int:
    collect.run(cfg)
    print("\n다음: python pipeline.py generate")
    return 0


def cmd_generate(args, cfg) -> int:
    written = generate.run(cfg, topic_title=args.topic)
    if not written:
        print("생성된 초안이 없습니다.")
        return 1
    print(f"\n초안 {len(written)}개 생성. 파이프라인은 여기서 멈춥니다.")
    print("초안을 읽고 실전 데이터를 채운 뒤 프론트매터의 reviewed 를 true 로 바꾸세요.")
    print("다음: python pipeline.py review")

    if cfg.get("notify", {}).get("telegram", {}).get("on_drafts_ready"):
        files = "\n".join(f"• {p.name}" for p in written)
        notify.send(cfg, f"📝 <b>초안 {len(written)}개 검수 대기</b>\n{files}")
    return 0


def cmd_review(args, cfg) -> int:
    """검수 대기 중인 초안 목록. 발행 전 상태 확인용."""
    drafts = sorted(drafts_dir(cfg).glob("*.md"))
    if not drafts:
        print("초안이 없습니다.")
        return 0

    print(f"{'상태':<12} {'파일':<45} 제목")
    print("-" * 90)
    for path in drafts:
        post = frontmatter.load(path)
        if post.get("published_url"):
            status = "발행됨"
        elif post.get("reviewed"):
            status = "검수완료"
        else:
            status = "검수대기"
        print(f"{status:<12} {path.name:<45} {post.get('title', '')}")
    return 0


def cmd_publish(args, cfg) -> int:
    if args.live:
        # 안전장치 3: 공개 발행은 되돌리기 어려우므로 한 번 더 확인
        answer = input(f"'{args.draft}' 를 실제로 공개 발행합니다. 계속할까요? [y/N] ")
        if answer.strip().lower() != "y":
            print("취소했습니다.")
            return 1
    url = publish.run(cfg, args.draft, live=args.live)

    if cfg.get("notify", {}).get("telegram", {}).get("on_published"):
        status = "공개 발행" if args.live else "플랫폼 draft"
        notify.send(cfg, f"🚀 <b>{status}</b>\n{args.draft}\n{url}")
    return 0


def cmd_telegram(args, cfg) -> int:
    if args.action == "setup":
        notify.setup(cfg, token=args.token, chat_id=args.chat_id)
    else:
        notify.check(cfg)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeline.py",
        description="콘텐츠 자동화 파이프라인 (초안 생성까지 자동, 발행은 수동 승인)",
    )
    parser.add_argument("-c", "--config", default="config.yaml", help="설정 파일 경로")
    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser("collect", help="1단계: 주제 수집 + Claude 필터")
    p_collect.set_defaults(func=cmd_collect)

    p_generate = sub.add_parser("generate", help="2단계: claude -p 로 초안 생성")
    p_generate.add_argument(
        "--topic",
        help="주제를 직접 지정(수집 단계 없이 하나만 생성). 생략 시 수집된 주제 전부.",
    )
    p_generate.set_defaults(func=cmd_generate)

    p_review = sub.add_parser("review", help="3단계: 초안 검수 상태 확인")
    p_review.set_defaults(func=cmd_review)

    p_publish = sub.add_parser("publish", help="4단계: 발행 (기본 = 플랫폼 draft)")
    p_publish.add_argument("draft", help="초안 파일명 (예: 20260717-my-slug)")
    p_publish.add_argument(
        "--live",
        action="store_true",
        help="플랫폼 draft 가 아니라 실제 공개 발행. 확인 프롬프트가 뜬다.",
    )
    p_publish.set_defaults(func=cmd_publish)

    p_tg = sub.add_parser("telegram", help="텔레그램 알림 설정/점검")
    p_tg.add_argument(
        "action",
        choices=["setup", "test"],
        help="setup: 토큰 저장 + chat_id 자동 탐지 / test: 저장된 설정으로 발송 확인",
    )
    p_tg.add_argument("--token", help="BotFather 토큰 (생략 시 설정 파일에서 읽음)")
    p_tg.add_argument("--chat-id", help="chat_id 직접 지정 (자동 탐지 건너뜀)")
    p_tg.set_defaults(func=cmd_telegram)

    return parser


def main() -> int:
    load_dotenv()
    args = build_parser().parse_args()
    try:
        cfg = load_config(args.config)
        return args.func(args, cfg)
    except PipelineError as e:
        print(f"\n오류: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n중단했습니다.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
