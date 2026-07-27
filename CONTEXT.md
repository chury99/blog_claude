# 네이버 인기종목 공시 브리핑 — 프로젝트 컨텍스트

> Claude Code 가 이 프로젝트를 이어받아 작업하기 위한 문서.
> 결정사항·제약·구조를 담는다. (2026-07-24 컨셉 확정)

---

## 1. 한 줄 요약

매일 아침 08시, **네이버 금융 인기 검색 종목 TOP 20** 중 공시가 있는 종목을 찾아
그 공시를 **3줄(핵심 / 세부·해석 / 예상 주가 방향)**로 정리한 HTML 리포트를 자체
웹서버에 올리고, 텔레그램으로 링크를 보낸다. 짧고 쉽게가 차별점.

---

## 2. 개발자 배경

- Python 개발자이자 알고리즘 트레이더. 서버는 **Mac Mini**(hostname MacMini), 원격은 MacBook Air.
- **Claude Pro** 구독 (Max 아님) → `claude -p` 헤드리스 CLI 사용. daily 1회에 호출이
  공시 건수만큼(보통 10~20회) 나가므로 사용량 한도를 지켜봐야 함. [[claude-plan-pro]]
- 한국어로 소통. 응답은 항상 한글.

---

## 3. 핵심 결정사항

### 3-1. 컨셉 확정 (2026-07-24)
- 구글 트렌드는 **폐기**했다(연예·스포츠 노이즈가 많고 종목 연결이 불명확).
- **네이버 인기 검색 종목**만 신호로 쓴다 — 투자자가 실제로 검색하는 종목이라
  공시와 직접 연결된다. 종목코드로 매칭하므로 회사명 모호성이 없다.
- TOP 20 중 최근 공시가 있는 종목만 다룬다. 방향(긍정/부정/중립)은 공시별로 판정.

### 3-2. 데이터 소스
- **인기종목**: 네이버 금융 `finance.naver.com/sise/lastsearch2.naver` (euc-kr HTML 파싱).
  - 네이버 실시간 검색어(범용)는 2021년 폐지 → 금융 인기검색종목이 대안.
- **공시**: DART OpenAPI (opendart.fss.or.kr, 무료. 인증키는 `config/dart.json`).
  - 목록 `list.json` 은 **날짜(rcept_dt)만** 주고 시각은 없다(접수번호 뒷자리는 순번).
  - 본문 `document.xml` → 텍스트 추출 → 3줄 요약 입력.
  - **절차성 공시 제외**: 임원 소유상황보고서 등(전체의 절반 이상)은 `dart._ROUTINE_TYPES`
    로 후보에서 뺀다. 안 그러면 대형주의 이런 공시가 후보를 채운다.

### 3-3. 글 생성은 `claude -p` (헤드리스)
- `~/.local/bin/claude` 절대경로 고정 (cron 은 PATH 가 최소한이라). `PATH=/usr/bin:/bin`
  환경에서도 정상 동작 확인됨.
- 공시별로 1회 호출, {"direction","lines"} JSON 반환. 요약 말끝은 음슴체(했음/뜻임).
- **인증은 장기 토큰**: 대화형 로그인(키체인 OAuth)은 며칠 만에 만료되고, cron 은
  GUI 세션이 아니라 토큰 자동 갱신을 못 해 `Not logged in` 으로 죽는다(2026-07 확인).
  `claude setup-token` 으로 1년짜리 토큰을 발급해 `config/claude.json` 의 `oauth_token`
  에 두면, `claude_cli.ask` 가 이를 `CLAUDE_CODE_OAUTH_TOKEN` 으로 서브프로세스에
  주입한다. 파일이 없으면 키체인 로그인으로 폴백(대화형 개발엔 영향 없음).

### 3-4. 출력·발행
- Ghost 등 블로그 플랫폼을 쓰지 않는다. **HTML 파일을 자체 웹서버 폴더에 직접 저장**한다.
  - 폴더: `config.yaml` 의 `report.web_dir` (외장 SSD `/Volumes/extSSD4tb/90_web/kakao/클로드수행결과`)
  - 주소: `report.url_base` (`goniee.iptime.org/kakao/클로드수행결과`) + 파일명
- 실패 시 리포트를 올리지 않고 텔레그램으로 에러 보고. 다룬 공시는 `data/seen.json`
  에 기록해 다음 날 중복 게재를 막는다.

### 3-5. 스케줄링 — cron 매일 08:00
- 다른 프로젝트(`/Users/sh/*.sh` + crontab)와 동일한 방식으로 통일했다.
  `cron/blog_claude.sh` 를 `/Users/sh/blog_claude.sh` 로 배포하고 crontab 에
  `0 8 * * * /Users/sh/blog_claude.sh` 를 추가한다. 로그는 iCloud
  `python_log/blog_claude_YYYYMMDD.log`.
- cron 은 잠든 Mac 을 못 깨운다. 확실히 하려면 `pmset repeat wakeorpoweron MTWRFSU 07:55:00`.
- **휴일 제외**: cron 스크립트는 `daily --skip-holiday` 로 부른다. 주말·한국 공휴일
  (`holidays.SouthKorea`, 대체공휴일 포함)이면 네이버·DART·claude 호출 없이 조용히
  종료한다. 판정은 `common.holiday_reason()`. 증시 휴장일엔 새 공시가 없기 때문.

### 3-6. 소통은 텔레그램
- 자격증명은 `config/telegram.json` (git 제외). 결과·에러·스킵 모두 알림.

---

## 4. 파이프라인 구조

```
매일 08:00 (cron)
[1.네이버 TOP20] → [2.종목코드로 공시 매칭] → [3.공시별 3줄 요약+방향]
   naver.py         dart.disclosures_for_codes    brief.summarize_stocks
→ [4.HTML 렌더+서버 저장] → [5.텔레그램 링크]
   report.save            notify.send
```

- 공시 있는 종목이 0이면(휴일 등) 리포트를 건너뛰고 텔레그램으로만 알린다.

---

## 5. CLI

```
python pipeline.py daily            # 전체 실행 (cron 진입점)
python pipeline.py daily --dry-run  # 저장만, 텔레그램·기록 없이
python pipeline.py naver            # 인기 검색 종목 (디버그)
python pipeline.py dart             # 인기종목 공시 매칭 (디버그)
python pipeline.py telegram setup|test
```

---

## 6. 비밀값

- `config/dart.json` (git 제외): DART 인증키 (`api_key`)
- `config/telegram.json` (git 제외): 텔레그램 토큰/채팅ID
- `config/claude.json` (git 제외): claude 장기 토큰 (`oauth_token`, `setup-token` 발급)
- `config.yaml` 에는 비밀값을 두지 않는다. 에러 메시지에 토큰을 싣지 않는다.

---

## 7. 미결/한계

- **공시 시각**: DART 가 날짜만 제공 → 리포트에 날짜만 표시. 분 단위 시각이 필요하면
  한국거래소 KIND(kind.krx.co.kr) 를 보조 소스로 붙이는 방안 검토 가능.
- 리포트 저장은 외장 SSD 마운트 전제. 미마운트 시 report.save 가 에러 → 텔레그램 알림.
- 수익화(광고/제휴)는 코드 범위 밖.
