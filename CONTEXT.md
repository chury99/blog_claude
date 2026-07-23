# 공시 브리핑 자동 블로그 — 프로젝트 컨텍스트

> Claude Code가 이 프로젝트를 이어받아 작업하기 위한 문서.
> 결정사항, 제약조건, 구조를 담는다. (2026-07-23 전면 재설계)

---

## 1. 프로젝트 한 줄 요약

매일 아침 08시에 **국내주식 공시를 긍정 5개 · 부정 5개로 골라 각 3줄로 요약**한 글을
블로그에 **자동 발행**해 수익을 창출한다. 운영자와의 소통은 텔레그램.

핵심 차별점: **짧고 쉽게.** 장황하면 안 읽는다. 핵심만 3줄.

---

## 2. 개발자 배경

- Python 개발자이자 알고리즘 트레이더. KRX 자동매매 시스템 구축 경험(Kiwoom API, asyncio, 텔레그램 봇).
- 서버는 **Mac Mini**. 원격 제어는 MacBook Air.
- **Claude Pro 구독** 보유 → API 종량 과금 대신 `claude -p` 헤드리스 모드 사용.
  (Pro 는 사용량 한도가 Max 보다 낮다. daily 1회에 claude 호출 약 12번 —
  자동 실행 시 한도 초과 여부를 지켜봐야 한다.)
- 한국어로 소통. 응답은 항상 한글.

---

## 3. 핵심 결정사항

### 3-1. 콘텐츠 정의 (2026-07-23 사용자 확정)
- 검색어 트렌드에서 **국내주식 관련 항목**을 찾아낸다.
- 관련 공시(DART)를 파악해 **긍정 5개, 부정 5개로 제한**한다.
- 각 공시를 **3줄 요약**한다. 쉽고 간단하게.
- 트렌드에 걸린 종목의 공시를 최우선으로 다루되, 부족하면 그날의 주요 공시로 채운다.

### 3-2. 자동 발행 전환 (구 원칙 폐기)
- 구버전의 "완전 무인 발행 금지" 원칙은 **2026-07-23 사용자 결정으로 폐기**했다.
  이 프로젝트는 매일 08시 무인 발행이 전제다.
- 대신 다음 완화 장치를 둔다:
  1. **킬스위치**: `config.yaml` 의 `publish.auto: false` 로 바꾸면 발행 없이 파일만 생성.
  2. **실패 시 발행 안 함**: 파이프라인 어느 단계든 실패하면 불완전한 글을 올리지 않고
     텔레그램으로 에러를 보고한다.
  3. **사후 통보**: 발행 성공/실패/스킵 모두 텔레그램으로 알린다.
  4. **지어내기 금지**: 공시 본문을 확보하지 못하면 제목에서 확실한 것만 쓴다.
     모든 글 하단에 "투자 권유 아님" 디스클레이머 고정.

### 3-3. 데이터 소스
- **공시**: DART OpenAPI (opendart.fss.or.kr, 무료. 인증키 필요 — `config/dart.json`).
  - 목록: `list.json` (유가 Y / 코스닥 K, 상장사만)
  - 본문: `document.xml` (zip) → 텍스트 추출 → 요약 입력으로 사용
- **트렌드**: Google Trends RSS `trends.google.com/trending/rss?geo=KR` (시드 불필요, 무료).
  pytrends 는 구글 백엔드 변경으로 seedless 엔드포인트가 404 → 사용하지 않는다.
- 트렌드 검색어 → 상장사 연결은 Claude가 판단한다 (예: 인물·제품·사건 → 관련 종목).

### 3-4. 글 생성은 `claude -p` (헤드리스)
- Pro 구독 범위 내 CLI 호출. `subprocess` 로 stdout 회수.
- 실행 파일은 `~/.local/bin/claude` 절대경로 고정 (launchd 는 PATH 가 최소한이라).

### 3-5. 발행 플랫폼 → Ghost 우선, 어댑터로 추상화
- Ghost Admin API (JWT 인증). `publish.adapter: dryrun` 으로 무발행 테스트 가능.
- Medium(API 중단)/Substack(공식 API 없음)은 부적합 판정 유지.

### 3-6. 스케줄링 — launchd 매일 08:00
- `launchd/com.chury99.blog-daily.plist` (등록은 사용자가 직접).
- Mac 이 잠들어 있으면 깨어난 직후 밀린 실행이 돈다(StartCalendarInterval 특성).
  확실히 하려면 `pmset repeat wakeorpoweron MTWRFSU 07:55:00` 권장.

### 3-7. 소통은 텔레그램
- 자격증명은 `config/telegram.json` (git 제외, lotto_claude 와 동일 방식).
- 발행 결과·에러·스킵 모두 알림. **발행 승인 기능은 두지 않는다** — 어차피 자동 발행이고,
  중단은 킬스위치로 한다.

---

## 4. 파이프라인 구조

```
매일 08:00 (launchd)
   │
[1. 트렌드]  Google Trends RSS(KR) → Claude: 국내 상장사 관련 검색어만 추출
   │
[2. 공시수집] DART list.json (최근 N일, 상장사만, 기수록분 제외)
   │           트렌드에 걸린 종목의 공시는 🔥 표시
[3. 선정]    Claude: 긍정 5 + 부정 5 선정 (🔥 최우선, 다음은 중요도)
   │
[4. 요약]    공시별 본문(document.xml) 확보 → Claude: 3줄 요약
   │
[5. 조립]    posts/YYYYMMDD-brief.md (프론트매터 + 마크다운)
   │
[6. 발행]    publish.auto=true → Ghost 공개 발행 / false → 파일만
   │
[7. 알림]    텔레그램: 성공(링크)/실패(에러)/스킵(공시 없음)
```

- 다룬 공시는 `data/seen.json` 에 기록해 다음 날 중복 게재를 막는다.
- 공시가 0건(휴일 등)이면 발행을 건너뛰고 텔레그램으로만 알린다.

---

## 5. CLI

```
python pipeline.py daily            # 전체 실행 (08시 launchd 가 부르는 진입점)
python pipeline.py daily --dry-run  # 발행·기록 없이 글 생성까지만
python pipeline.py trends           # 1단계만 (디버그)
python pipeline.py dart             # 2단계만 (디버그)
python pipeline.py publish <파일> --live   # 생성된 글 수동 발행 (auto=false 운용 시)
python pipeline.py telegram setup|test
```

---

## 6. 비밀값 취급

- `.env` (git 제외): `GHOST_ADMIN_API_KEY`
- `config/dart.json` (git 제외): DART 인증키 (`api_key`)
- `config/telegram.json` (git 제외): 텔레그램 토큰/채팅ID
- `config.yaml` 에는 비밀값을 두지 않는다. 에러 메시지에 토큰을 싣지 않는다.

---

## 7. 미결 사항

- Ghost 사이트 미개설 — `publish.ghost.api_url` 이 아직 `CHANGE-ME`.
- DART 인증키 — 발급 완료, `config/dart.json` 에 저장됨. (실호출 검증 완료)
- launchd 미등록 — 위 두 개가 채워진 뒤 사용자가 등록.
- 수익화 방식(광고/제휴)은 코드 범위 밖. 블로그 개설 후 별도 논의.
