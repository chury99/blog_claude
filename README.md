# 오늘의 특징주 브리핑

매일 아침 07시, 제목에 **'특징주'가 들어간 기사**를 모아 종목별로 묶고,
**이슈를 3줄(무슨 일 / 세부·해석 / 예상 주가 방향) + 긍정·부정 판정**으로
정리한 HTML 리포트를 자체 웹서버에 올리고 텔레그램으로 링크를 보낸다.
종목은 등락률과 함께 표시되고, 누르면 해당 이슈 요약으로 이동한다.
리포트 머리에는 **간밤 미국 증시**(다우존스·나스닥 지수 + 뉴욕증시 기사에 근거한
흐름 2~3문장)를 얹는다. 요약의 근거 기사는 모두 원문으로 링크된다.

설계 배경은 [CONTEXT.md](CONTEXT.md) 참고.

```
매일 07:00 (cron)
[1.'특징주' 기사] → [2.종목별로 묶어 이슈 3줄+방향] → [3.간밤 미국 증시] → [4.HTML 서버 저장] → [5.텔레그램]
 구글뉴스 RSS       종목 확인 + 시세 → claude -p       지수+뉴스→claude    report.web_dir     링크 발송
```

기준이 여러 번 바뀌었다: **공시 → 종목 뉴스 → 테마 → 특징주 기사(현재)**. 앞 단계
코드는 지우지 않고 남겨뒀고 daily 에서만 뺐다 (`pipeline.py theme|feature|dart`).

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

**cron 무인 실행엔 장기 토큰이 필요하다.** 대화형 로그인(키체인)은 며칠 만에
만료되고, cron 은 GUI 세션이 아니라 토큰 자동 갱신을 못 해 `Not logged in` 으로
죽는다. `claude setup-token` 으로 1년짜리 장기 토큰을 발급해 `config/claude.json`
(git 제외)에 넣어두면 파이프라인이 이걸 `CLAUDE_CODE_OAUTH_TOKEN` 으로 주입한다.

```bash
claude setup-token                                # 브라우저 인증 → sk-ant-oat... 출력
cp config/claude.json.example config/claude.json  # oauth_token 에 붙여넣고 chmod 600
```

파일이 없으면 기존처럼 로그인된 CLI 세션(키체인)을 빌려 쓴다 — 대화형 개발엔 영향 없음.

## 사용

```bash
python pipeline.py daily                 # 전체 실행 (cron 진입점)
python pipeline.py daily --skip-holiday   # 주말·공휴일이면 실행 안 함 (cron이 쓰는 형태)
python pipeline.py daily --dry-run        # 저장만, 텔레그램·기록 없이
python pipeline.py highlight              # 오늘의 특징주 (디버그)
python pipeline.py market                 # 간밤 미국 증시 시황 (디버그)
python pipeline.py theme                  # 테마별 이슈 (디버그, daily 미사용)
python pipeline.py naver|feature|dart     # 이전 방식 (디버그, daily 미사용)
python pipeline.py telegram test          # 알림 점검
```

`--skip-holiday` 는 주말·한국 공휴일(설날·추석·대체공휴일 등, `holidays` 라이브러리)
이면 아무 작업 없이 조용히 종료한다. cron 스크립트가 이 플래그로 부르므로, 증시 휴장일엔
자동 실행이 걸러진다. 수동 `daily` 실행에는 영향이 없다.

## 매일 07시 자동 실행 (cron)

다른 프로젝트(`/Users/sh/*.sh`)와 동일하게, 실행 스크립트를 `/Users/sh` 에 두고
crontab 에서 부른다. 스크립트 원본은 [cron/blog_claude.sh](cron/blog_claude.sh).

```bash
cp cron/blog_claude.sh /Users/sh/blog_claude.sh
chmod +x /Users/sh/blog_claude.sh
```

crontab 에 아래 한 줄 추가 (`crontab -e`, 기존 항목은 유지):

```
0 7 * * * /Users/sh/blog_claude.sh
```

로그는 iCloud `python_log/blog_claude_YYYYMMDD.log` 에 날짜별로 쌓인다.

cron 은 잠든 Mac 을 깨우지 못한다. 07시에 확실히 실행하려면 미리 깨워둔다:

```bash
sudo pmset repeat wakeorpoweron MTWRFSU 06:55:00
```

## 출력

