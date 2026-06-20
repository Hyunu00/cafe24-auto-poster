# CLAUDE.md — cafe24-auto-poster

## 프로젝트 개요

카페24로 호스팅 중인 **WordPress 블로그**에 AI가 생성한 글을 자동으로 포스팅하는 자동화 프로그램.
키워드 기반으로 Claude API가 SEO 최적화 글을 생성하고, WordPress REST API로 자동 업로드해
구글 애드센스 수익을 극대화하는 것이 목적.

---

## 기술 스택

- **언어**: Python 3.11+
- **AI 글 생성**: Anthropic Claude API (`claude-sonnet-4-6`)
- **포스팅**: WordPress REST API v2
- **스케줄링**: `schedule` 라이브러리
- **환경변수**: `python-dotenv`
- **HTTP 클라이언트**: `httpx`

---

## 폴더 구조

```
cafe24-auto-poster/
├── CLAUDE.md               # 이 파일
├── main.py                 # 실행 진입점 (스케줄러 포함)
├── config.py               # 설정값 로드 (.env → Python 객체)
├── .env                    # 비밀키 (절대 git 커밋 금지)
├── .env.example            # 키 목록만 공개용으로 제공
├── .gitignore
│
├── ai_writer/
│   ├── __init__.py
│   └── generator.py        # Claude API로 블로그 글 생성
│
├── wordpress/
│   ├── __init__.py
│   └── poster.py           # WordPress REST API로 글 등록
│
├── keywords/
│   └── keywords.txt        # 타겟 키워드 목록 (한 줄에 하나)
│
└── logs/
    └── post_log.json       # 포스팅 이력 기록 (키워드, 제목, 날짜, 성공여부)
```

---

## 환경변수 (.env)

```env
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# WordPress (카페24 호스팅)
WP_URL=https://yourdomain.com          # 블로그 도메인
WP_USERNAME=admin                       # WordPress 관리자 아이디
WP_APP_PASSWORD=xxxx xxxx xxxx xxxx   # 애플리케이션 비밀번호 (wp-admin에서 발급)

# 포스팅 설정
POST_PER_DAY=3                          # 하루 포스팅 횟수
POST_STATUS=publish                     # publish(즉시공개) or draft(임시저장)
POST_CATEGORY_ID=1                      # 글 올릴 카테고리 ID
```

---

## 핵심 모듈 역할

### `ai_writer/generator.py`
- `keywords.txt`에서 키워드를 하나 읽어옴
- Claude API에 SEO 최적화 블로그 글 생성 요청
- 반환값: `{ "title": str, "content": str, "tags": list, "excerpt": str }`
- 글 길이는 최소 800자 이상, HTML 형식으로 생성
- 이미 사용한 키워드는 `logs/post_log.json`에서 중복 체크 후 스킵

### `wordpress/poster.py`
- `POST {WP_URL}/wp-json/wp/v2/posts` 엔드포인트 사용
- 인증: Basic Auth (`WP_USERNAME` + `WP_APP_PASSWORD`)
- 제목, 내용, 태그, 카테고리, 발췌문 포함해서 글 등록
- 성공/실패 결과를 `logs/post_log.json`에 기록

### `main.py`
- `schedule` 라이브러리로 하루 N번 자동 실행
- 실행 순서: 키워드 로드 → AI 글 생성 → WordPress 포스팅 → 로그 저장

---

## WordPress 애플리케이션 비밀번호 발급 순서

1. WordPress 관리자 페이지 접속 (`yourdomain.com/wp-admin`)
2. **사용자 → 프로필** 이동
3. 하단 **"애플리케이션 비밀번호"** 섹션 찾기
4. 이름 입력 (예: `auto-poster`) → **"새 애플리케이션 비밀번호 추가"** 클릭
5. 생성된 비밀번호(공백 포함) 복사 → `.env`의 `WP_APP_PASSWORD`에 저장
6. ⚠️ 이 비밀번호는 다시 볼 수 없으므로 반드시 바로 저장

---

## 개발 순서 (단계별)

