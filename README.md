# 공시 브리핑 자동 블로그

매일 아침 08시, 국내주식 공시를 **긍정 5 · 부정 5**로 골라 각 **3줄 요약**한 글을
블로그에 자동 발행한다. 짧고 쉽게 — 그게 차별점이다.

설계 배경과 결정사항은 [CONTEXT.md](CONTEXT.md) 참고.

```
매일 08:00 (launchd)
[1.트렌드] → [2.공시수집] → [3.선정 긍5/부5] → [4.3줄요약] → [5.조립] → [6.발행] → [7.알림]
 Trends RSS    DART API       claude -p        claude -p     posts/    Ghost API   텔레그램
```

## 설치

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # Ghost 키 입력
cp config/dart.json.example config/dart.json   # DART 인증키 입력 후: chmod 600 config/dart.json
python pipeline.py telegram setup --token <BotFather토큰>
```

`claude` CLI(헤드리스 `-p`)가 필요하다. `config.yaml` 의 `generate.claude_bin` 이
절대경로를 가리켜야 한다 (launchd 는 PATH 가 최소한이라).

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

## 사용

```bash
python pipeline.py daily            # 전체 실행 (launchd 진입점)
python pipeline.py daily --dry-run  # 발행·기록 없이 글 생성까지만
python pipeline.py trends           # 1단계 디버그
python pipeline.py dart             # 2단계 디버그
python pipeline.py publish 20260723-brief --live   # 수동 발행
python pipeline.py telegram test    # 알림 점검
```

## 매일 08시 자동 실행 (launchd)

```bash
cp launchd/com.chury99.blog-daily.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.chury99.blog-daily.plist
```

해제:

```bash
launchctl bootout gui/$(id -u)/com.chury99.blog-daily
```

Mac 이 08시에 자고 있으면 깨어난 직후 밀린 실행이 돈다. 확실히 하려면:

```bash
sudo pmset repeat wakeorpoweron MTWRFSU 07:55:00
```

## 자동 발행 제어

- **킬스위치**: `config.yaml` → `publish.auto: false` — 발행 없이 파일만 생성.
- **무발행 테스트**: `publish.adapter: dryrun` 또는 `daily --dry-run`.
- 파이프라인이 실패하면 불완전한 글을 올리지 않고 텔레그램으로 에러를 보낸다.

## 구조

```
pipeline.py          CLI 진입점 / 오케스트레이터
config.yaml          수집 범위, 선정 개수, 발행 대상 등 설정
steps/
  claude_cli.py      claude -p subprocess 래퍼 (클로드 호출은 전부 여기 경유)
  trends.py          1단계: Trends RSS → 주식 관련 검색어 추출
  dart.py            2단계: DART 공시 목록/본문 + 기수록 기록
  brief.py           3-5단계: 선정 → 3줄 요약 → 글 조립
  publish.py         6단계: Publisher 추상 클래스 + Ghost/DryRun 어댑터
  notify.py          7단계: 텔레그램 알림
  common.py          설정 로딩, slug, JSON 추출 등 공용 유틸
prompts/
  trends_stocks.txt  트렌드→상장사 연결 프롬프트
  select.txt         긍정/부정 선정 프롬프트
  summarize.txt      3줄 요약 프롬프트
launchd/             매일 08시 실행용 plist
posts/               생성된 글 (git 제외)
data/                기수록 공시 기록 (git 제외)
logs/                launchd 실행 로그 (git 제외)
```

다른 플랫폼을 붙이려면 `steps/publish.py` 의 `Publisher` 를 상속해
`make_publisher()` 에 등록하면 된다.

## 비밀값

| 값 | 위치 |
|---|---|
| DART 인증키 | `config/dart.json` → `api_key` |
| Ghost Admin 키 | `.env` → `GHOST_ADMIN_API_KEY` |
| 텔레그램 토큰/채팅ID | `config/telegram.json` (`telegram setup` 이 생성) |

전부 git 제외. `config.yaml` 에는 비밀값을 두지 않는다.
