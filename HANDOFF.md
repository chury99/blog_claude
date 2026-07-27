# 인수인계 — 네이버 인기종목 공시 브리핑

> 새 대화(Claude Code)가 이 프로젝트를 이어받기 위한 문서.
> 설계 배경은 [CONTEXT.md](CONTEXT.md), 사용법은 [README.md](README.md).
> 이 문서는 **무엇이 만들어졌고 무엇이 남았는지**만 담는다.

## 현재 상태 (2026-07-27)

**컨셉이 확정·구현 완료됐고 매일 자동 실행 중이다.** 네이버 금융 인기 검색 종목
TOP 20 → 공시 있는 종목 → 공시별 3줄 요약(핵심/세부·해석/예상 주가 방향, 방향 판정
포함) → HTML 리포트를 자체 웹서버 폴더에 저장 → 텔레그램 링크 발송.

- 저장소: https://github.com/chury99/blog_claude (Public, `main`). 최신 커밋 `daccada`.
- 서버: Mac Mini(이 머신). `claude` CLI 설치 완료(`~/.local/bin/claude`, v2.1.x).
  cron 무인 실행은 `config/claude.json` 의 장기 토큰(`claude setup-token`)으로 인증.
- 의존성: PyYAML, requests, holidays (Ghost·markdown 경로는 제거됨).

## 최근 변경 이력 (최신순)

- **2026-07-27 — cron claude 인증을 장기 토큰으로 전환** (`daccada`). 배경: 이날 아침
  08시 cron 이 `Not logged in` 으로 실패. 원인은 키체인 OAuth 토큰이 며칠 만에
  만료되는데(24일 저녁 만료) 주말 스킵으로 갱신 기회가 없었고, cron 은 GUI 세션이
  아니라 갱신·키체인 접근이 막힌 것. `claude setup-token` 장기 토큰(1년)을
  `config/claude.json` 에 두고 `claude_cli.ask` 가 `CLAUDE_CODE_OAUTH_TOKEN` 으로
  주입하도록 함. 토큰 인식·실제 헤드리스 호출 성공까지 확인 완료.
  - ⚠️ **미결**: 27일 아침 브리핑은 실패 후 재실행하지 않았다(그날치 리포트 미게재).
    필요하면 `python pipeline.py daily` 를 수동 실행. seen.json 이 중복을 막으므로
    이후 정상 실행에 지장은 없음.
- **2026-07-24 — 주말·공휴일 제외** (`341e2af`). cron 은 `daily --skip-holiday` 로
  부르고, `common.holiday_reason()`(`holidays.SouthKorea`)이 휴일이면 조용히 종료.
- **2026-07-24 — 자동실행 launchd → cron 전환** (`91165b7`).

## 무엇이 동작하는가 (실행으로 확인)

- `naver` → 인기 검색 종목 20개 수집
- `dart` → 종목코드로 공시 매칭, 절차성 공시 제외
- `daily` → 전 구간 실행, HTML 리포트 생성·서버 저장·텔레그램 발송
- HTML 리포트: TOP20 칩(공시 있는 종목 표시, 클릭 시 해당 공시로 이동), 공시별 방향
  배지(긍정/부정/중립)·3줄·공시일, 종목명 클릭 시 맨 위로 복귀
- 텔레그램 알림(성공/스킵/에러) — 이모지 없이 방향 집계·종목코드 포함
- **cron 매일 08:00 등록 완료**: `/Users/sh/blog_claude.sh` + crontab
  `0 8 * * * /Users/sh/blog_claude.sh`. 최소 환경(PATH=/usr/bin:/bin)에서 동작 확인.
  스크립트는 `daily --skip-holiday` 로 부른다 → 주말·공휴일(`holidays` 라이브러리)엔
  자동 실행이 조용히 걸러진다(수동 실행엔 영향 없음).

## 무엇이 아직인가

- **공시 시각**: DART 가 날짜만 제공 → 리포트에 날짜만. 분 단위가 필요하면 KIND 연동.
- 외장 SSD(`/Volumes/extSSD4tb`) 미마운트 시 저장 실패 → 텔레그램 에러 알림으로 감지.

## 주의사항

- **claude 인증**: cron 은 키체인 로그인을 못 빌리고 OAuth 토큰이 며칠 만에 만료된다.
  `claude setup-token` 으로 발급한 장기 토큰을 `config/claude.json` 의 `oauth_token`
  에 넣어둔다. 토큰이 만료되면(1년 뒤 등) 재발급 후 이 값만 갈아끼우면 된다.
- 응답은 항상 한글. 요금제는 **Pro**(Max 아님) — claude 호출 수(공시 건수만큼)에 유의.
- 비밀값은 `config/*.json` 에만. 에러 메시지에 토큰 싣지 않기.
- 요약 말끝은 음슴체(했음/뜻임/어려움). `brief._tidy` 가 마침표·어미중복 정리.
- 실패 시 리포트를 올리지 않는다 — 불완전한 글보다 하루 거르는 게 낫다.
