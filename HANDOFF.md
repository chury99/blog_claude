# 인수인계 — 네이버 인기종목 공시 브리핑

> 새 대화(Claude Code)가 이 프로젝트를 이어받기 위한 문서.
> 설계 배경은 [CONTEXT.md](CONTEXT.md), 사용법은 [README.md](README.md).
> 이 문서는 **무엇이 만들어졌고 무엇이 남았는지**만 담는다.

## 현재 상태 (2026-07-24)

**컨셉이 확정·구현 완료됐다.** 네이버 금융 인기 검색 종목 TOP 20 → 공시 있는 종목
→ 공시별 3줄 요약(핵심/세부·해석/예상 주가 방향, 방향 판정 포함) → HTML 리포트를
자체 웹서버 폴더에 저장 → 텔레그램 링크 발송.

- 저장소: https://github.com/chury99/blog_claude (Public, `main`)
- 서버: Mac Mini. `claude` CLI 설치·로그인 완료(`~/.local/bin/claude`).
- 의존성: PyYAML, python-dotenv, requests (Ghost·markdown 경로는 제거됨).

## 무엇이 동작하는가 (실행으로 확인)

- `naver` → 인기 검색 종목 20개 수집
- `dart` → 종목코드로 공시 매칭, 절차성 공시 제외
- `daily` → 전 구간 실행, HTML 리포트 생성·서버 저장·텔레그램 발송
- HTML 리포트: TOP20 칩(공시 있는 종목 📄, 클릭 시 해당 공시로 이동), 공시별 방향
  배지(🔺긍정/🔻부정/⚪중립)·3줄·공시일, 종목명 클릭 시 맨 위로 복귀
- 텔레그램 알림(성공/스킵/에러)

## 무엇이 아직인가

- **launchd 등록**: `launchd/com.chury99.blog-daily.plist` 를 08:00 스케줄로 등록해야 함
  (README 의 launchctl bootstrap). 등록됐다면 이 항목 삭제.
- **공시 시각**: DART 가 날짜만 제공 → 리포트에 날짜만. 분 단위가 필요하면 KIND 연동.
- 외장 SSD(`/Volumes/extSSD4tb`) 미마운트 시 저장 실패 → 텔레그램 에러 알림으로 감지.

## 주의사항

- 응답은 항상 한글. 요금제는 **Pro**(Max 아님) — claude 호출 수(공시 건수만큼)에 유의.
- 비밀값은 `config/*.json` 에만. 에러 메시지에 토큰 싣지 않기.
- 요약 말끝은 음슴체(했음/뜻임/어려움). `brief._tidy` 가 마침표·어미중복 정리.
- 실패 시 리포트를 올리지 않는다 — 불완전한 글보다 하루 거르는 게 낫다.
