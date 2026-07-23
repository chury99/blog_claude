# 인수인계 — 공시 브리핑 자동 블로그

> 새 대화(Claude Code)가 이 프로젝트를 이어받기 위한 문서.
> 설계 배경/결정사항은 [CONTEXT.md](CONTEXT.md), 사용법은 [README.md](README.md) 참고.
> 이 문서는 **지금까지 무엇이 만들어졌고 무엇이 남았는지**만 담는다.

## 현재 상태 (2026-07-23 기준)

**프로젝트가 전면 재설계됐다.** 구버전(범용 초안 생성 + 사람 검수 + 수동 발행)은 폐기.
현재 정의: 매일 08시 자동 실행 → 트렌드에서 국내주식 관련 항목 발굴 → DART 공시를
긍정 5 · 부정 5 로 선정 → 각 3줄 요약 → 블로그 **자동 발행** → 텔레그램 통보.

- 저장소: https://github.com/chury99/blog_claude (Public, `main`)
- 로컬: `/Users/chury99/PycharmProjects/blog_claude` (MacBook — 운영 서버는 Mac Mini 예정)
- 가상환경: `.venv/`. 의존성: PyYAML, python-frontmatter, python-dotenv, requests, PyJWT, markdown

## 무엇이 동작하는가 (실행으로 확인함)

- `claude` CLI 설치·로그인 완료 (`~/.local/bin/claude`, 헤드리스 `-p` 검증됨)
- 텔레그램 알림 연동 완료 (`config/telegram.json`, 실발송 확인)
- 1단계 트렌드 수집: RSS(KR) 실호출 + Claude 주식 관련 추출 검증됨
- 3-5단계 선정·요약·조립: 샘플 공시 데이터로 전 구간 검증됨
- dryrun 발행 어댑터 동작 확인

- 2단계 DART 실호출: 인증키(`config/dart.json`)로 공시 2124건 수집 + `daily --dry-run`
  전 구간 검증됨 (긍5/부5 선정, 🔥 3건 매칭, 3줄 요약까지).

## 무엇이 검증 안 됐는가

- **DART 본문(document.xml) 파싱** — 실데이터로 못 돌려봤다. 리허설은 제목 기반 요약
  폴백으로 진행됐다 (본문 확보 실패 시 정상 폴백). 실본문 요약 품질은 미검증.
- **Ghost 실발행** — 사이트 미개설 (`publish.ghost.api_url` = CHANGE-ME).
- **launchd 08시 실행** — plist 만 준비됨 (`launchd/`), 미등록.

## 남은 일 (순서대로)

1. 사용자: Ghost 사이트 개설 → `config.yaml` 의 `api_url` + `.env` 의 `GHOST_ADMIN_API_KEY`
2. 실발행 1회 검증 (`daily --dry-run` → adapter 를 ghost 로) 후 launchd 등록 (README 의 명령)
3. 수익화(광고/제휴) 논의 — 코드 범위 밖

## 주의사항

- 응답은 항상 한글로.
- 비밀값은 `.env` / `config/telegram.json` 에만. 에러 메시지에 토큰 싣지 않기.
- 알림 실패는 파이프라인을 죽이지 않는다 (`notify.send` 는 False 만 반환).
- 실패 시 발행하지 않는다 — 불완전한 글이 올라가느니 하루 거르는 게 낫다.