1. `pip install anthropic httpx python-dotenv schedule` 설치
2. `.env` 작성 및 WordPress 애플리케이션 비밀번호 발급
3. `ai_writer/generator.py` 구현 및 단독 테스트 (글 생성만 확인)
4. `wordpress/poster.py` 구현 — `POST_STATUS=draft`로 테스트 글 1개 수동 포스팅
5. WordPress 관리자에서 임시저장 글 확인
6. `main.py` 스케줄러 연결
7. `POST_STATUS=publish`로 전환 후 실제 운영

---

## 코딩 규칙 (Claude에게)

- 모든 코드는 **Python 3.11+ 기준**으로 작성
- 타입 힌트 필수 (`def func(x: str) -> dict:`)
- API 호출은 전부 `httpx.AsyncClient` 사용 (비동기)
- 에러 발생 시 프로그램이 죽지 않고 로그만 남기고 다음으로 넘어갈 것
- `.env` 값은 반드시 `config.py`를 통해서만 접근
- 한 파일에 한 가지 역할만 (단일 책임 원칙)
- 함수 위에 한 줄 docstring 필수

---

## 금지사항

- `.env` 파일 절대 git에 커밋하지 말 것
- API 키 / 비밀번호를 코드에 하드코딩하지 말 것
- WordPress API 호출 간격은 최소 2초 이상 (서버 부하 방지)
- 같은 키워드로 중복 포스팅 금지 (로그로 체크)


CLAUDE.md

일반적인 LLM 코딩 실수를 줄이기 위한 행동 지침입니다. 필요에 따라 프로젝트별 지침과 병합하세요.

절충점: 이 지침은 속도보다는 신중함에 중점을 둡니다. 사소한 작업에는 판단력을 사용하세요.

1. 코딩 전 생각하기

가정하지 마세요. 혼란을 숨기지 마세요. 절충점을 드러내세요.

구현하기 전에:

가정을 명시적으로 진술하세요. 불확실하면 물어보세요.

여러 해석이 있다면, 조용히 선택하지 말고 제시하세요.

더 간단한 접근 방식이 있다면 말하세요. 타당할 때 반박하세요.

불분명한 점이 있다면 멈추세요. 무엇이 혼란스러운지 이름을 붙이세요. 물어보세요.

2. 단순함 우선

문제를 해결하는 최소한의 코드. 추측적인 것은 없습니다.

요청된 것 이상의 기능은 없습니다.

단일 사용 코드에 대한 추상화는 없습니다.

요청되지 않은 "유연성" 또는 "구성 가능성"은 없습니다.

불가능한 시나리오에 대한 오류 처리는 없습니다.

200줄을 작성했는데 50줄로 가능했다면, 다시 작성하세요.

스스로에게 물어보세요: "시니어 엔지니어라면 이것이 너무 복잡하다고 말할까요?" 그렇다면 단순화하세요.

3. 수술적 변경

필요한 것만 건드리세요. 자신의 실수만 정리하세요.

기존 코드를 편집할 때:

인접한 코드, 주석 또는 서식을 "개선"하지 마세요.

망가지지 않은 것을 리팩터링하지 마세요.

다르게 할지라도 기존 스타일을 맞추세요.

관련 없는 죽은 코드를 발견하면, 삭제하지 말고 언급하세요.

변경 사항으로 인해 고아가 발생할 때:

귀하의 변경으로 인해 사용되지 않게 된 가져오기/변수/함수를 제거하세요.

요청받지 않은 한 기존의 죽은 코드를 제거하지 마세요.

테스트: 변경된 모든 줄은 사용자의 요청으로 직접 추적되어야 합니다.

4. 목표 중심 실행

성공 기준을 정의하세요. 확인될 때까지 반복하세요.

작업을 검증 가능한 목표로 변환하세요:

"유효성 검사 추가" → "잘못된 입력에 대한 테스트를 작성한 다음 통과시키세요"

"버그 수정" → "버그를 재현하는 테스트를 작성한 다음 통과시키세요"

"X 리팩터링" → "이전과 이후에 테스트가 통과하는지 확인하세요"

다단계 작업의 경우, 간략한 계획을 세우세요:

1. [단계] → 확인: [체크]
2. [단계] → 확인: [체크]
3. [단계] → 확인: [체크]