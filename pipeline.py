#!/usr/bin/env python3
"""네이버 인기종목 공시 브리핑 — CLI 진입점.

매일 07:00 (cron)
  [1.'특징주' 기사 수집] → [2.종목별로 묶어 이슈 3줄+방향]
  → [3.간밤 미국 증시] → [4.HTML 리포트 서버 저장] → [5.텔레그램 알림]

사용법:
  python pipeline.py daily                 # 전체 실행 (cron 진입점)
  python pipeline.py daily --skip-holiday  # 주말·공휴일이면 실행 안 함 (cron용)
  python pipeline.py daily --dry-run       # 저장만, 텔레그램 없이
  python pipeline.py highlight             # 오늘의 특징주 (디버그)
  python pipeline.py market                # 간밤 미국 증시 시황 (디버그)
  python pipeline.py theme                 # 테마별 이슈 (디버그, daily 미사용)
  python pipeline.py naver|feature|dart    # 이전 방식 (디버그, daily 미사용)
  python pipeline.py telegram setup|test
"""

from __future__ import annotations

import argparse
import sys
import traceback
from collections import Counter
from datetime import datetime

from steps import brief, dart, feature, highlight, market, naver, notify, report, theme
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

    # 1~2. '특징주' 기사 수집 → 종목별로 묶어 이슈 정리(+긍정/부정 판정)
    stocks = highlight.pick(cfg)
    if not stocks:
        msg = "오늘 다룰 특징주 기사가 없습니다. 리포트를 건너뜁니다."
        print(f"[daily] {msg}")
        if not dry:
            notify.send(
                cfg,
                "<b>오늘의 특징주 브리핑</b>\n"
                f"<i>{now:%Y-%m-%d %H:%M} 기준</i>\n\n"
                f"오늘은 다룰 기사가 없어 리포트를 건너뜁니다.",
            )
        return 0

    # 3. 간밤 미국 증시 시황 (곁들이는 정보라 실패해도 리포트는 그대로 나간다)
    #    다룰 종목이 있을 때만 부른다 — 스킵하는 날 claude 호출을 낭비하지 않으려고.
    us = market.brief_us(cfg)

    # 4. HTML 리포트 렌더 + 서버 폴더 저장
    _, url = report.save(cfg, now, stocks, us)

    if dry:
        print(f"[daily] --dry-run 종료. URL: {url}")
        return 0

    # 5. 텔레그램 알림
    dirs = Counter(s.get("direction", "중립") for s in stocks)
    names = ", ".join(f"{s['name']}({s['code']})" for s in stocks)
    notify.send(
        cfg,
        "<b>오늘의 특징주 브리핑</b>\n"
        f"<i>{now:%Y-%m-%d %H:%M} 기준</i>\n\n"
        f"특징주 {len(stocks)}종목\n"
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


def cmd_highlight(args, cfg) -> int:
    for s in highlight.pick(cfg):
        ratio = s.get("ratio")
        move = f"{ratio:+.2f}%" if isinstance(ratio, (int, float)) else ""
        print(f"\n  [{s['direction']}] {s['name']} ({s['code']}) {s.get('price', '')} {move}")
        for l in s["lines"]:
            print(f"      - {l}")
        for a in s.get("sources", []):
            print(f"      · {a['title'][:54]} — {a['press']}")
    return 0


def cmd_theme(args, cfg) -> int:
    themes, covered = theme.pick(cfg)
    print(f"\n  [테마 목록 상위 10]")
    for t in themes[:10]:
        print(f"    {t['name'][:28]:<30} {t['ratio']:+.2f}%")
    for c in covered:
        print(f"\n  [{c['direction']}] {c['name']} ({c['ratio']:+.2f}%)")
        for l in c["lines"]:
            print(f"      - {l}")
        rel = ", ".join(f"{s['name']}({s['ratio']:+.2f}%)" for s in c["stocks"]
                        if isinstance(s.get("ratio"), (int, float)))
        print(f"      관련: {rel}")
        for s in c.get("sources", []):
            print(f"      · {s['title'][:52]} — {s['press']}")
    return 0


def cmd_feature(args, cfg) -> int:
    stocks = naver.fetch_popular_stocks(cfg)
    for f in feature.pick(cfg, stocks):
        ratio = f.get("ratio")
        move = f"{ratio:+.2f}%" if isinstance(ratio, (int, float)) else ""
        print(f"\n  [{f['direction']}] {f['rank']}위 {f['name']} ({f['code']}) {move}")
        for l in f["lines"]:
            print(f"      - {l}")
        for s in f.get("sources", []):
            print(f"      · {s['title'][:52]} — {s['press']}")
    return 0


def cmd_market(args, cfg) -> int:
    us = market.brief_us(cfg)
    if not us:
        print("  (미국 지수를 가져오지 못했습니다)")
        return 0
    for i in us["indices"]:
        print(f"  {i['label']:>10}  {i['close']:>12}  {i['diff']:>10} ({i['ratio']:+.2f}%)")
    print(f"\n  시황: {us['summary'] or '(요약 실패)'}")
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
        description="오늘의 특징주 브리핑 (매일 07시 자동 실행)",
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

    p_hl = sub.add_parser("highlight", help="오늘의 특징주 (디버그)")
    p_hl.set_defaults(func=cmd_highlight)

    p_theme = sub.add_parser("theme", help="테마별 이슈 (디버그, daily 미사용)")
    p_theme.set_defaults(func=cmd_theme)

    p_feat = sub.add_parser("feature", help="종목별 특징주 (디버그, daily 미사용)")
    p_feat.set_defaults(func=cmd_feature)

    p_dart = sub.add_parser("dart", help="인기종목 공시 매칭 (디버그, daily 에서는 미사용)")
    p_dart.set_defaults(func=cmd_dart)

    p_mkt = sub.add_parser("market", help="간밤 미국 증시 시황 (디버그)")
    p_mkt.set_defaults(func=cmd_market)

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