- HTML 리포트는 `config.yaml` 의 `report.web_dir` 폴더에 저장되고, `report.url_base`
  주소로 열린다. 이 폴더를 웹서버가 서빙한다.
- 파일명: `YYYYMMDD_오늘의특징주_브리핑.html`
- 파이프라인이 실패하면 리포트를 올리지 않고 텔레그램으로 에러를 보낸다.
- 리포트 머리의 미국 증시 시황은 곁들이는 정보라, 지수·뉴스 수집이나 요약이
  실패하면 그 부분만 빠지고 특징주 브리핑은 그대로 나간다. 대상 지수는 `config.yaml`
  의 `market.us_indices` 에서 바꾼다(S&P 500 은 주석만 풀면 된다).
- 종목 이슈도, 미국 시황도 **함께 표시되는 기사에서만** 근거를 얻는다.
- 특징주 기사는 네이버 금융 API·큐레이션 피드에 거의 올라오지 않아 **구글 뉴스
  RSS** 로 찾는다. 종목명은 기사 제목에서 뽑아 네이버 자동완성으로 실제 종목인지
  확인하므로 오탐이 걸러지고, `[유럽 특징주]` 같은 해외물은 `highlight.exclude_keywords`
  로 뺀다.
- 기사 수집 구간은 **직전 거래일 장 종료(`market_close`) ~ 실행 시각**이다. 그런데
  특징주 기사는 장중에만 나와 07시 실행에서는 거의 안 잡힌다. 그래서 모자란 만큼
  **등락률 상위 종목의 기사로 채운다**(`highlight.movers`). 이때도 '[마감시황]' 같은
  시장 전체 기사는 빼고 **제목에 종목명이 든 기사만** 쓴다.
- 시황 요약의 원인 서술은 **함께 표시되는 기사에서만** 나온다. 근거 기사는 제목을
  누르면 네이버 뉴스 원문으로 열린다. 기사가 없으면 요약을 건너뛰고 지수 숫자만
  싣는다. 기사 수·조회 쪽수는 `market.news` 에서 조절한다.
- 요약은 지수 등락률을 되풀이하지 않는다(바로 위 카드에 있으므로). 대신 업종·개별
  종목 움직임과 배경을 담는다. 이를 위해 상위 `news.body_count` 건은 기사 본문까지
  받아 쓴다 — 목록 발췌만으로는 구체적인 내용이 나오지 않는다.

## 구조

```
pipeline.py          CLI 진입점 / 오케스트레이터
config.yaml          특징주 종목 수, 기사 범위, 출력 폴더/주소 등
steps/
  claude_cli.py      claude -p subprocess 래퍼
  highlight.py       '특징주' 기사 수집 + 종목 확인·시세 + 이슈 요약(+방향 판정)
  stocknews.py       종목 뉴스 수집 (본문 근거 보강용)
  market.py          간밤 미국 증시 지수 + 흐름 요약
  report.py          HTML 리포트 렌더 + 서버 폴더 저장
  notify.py          텔레그램 알림
  common.py          설정 로딩, JSON 추출 등 공용 유틸
  theme.py           테마별 이슈 (현재 daily 미사용)
  naver.py           인기 검색 종목 (현재 daily 미사용)
  feature.py         종목별 3줄 요약 (현재 daily 미사용)
  dart.py            DART 공시 (현재 daily 미사용)
  brief.py           공시별 3줄 요약 (현재 daily 미사용)
prompts/
  highlight.txt      특징주 이슈 3줄 + 방향 판정 프롬프트
  us_market.txt      미국 증시 흐름 요약 프롬프트
  theme.txt          테마 요약 프롬프트 (현재 미사용)
  feature.txt        종목별 요약 프롬프트 (현재 미사용)
  summarize.txt      공시 요약 프롬프트 (현재 미사용)
cron/                매일 07시 실행용 셸 스크립트 (→ /Users/sh 로 배포)
data/                기수록 공시 기록 (git 제외)
logs/                실행 로그 (git 제외; cron 로그는 iCloud python_log 에도 쌓임)
```

## 비밀값

| 값 | 위치 |
|---|---|
| DART 인증키 | `config/dart.json` → `api_key` (현재 daily 미사용) |
| 텔레그램 토큰/채팅ID | `config/telegram.json` (`telegram setup` 이 생성) |
| claude 장기 토큰 | `config/claude.json` → `oauth_token` (`claude setup-token` 이 발급) |

전부 git 제외. `config.yaml` 에는 비밀값을 두지 않는다.
