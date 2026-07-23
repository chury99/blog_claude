#!/usr/bin/env python3
"""공시 브리핑 자동 블로그 — CLI 진입점.

매일 08:00 (launchd)
  [1.트렌드] → [2.공시수집] → [3.선정 긍5/부5] → [4.3줄요약] → [5.조립] → [6.발행] → [7.알림]

사용법:
  python pipeline.py daily            # 전체 실행 (launchd 가 부르는 진입점)
  python pipeline.py daily --dry-run  # 발행·기록 없이 글 생성까지만
  python pipeline.py trends           # 1단계만 (디버그)
  python pipeline.py dart             # 2단계만 (디버그)
  python pipeline.py publish 20260723-brief --live
  python pipeline.py telegram setup|test
"""

from __future__ import annotations

import argparse
import sys
import traceback

from dotenv import load_dotenv

from steps import brief, dart, notify, publish, trends
from steps.common import PipelineError, load_config


def cmd_daily(args, cfg) -> int:
    dry = args.dry_run
    if dry:
        print("[daily] --dry-run: 발행/기록 없이 글 생성까지만 합니다.")

    # 1. 트렌드에서 주식 관련 검색어
    trend_stocks = trends.run(cfg)

    # 2. 공시 후보 풀
    pool = dart.build_pool(cfg, trend_stocks)
    if not pool:
        msg = "오늘은 다룰 새 공시가 없습니다 (휴일 등). 발행을 건너뜁니다."
        print(f"[daily] {msg}")
        if not dry:
            notify.send(cfg, f"⏭️ <b>공시 브리핑 스킵</b>\n{notify.escape(msg)}")
        return 0

    # 3. 긍정/부정 선정
    positive, negative = brief.select(cfg, pool)
    if not positive and not negative:
        raise PipelineError("선정된 공시가 0건입니다. select.txt 프롬프트를 점검하세요.")

    # 4. 3줄 요약
    positive = brief.summarize_all(cfg, positive, "긍정")
    negative = brief.summarize_all(cfg, negative, "부정")

    # 5. 글 조립
    post_path = brief.write_post(cfg, trend_stocks, positive, negative)

    # 6. 발행 (킬스위치/드라이런 시 파일만)
    if dry:
        print(f"[daily] --dry-run 종료. 결과 확인: {post_path}")
        return 0
    if not cfg["publish"]["auto"]:
        print("[daily] publish.auto=false — 발행하지 않고 파일만 남깁니다.")
        notify.send(
            cfg,
            "📄 <b>공시 브리핑 생성 (발행 안 함)</b>\n"
            f"{notify.escape(post_path.name)}\n"
            "publish.auto=false 상태입니다. 수동 발행: "
            f"python pipeline.py publish {post_path.stem} --live",
        )
        return 0

    url = publish.run(cfg, post_path, live=True)

    # 7. 기록 + 알림
    dart.mark_seen(cfg, positive + negative)
    notify.send(
        cfg,
        f"🚀 <b>공시 브리핑 발행 완료</b>\n"
        f"긍정 {len(positive)} · 부정 {len(negative)}\n{url}",
    )
    return 0


def cmd_trends(args, cfg) -> int:
    picked = trends.run(cfg)
    print(f"\n주식 관련 검색어 {len(picked)}개")
    return 0


def cmd_dart(args, cfg) -> int:
    pool = dart.build_pool(cfg, [])
    for d in pool[:20]:
        print(f"  {d['rcept_dt']} {d['corp_name']:<20} {d['report_nm']}")
    if len(pool) > 20:
        print(f"  ... 외 {len(pool) - 20}건")
    return 0


def cmd_publish(args, cfg) -> int:
    url = publish.run(cfg, args.post, live=args.live)
    notify.send(
        cfg,
        f"🚀 <b>{'공개 발행' if args.live else '플랫폼 draft'}</b>\n"
        f"{notify.escape(args.post)}\n{url}",
    )
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
        description="공시 브리핑 자동 블로그 (매일 08시 자동 발행)",
    )
    parser.add_argument("-c", "--config", default="config.yaml", help="설정 파일 경로")
    sub = parser.add_subparsers(dest="command", required=True)

    p_daily = sub.add_parser("daily", help="전체 파이프라인 실행 (launchd 진입점)")
    p_daily.add_argument(
        "--dry-run", action="store_true",
        help="발행/기록 없이 글 생성까지만 (posts/ 에 파일은 남음)",
    )
    p_daily.set_defaults(func=cmd_daily)

    p_trends = sub.add_parser("trends", help="1단계만: 트렌드→주식 검색어 (디버그)")
    p_trends.set_defaults(func=cmd_trends)

    p_dart = sub.add_parser("dart", help="2단계만: DART 공시 후보 풀 (디버그)")
    p_dart.set_defaults(func=cmd_dart)

    p_publish = sub.add_parser("publish", help="글 수동 발행 (publish.auto=false 운용 시)")
    p_publish.add_argument("post", help="글 파일명 (예: 20260723-brief)")
    p_publish.add_argument("--live", action="store_true", help="공개 발행 (기본: 플랫폼 draft)")
    p_publish.set_defaults(func=cmd_publish)

    p_tg = sub.add_parser("telegram", help="텔레그램 알림 설정/점검")
    p_tg.add_argument(
        "action", choices=["setup", "test"],
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
    except PipelineError as e:
        print(f"\n오류: {e}", file=sys.stderr)
        return 1

    try:
        return args.func(args, cfg)
    except PipelineError as e:
        print(f"\n오류: {e}", file=sys.stderr)
        # 무인 실행(daily)에서 죽으면 텔레그램으로도 알린다
        if args.command == "daily" and not args.dry_run:
            notify.send(cfg, f"❌ <b>공시 브리핑 실패</b>\n{notify.escape(str(e))}")
        return 1
    except KeyboardInterrupt:
        print("\n중단했습니다.", file=sys.stderr)
        return 130
    except Exception:
        # 예상 못 한 예외도 무인 실행에서는 반드시 알림
        err = traceback.format_exc()
        print(err, file=sys.stderr)
        if args.command == "daily" and not args.dry_run:
            notify.send(cfg, f"❌ <b>공시 브리핑 실패 (예상외 오류)</b>\n{notify.escape(err[-800:])}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
