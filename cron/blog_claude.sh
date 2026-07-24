#! /bin/bash
#
# 네이버 인기종목 공시 브리핑 — 매일 08시 cron 실행 스크립트.
#
# 배포: 이 파일을 /Users/sh/blog_claude.sh 로 복사하고 실행권한을 준 뒤,
#       crontab 에 아래 한 줄을 추가한다(기존 항목은 유지).
#
#   0 8 * * * /Users/sh/blog_claude.sh
#
# 로그는 iCloud python_log 폴더에 날짜별로 쌓인다. 다른 프로젝트
# (refresh_kakaoapi.sh 등)와 동일한 패턴.

cd "/Users/chury99/PycharmProjects/blog_claude"

TODAY=$(date "+%Y%m%d")
LOG="/Users/chury99/Library/Mobile Documents/com~apple~CloudDocs/python_log/blog_claude_$TODAY.log"

PROJECT="/Users/chury99/PycharmProjects"
VENV="$PROJECT/blog_claude/.venv"

echo "" >> "$LOG"
echo "----- $(date) -----" >> "$LOG"
source "$VENV/bin/activate"
$VENV/bin/python $PROJECT/blog_claude/pipeline.py daily --skip-holiday >> "$LOG" 2>&1
