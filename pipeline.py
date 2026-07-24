#!/usr/bin/env python3
"""네이버 인기종목 공시 브리핑 — CLI 진입점.

매일 08:00 (cron)
  [1.네이버 인기종목 TOP20] → [2.그 종목들의 공시] → [3.3줄요약+방향]
  → [4.HTML 리포트 서버 저장] → [5.텔레그램 알림]

사용법:
  python pipeline.py daily                 # 전체 실행 (cron 진입점)
  python pipeline.py daily --skip-holiday  # 주말·공휴일이면 실행 안 함 (cron용)
  python pipeline.py daily --dry-run       # 저장만, 텔레그램·기록 없이
  python pipeline.py naver                 # 인기 검색 종목 (디버그)
  python pipeline.py dart                  # 인기종목 공시 매칭 (디버그)
  python pipeline.py telegram setup|test
"""

from __future__ import annotations

import argparse
import sys
import traceback
from collections import Counter
from datetime import datetime

from steps import brief, dart, naver, notify, report
from steps.common import PipelineError, holiday_reason, load_config


def cmd_daily(args, cfg) -> int:
    dry = args.dry_run
    now = datetime.now()
    if dry:
        print("[daily] --dry-run: 저장만 하고 텔레그램·기록은 생략합니다.")

    # 0. 휴일이면 건너뛴다 (증시 휴장일엔 새 공시가 없음). cron 자동 실행 전용
    #    플래그라 수동 실행(--skip-holiday 없이)에는 영향 없음. 조용히 종료한다.
    if getattr(args, "skip_holiday", False):
        reason = holiday_reason(now.date())
        if reason:
            print(f"[daily] 오늘은 휴일({reason})이라 실행을 건너뜁니다.")
            return 0

    # 1. 네이버 인기 검색 종목 TOP N
    stocks = naver.fetch_popular_stocks(cfg)
    if not stocks:
        raise PipelineError("네이버 인기 검색 종목을 가져오지 못했습니다.")

    # 2. 그 종목들의 공시 (종목코드 매칭, 절차성·기수록 제외)
    by_code = dart.disclosures_for_codes(cfg, [s["code"] for s in stocks])

    # 3. 공시 있는 종목만 3줄 요약(+방향 판정)
    covered = brief.summarize_stocks(cfg, stocks, by_code)
    if not covered:
        msg = "인기 검색 종목 중 다룰 새 공시가 없습니다. 리포트를 건너뜁니다."
        print(f"[daily] {msg}")
        if not dry:
            notify.send(
                cfg,
                "<b>네이버 인기종목 공시 브리핑</b>\n"
                f"<i>{now:%Y-%m-%d %H:%M} 기준</i>\n\n"
                f"오늘은 다룰 새 공시가 없어 리포트를 건너뜁니다.",
            )
        return 0

    # 4. HTML 리포트 렌더 + 서버 폴더 저장
    _, url = report.save(cfg, now, stocks, covered)

    if dry:
        print(f"[daily] --dry-run 종료. URL: {url}")
        return 0

    # 5. 기록(중복 게재 방지) + 텔레그램 알림
    disclosures = [d for c in covered for d in c["disclosures"]]
    dart.mark_seen(cfg, disclosures)
    dirs = Counter(d.get("direction", "중립") for d in disclosures)
    names = ", ".join(f"{c['name']}({c['code']})" for c in covered)
    notify.send(
        cfg,
        "<b>네이버 인기종목 공시 브리핑</b>\n"
        f"<i>{now:%Y-%m-%d %H:%M} 기준</i>\n\n"
        f"공시 {len(covered)}종목 · {len(disclosures)}건\n"
        f"긍정 {dirs['긍정']} · 부정 {dirs['부정']} · 중립 {dirs['중립']}\n\n"
        f"{notify.escape(names)}\n\n"
        f'<a href="{url}">리포트 열기</a>',
    )
    return 0


def cmd_naver(args, cfg) -> int:
    stocks = naver.fetch_popular_stocks(cfg)
    for s in stocks:
        print(f"  {s['rank']:>2}. {s['name']} ({s['code']})")
    return 0


def cmd_dart(args, cfg) -> int:
    stocks = naver.fetch_popular_stocks(cfg)
    by_code = dart.disclosures_for_codes(cfg, [s["code"] for s in stocks])
    for s in stocks:
        ds = by_code.get(s["code"], [])
        if ds:
            print(f"  {s['rank']:>2}. {s['name']}")
            for d in ds:
                print(f"        {d['rcept_dt']}  {d['report_nm']}")
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
        description="네이버 인기종목 공시 브리핑 (매일 08시 자동 실행)",
    )
    parser.add_argument("-c", "--config", default="config.yaml", help="설정 파일 경로")
    sub = parser.add_subparsers(dest="command", required=True)

    p_daily = sub.add_parser("daily", help="전체 파이프라인 실행 (cron 진입점)")
    p_daily.add_argument(
        "--dry-run", action="store_true",
        help="저장만 하고 텔레그램·기록은 생략",
    )
    p_daily.add_argument(
        "--skip-holiday", action="store_true",
        help="주말·공휴일이면 실행하지 않고 종료 (cron 자동 실행용)",
    )
    p_daily.set_defaults(func=cmd_daily)

    p_naver = sub.add_parser("naver", help="네이버 인기 검색 종목 (디버그)")
    p_naver.set_defaults(func=cmd_naver)

    p_dart = sub.add_parser("dart", help="인기종목 공시 매칭 (디버그)")
    p_dart.set_defaults(func=cmd_dart)

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
            notify.send(cfg, f"<b>공시 브리핑 실패</b>\n\n{notify.escape(str(e))}")
        return 1
    except KeyboardInterrupt:
        print("\n중단했습니다.", file=sys.stderr)
        return 130
    except Exception:
        # 예상 못 한 예외도 무인 실행에서는 반드시 알림
        err = traceback.format_exc()
        print(err, file=sys.stderr)
        if args.command == "daily" and not args.dry_run:
            notify.send(cfg, f"<b>공시 브리핑 실패 (예상외 오류)</b>\n\n{notify.escape(err[-800:])}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
