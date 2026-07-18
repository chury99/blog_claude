# 인수인계 — 콘텐츠 자동화 파이프라인

> 새 대화(Claude Code)가 이 프로젝트를 이어받기 위한 문서.
> 설계 배경/결정사항은 [CONTEXT.md](CONTEXT.md), 사용법은 [README.md](README.md) 참고.
> 이 문서는 **지금까지 무엇이 만들어졌고 무엇이 남았는지**만 담는다.

## 현재 상태 (2026-07-18 기준)

MVP 스캐폴딩 완성 + 실행 검증 완료. GitHub 에 Public 으로 푸시됨.

- 저장소: https://github.com/chury99/blog_claude (Public, `main`)
- 로컬: `/Users/chury99/PycharmProjects/blog_claude`
- 커밋:
  - `178afab` 초기 스캐폴딩
  - `d8ebee7` 점검에서 발견된 발행/생성 로직 버그 수정
- 가상환경: `.venv/` (git 제외). 핵심 의존성 설치됨:
  PyYAML, python-frontmatter, python-dotenv, requests, PyJWT, markdown.
  (pytrends, praw 는 아직 미설치 — 1단계 수집을 실제로 돌릴 때 필요)

## 무엇이 동작하는가 (실행으로 확인함)

`claude` CLI 자리에 대역 스텁을 끼워 전 구간을 한 바퀴 돌려 검증했다:

1. `generate --topic "제목"` → `drafts/YYYYMMDD-slug.md` 생성, `reviewed: false` 로 잠김
2. `review` → 검수대기/검수완료/발행됨 상태 표시
3. 검수 전 `publish` → 안전장치가 거부
4. `reviewed: true` 로 바꾼 뒤 `publish` → 기본 draft 로 업로드(dryrun 어댑터로 확인)
5. Ghost JWT 인증 토큰 생성까지 확인(네트워크 실호출은 안 함)

무인 발행 금지 3중 안전장치(publish 명시 호출 / reviewed:true / 기본 draft)
가 순서대로 작동함을 확인.

## 아직 실제로 못 돌려본 것 (이 머신의 한계)

- **`claude` CLI 가 이 개발 머신(MacBook)에 미설치.** 그래서 진짜 초안 생성과
  주제 필터링은 실행으로 확인 못 함. 실제 서버는 Mac Mini 이므로 거기서 확인 필요.
  → `config.yaml` 의 `generate.claude_bin` 에 절대경로를 넣거나 PATH 에 claude 설치.
- **Ghost 실업로드.** API 키/실제 사이트 URL 이 없어 draft 실업로드는 미확인.
  JWT 생성까지만 검증됨.
- **1단계 수집(pytrends/praw).** 라이브러리 미설치 + 자격증명 없음 → 실행 미확인.
  코드상 소스 실패 시 건너뛰도록 방어는 되어 있음.

## 다음에 할 일 (권장 순서)

1. **Mac Mini 에서 실제 `claude -p` 로 초안 1개 뽑아 프롬프트 품질 확인.**
   `prompts/write.txt` 의 `[경험 삽입]` 마커 개수·위치, 분량, 톤을 실제 출력으로 보고 조정.
   가장 먼저 할 것. 수집 없이 `generate --topic` 하나로 검증 가능.
2. Ghost 사이트 확정 후 `config.yaml` 의 `publish.ghost.api_url` 설정,
   `.env` 에 `GHOST_ADMIN_API_KEY` 입력 → dryrun 아닌 실제 draft 업로드 1회 확인.
3. 1단계 수집을 붙일 때 `pip install pytrends praw`, `config.yaml` 에서 소스 enable.
   pytrends 는 구글 응답 변경에 자주 깨지므로 실제 후보가 나오는지부터 확인.
4. 스케줄링(cron/launchd)은 collect+generate 까지만. 발행은 절대 자동화하지 않는다.

## 열린 질문 (개발자 확인 필요 — CONTEXT.md 8장)

- Ghost(Pro) 호스팅 vs 자가호스팅? (API 사용법은 동일)
- 생성 언어: 한글 vs 영어(글로벌 타깃 시)? 현재 `config.yaml` 은 `ko`.
- 초기 니치: 현재 "알고리즘 트레이딩, 퀀트 투자, 파이썬 자동매매" 로 잡아둠.
- 수집 소스: Google Trends 만으로 시작 vs Reddit 도 포함? 현재 Reddit 은 비활성.

## 구조 빠른 참고

```
pipeline.py          CLI 진입점 (collect/generate/review/publish 서브커맨드)
config.yaml          니치·시드키워드·발행대상 등 설정 (비밀값은 .env)
steps/
  claude_cli.py      claude -p subprocess 래퍼 (클로드 호출은 전부 여기 경유)
  generate.py        2단계: 초안 생성 (핵심). 기존 초안 있으면 덮어쓰지 않음
  collect.py         1단계: Google Trends/Reddit 수집 + Claude 필터
  publish.py         4단계: Publisher 추상 + Ghost/DryRun 어댑터
  common.py          설정 로딩, slug(한글 보존), JSON 추출 등 공용 유틸
prompts/filter.txt   주제 필터링 프롬프트
prompts/write.txt    글쓰기 프롬프트 ([경험 삽입] 마커 지시 포함)
drafts/              생성 초안 (git 제외, 로컬 전용)
```

## 알아둘 만한 설계 포인트

- `d8ebee7` 에서 잡은 버그들: dryrun 이 published_url 을 기록해 실발행이 막히던 문제,
  generate 재실행이 검수 중 초안을 덮어쓰던 문제, markdown 미설치 시 글 깨짐.
  같은 함정을 다시 만들지 말 것.
- slug 는 한글을 그대로 살린다(`steps/common.py:slugify`). ASCII 로 떨구면 파일명이
  전부 겹쳐서 초안이 서로 덮어써진다.
- 발행 어댑터는 `config.yaml` 의 `publish.adapter` 로 `ghost`/`dryrun` 전환.
  새 플랫폼은 `steps/publish.py` 의 `Publisher` 상속 후 `make_publisher()` 에 등록.
