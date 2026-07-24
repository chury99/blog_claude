# 네이버 인기종목 공시 브리핑

매일 아침 08시, **네이버 금융 인기 검색 종목 TOP 20** 중 공시가 있는 종목을 찾아
그 공시를 **3줄(핵심 / 세부·해석 / 예상 주가 방향)**로 정리한 HTML 리포트를 자체
웹서버에 올리고 텔레그램으로 링크를 보낸다.

설계 배경은 [CONTEXT.md](CONTEXT.md) 참고.

```
매일 08:00 (cron)
[1.네이버 TOP20] → [2.종목코드로 공시 매칭] → [3.공시별 3줄 요약+방향] → [4.HTML 서버 저장] → [5.텔레그램]
 finance.naver     DART OpenAPI               claude -p              report.web_dir     링크 발송
```

## 설치

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config/dart.json.example config/dart.json   # DART 인증키 입력 후 chmod 600
python pipeline.py telegram setup --token <BotFather토큰>
```

`claude` CLI(헤드리스 `-p`)가 필요하다. `config.yaml` 의 `generate.claude_bin` 이
절대경로를 가리켜야 한다.

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

## 사용

```bash
python pipeline.py daily            # 전체 실행 (cron 진입점)
python pipeline.py daily --dry-run  # 저장만, 텔레그램·기록 없이
python pipeline.py naver            # 인기 검색 종목 (디버그)
python pipeline.py dart             # 인기종목 공시 매칭 (디버그)
python pipeline.py telegram test    # 알림 점검
```

## 매일 08시 자동 실행 (cron)

다른 프로젝트(`/Users/sh/*.sh`)와 동일하게, 실행 스크립트를 `/Users/sh` 에 두고
crontab 에서 부른다. 스크립트 원본은 [cron/blog_claude.sh](cron/blog_claude.sh).

```bash
cp cron/blog_claude.sh /Users/sh/blog_claude.sh
chmod +x /Users/sh/blog_claude.sh
```

crontab 에 아래 한 줄 추가 (`crontab -e`, 기존 항목은 유지):

```
0 8 * * * /Users/sh/blog_claude.sh
```

로그는 iCloud `python_log/blog_claude_YYYYMMDD.log` 에 날짜별로 쌓인다.

cron 은 잠든 Mac 을 깨우지 못한다. 08시에 확실히 실행하려면 미리 깨워둔다:

```bash
sudo pmset repeat wakeorpoweron MTWRFSU 07:55:00
```

## 출력

- HTML 리포트는 `config.yaml` 의 `report.web_dir` 폴더에 저장되고, `report.url_base`
  주소로 열린다. 이 폴더를 웹서버가 서빙한다.
- 파일명: `YYYYMMDD_네이버인기종목_공시브리핑.html`
- 파이프라인이 실패하면 리포트를 올리지 않고 텔레그램으로 에러를 보낸다.

## 구조

```
pipeline.py          CLI 진입점 / 오케스트레이터
config.yaml          인기종목 수, 공시 범위, 출력 폴더/주소 등
steps/
  claude_cli.py      claude -p subprocess 래퍼
  naver.py           네이버 인기 검색 종목 수집
  dart.py            DART 공시 목록/본문 + 종목코드 매칭 + 기수록 기록
  brief.py           공시별 3줄 요약(+방향 판정)
  report.py          HTML 리포트 렌더 + 서버 폴더 저장
  notify.py          텔레그램 알림
  common.py          설정 로딩, JSON 추출 등 공용 유틸
prompts/
  summarize.txt      3줄 요약 + 방향 판정 프롬프트
cron/                매일 08시 실행용 셸 스크립트 (→ /Users/sh 로 배포)
data/                기수록 공시 기록 (git 제외)
logs/                실행 로그 (git 제외; cron 로그는 iCloud python_log 에도 쌓임)
```

## 비밀값

| 값 | 위치 |
|---|---|
| DART 인증키 | `config/dart.json` → `api_key` |
| 텔레그램 토큰/채팅ID | `config/telegram.json` (`telegram setup` 이 생성) |

전부 git 제외. `config.yaml` 에는 비밀값을 두지 않는다.
