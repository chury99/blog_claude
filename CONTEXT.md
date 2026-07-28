# 네이버 인기종목 공시 브리핑 — 프로젝트 컨텍스트

> Claude Code 가 이 프로젝트를 이어받아 작업하기 위한 문서.
> 결정사항·제약·구조를 담는다. (2026-07-24 컨셉 확정)

---

## 1. 한 줄 요약

매일 아침 08시, **네이버 금융 인기 검색 종목 TOP 20** 중 공시가 있는 종목을 찾아
그 공시를 **3줄(핵심 / 세부·해석 / 예상 주가 방향)**로 정리한 HTML 리포트를 자체
웹서버에 올리고, 텔레그램으로 링크를 보낸다. 리포트 머리에 **간밤 미국 증시**를
얹어 그날의 배경을 준다. 짧고 쉽게가 차별점.

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
- **미국 지수**: 네이버 금융 세계증시 API `api.stock.naver.com/index/{code}/basic`
  (인증키 없음). 다우존스 `.DJI`, 나스닥 `.IXIC`, S&P 500 `.INX`. 한글 지수명과
  전일 대비·등락률을 그대로 준다.
- **미국 증시 뉴스**: 네이버 금융 > 뉴스 > **해외증시** 목록
  (`finance.naver.com/news/news_list.naver`, `section_id3=403`, euc-kr HTML 파싱).
  제목·발췌·언론사·시각을 주고, 기사는 `n.news.naver.com/mnews/article/{oid}/{aid}`
  로 **링크가 열린다**.
  - 세계증시 API(`api.stock.naver.com/news/worldStock/{code}`)의 로이터 기사도
    내용은 좋지만 **공개 퍼머링크가 없어**(fnGuide 제공분, `n.news.naver.com` 이
    500) 쓰지 않는다. 링크가 열리는 쪽이 독자가 확인할 수 있어 낫다.

### 3-2-1. 간밤 미국 증시 (2026-07-28 추가)
- 한국 장 시작 전 리포트라 미국 마감이 그날의 배경이다. 리포트 맨 위에 지수 카드와
  흐름 2~3문장을 얹는다. **길게 쓰지 않는다 — 흐름만 알면 된다.**
- **요약은 뉴스 기반이다.** claude 는 간밤 뉴스를 모르므로, 지수 숫자만 주면 "왜
  움직였나"를 못 쓴다. 그래서 지수 등락 + 실제 기사(제목·발췌)를 함께 넘기고,
  **원인은 넘긴 기사에 있는 것만** 쓰도록 프롬프트에서 못박았다.
- 해외증시 목록엔 중국·일본 기사도 섞이므로 **미국 시장 전체 기사를 앞세운다**
  (`market._US_MARKET` 키워드 점수). 그게 밀리면 배경을 쓸 근거가 사라진다.
  간밤 마감 기사는 05~07시에 올라와 목록 뒤쪽으로 밀리니 여러 쪽을 본다(`news.pages`).
- 근거로 쓴 기사 제목·언론사를 리포트에 함께 싣고 **원문으로 링크한다**. 독자가
  확인할 수 있어야 하고, 요약이 어디서 왔는지 드러나야 한다.
- **상위 기사는 본문까지 받아 넘긴다**(`news.body_count`). 목록 발췌는 100자
  남짓이라 "혼조 마감했음" 수준밖에 못 쓴다. 본문이 있어야 필라델피아반도체지수·
  개별 종목 등락률·실적 발표 일정 같은 구체적 사실이 요약에 들어간다.
- **지수 등락률은 요약에 다시 쓰지 않는다.** 바로 위 카드에 숫자가 이미 있어
  되풀이가 된다. 요약은 "왜 그렇게 됐는지"와 개별 업종·종목 수치를 담당한다.
- **기사가 없으면 요약을 건너뛴다** — 지수 숫자만 싣는다. 원인을 지어내느니 낫다.
- **실패해도 죽지 않는다**: 지수·뉴스·요약 중 무엇이 실패하든 예외를 올리지 않고
  그 부분만 빠진다. 곁들이는 정보 때문에 공시 브리핑 전체를 거를 이유가 없다.
- 공시가 있는 날에만 부른다(리포트를 건너뛰는 날 claude 호출을 아끼려고).

### 3-3. 글 생성은 `claude -p` (헤드리스)
- `~/.local/bin/claude` 절대경로 고정 (cron 은 PATH 가 최소한이라). `PATH=/usr/bin:/bin`
  환경에서도 정상 동작 확인됨.
- 공시별로 1회 호출, {"direction","lines"} JSON 반환. 요약 말끝은 음슴체(했음/뜻임).
- **프로젝트 밖 빈 폴더에서 실행한다**(`claude_cli._neutral_cwd`). 프로젝트 폴더에서
  부르면 claude 가 저장소(CLAUDE.md·소스·git 상태)를 컨텍스트로 끌어와, 요약 대신
  "저장소가 이런 상태다" 같은 엉뚱한 응답을 낼 때가 있다(2026-07 실측). 요약에
  저장소는 필요 없다.
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
→ [4.간밤 미국 증시(지수+뉴스)] → [5.HTML 렌더+서버 저장] → [6.텔레그램 링크]
   market.brief_us               report.save                 notify.send
```

- 공시 있는 종목이 0이면(휴일 등) 리포트를 건너뛰고 텔레그램으로만 알린다.

---

## 5. CLI

```
python pipeline.py daily            # 전체 실행 (cron 진입점)
python pipeline.py daily --dry-run  # 저장만, 텔레그램·기록 없이
python pipeline.py naver            # 인기 검색 종목 (디버그)
python pipeline.py dart             # 인기종목 공시 매칭 (디버그)
python pipeline.py market           # 간밤 미국 증시 시황 (디버그)
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
