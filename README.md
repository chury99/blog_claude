# content-pipeline

키워드 리서치 → 초안 생성 → **사람 검수** → 발행으로 이어지는 반자동 블로그 콘텐츠 파이프라인.

설계 배경과 결정사항은 [CONTEXT.md](CONTEXT.md) 참고.

```
[1. 주제수집] → [2. 초안생성] → [3. 사람검수 ⏸️] → [4. 발행]
   pytrends/       claude -p        (수동 확인)      Ghost API
   Reddit(praw)                                    (publish 명령 시에만)
   + Claude 필터
```

## 완전 무인 발행을 하지 않는 이유

가치 없이 대량생산된 AI 콘텐츠는 검색 노출에서 불이익을 받는다. 자동화는 **초안 생성까지만** 하고,
글쓴이의 실전 데이터·경험을 얹는 편집 레이어를 반드시 거친다. 이 제약은 코드에 3중으로 박혀 있다.

1. `publish` 서브커맨드를 직접 부를 때만 발행 단계가 돈다.
2. 초안 프론트매터의 `reviewed: true` 가 아니면 거부한다.
3. 그래도 기본은 플랫폼 draft. 공개하려면 `--live` + 확인 프롬프트.

## 설치

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # Ghost/Reddit 키 입력
```

`claude` CLI(헤드리스 `-p` 모드)가 필요하다. PATH 에 없으면 `config.yaml` 의
`generate.claude_bin` 에 절대경로를 넣는다.

```bash
npm install -g @anthropic-ai/claude-code
```

## 사용

```bash
# 2단계만 먼저 돌려 흐름 확인 (수집 없이 주제 직접 지정)
python pipeline.py generate --topic "파이썬 백테스팅에서 흔한 룩어헤드 편향 3가지"

# 1단계: 주제 수집 + 필터
python pipeline.py collect

# 수집된 주제 전부 초안 생성
python pipeline.py generate

# 3단계: 검수 상태 확인 → drafts/*.md 를 열어 [경험 삽입] 마커를 채우고
#         프론트매터의 reviewed 를 true 로 바꾼다
python pipeline.py review

# 4단계: Ghost 에 draft 로 업로드
python pipeline.py publish 20260717-my-slug

# 실제 공개 (확인 프롬프트가 뜬다)
python pipeline.py publish 20260717-my-slug --live
```

발행 어댑터를 `dryrun` 으로 바꾸면(`config.yaml` 의 `publish.adapter`) 실제 업로드 없이
무엇이 올라갈지 확인할 수 있다.

## 구조

```
pipeline.py          CLI 진입점 / 오케스트레이터
config.yaml          니치, 시드 키워드, 발행 대상 등 설정
steps/
  claude_cli.py      claude -p subprocess 래퍼 (클로드 호출은 전부 여기 경유)
  collect.py         1단계: Google Trends/Reddit 수집 + Claude 필터
  generate.py        2단계: 초안 생성 → drafts/
  publish.py         4단계: Publisher 추상 클래스 + Ghost/DryRun 어댑터
  common.py          설정 로딩, slug, JSON 추출 등 공용 유틸
prompts/
  filter.txt         주제 필터링 프롬프트
  write.txt          글쓰기 프롬프트
drafts/              생성된 초안 (git 제외)
```

다른 플랫폼을 붙이려면 `steps/publish.py` 의 `Publisher` 를 상속해
`make_publisher()` 에 등록하면 된다.

## 스케줄링

수집·생성만 자동화한다. 발행은 스케줄에 넣지 않는다.

```bash
# crontab -e — 매일 오전 8시 수집 + 초안 생성
0 8 * * * cd /path/to/blog_claude && .venv/bin/python pipeline.py collect && .venv/bin/python pipeline.py generate
```
