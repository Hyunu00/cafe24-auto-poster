import json
import re
from pathlib import Path

from google import genai
from google.genai import types
from config import Config

STATE_PATH = Path("logs/state.json")
MODEL = "gemini-2.5-flash"


def _gen_config(max_tokens: int = 16384) -> types.GenerateContentConfig:
    """JSON 모드 + 충분한 출력 토큰 한도."""
    return types.GenerateContentConfig(
        response_mime_type="application/json",
        max_output_tokens=max_tokens,
        temperature=0.9,
    )


async def _generate_json(client: genai.Client, prompt: str, max_tokens: int = 16384, retries: int = 1) -> dict:
    """Gemini JSON 모드로 호출하고 dict 반환. 파싱 실패 시 retries회 재시도."""
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = await client.aio.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=_gen_config(max_tokens),
            )
            text = (resp.text or "").strip()
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
            return json.loads(text)
        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            if attempt < retries:
                print(f"[WARN] JSON 파싱 실패 ({attempt + 1}/{retries + 1}), 재시도 중...")
                continue
            raise
    raise RuntimeError(f"JSON 생성 실패: {last_error}")


def _load_state() -> dict:
    """state.json을 읽어 dict 반환. 없거나 깨졌으면 기본값."""
    if not STATE_PATH.exists():
        return {"last_posted_at": {}}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if "last_posted_at" not in data:
            data["last_posted_at"] = {}
        return data
    except Exception:
        return {"last_posted_at": {}}


def pick_next_category(categories: list[dict]) -> dict:
    """글 수가 가장 적은 카테고리부터 선택. 동률이면 가장 오래 안 쓰인 것 우선.

    categories는 WP REST API 응답 그대로 (id, name, count 포함).
    """
    state = _load_state()
    last_posted = state.get("last_posted_at", {})

    def sort_key(cat: dict) -> tuple[int, str]:
        # 1순위: 글 수 (오름차순)
        # 2순위: 마지막 포스팅 시간 (오래된 게 먼저, 안 쓴 카테고리는 빈 문자열로 최우선)
        count = int(cat.get("count", 0))
        last = last_posted.get(str(cat["id"]), "")
        return (count, last)

    return sorted(categories, key=sort_key)[0]


def save_state(category_id: int, posted_at: str) -> None:
    """해당 카테고리의 마지막 포스팅 시각을 저장."""
    state = _load_state()
    state["last_posted_at"][str(category_id)] = posted_at
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def generate_post(category_name: str, config: Config) -> dict:
    """3단계로 글 생성: 주제 선정 → 형식+개요 설계 → 본문 작성."""
    client = genai.Client(api_key=config.gemini_api_key)

    # ────────────────────────────────────────────────────────────
    # 1단계: 카테고리에 맞는 주제 선정 + 자체 검증
    # ────────────────────────────────────────────────────────────
    s1 = await _generate_json(
        client,
        prompt=f"""당신은 카테고리 [{category_name}] 전문 블로거입니다.

[작업]
이 카테고리에 정확히 맞으면서 한국 2030이 지금 검색할 만한 주제 하나 선정.

[주제 규칙]
- 반드시 [{category_name}] 카테고리에 명백히 속해야 함. 인접 분야 X.
- 시간이 지나도 가치 있는 주제로 — "지금도, 1년 뒤에도 검색될 만한 것"
- 너무 광범위 X, 너무 사소 X, 검색 의도 명확한 것.
- 옛날 사례 위주의 회고성 주제 X. 현재 시점에서 유효한 정보 위주.

[자체 검증]
주제를 정한 뒤, 왜 이 주제가 [{category_name}]에 명백히 속하는지 한 문장 설명.
설명이 어색하면 다른 주제로 다시.

[팩트 정리 — 가장 중요]
주제에 대해 확실히 아는 팩트만 7~10개.
- ❌ 특정 연도 숫자 (예: "2019년 기준 OO%") — 구식 느낌 남
- ❌ 특정 시점에만 유효했던 사례
- ❌ 출처 불명확한 수치
- ✅ 지금도 유효한 일반 지식 / 메커니즘 / 본질적 특성
- ✅ "대체로", "일반적으로", "최근에는" 같은 시점 표현 사용
- 추측 절대 금지. 모르면 빼.

JSON만 응답 (코드블록 없이):
{{
  "topic": "선정한 주제 (구체적으로)",
  "category_fit_reason": "왜 이 주제가 [{category_name}]에 속하는가",
  "verified_facts": ["팩트1", "팩트2", "팩트3", "팩트4", "팩트5", "팩트6", "팩트7"]
}}""",
        max_tokens=4096,
    )
    topic: str = s1["topic"]
    facts_text: str = "\n".join(f"- {f}" for f in s1["verified_facts"])

    # ────────────────────────────────────────────────────────────
    # 2단계: 주제에 가장 어울리는 글 형식 + 개요 설계
    # ────────────────────────────────────────────────────────────
    s2 = await _generate_json(
        client,
        prompt=f"""주제: {topic}
카테고리: {category_name}
검증된 팩트:
{facts_text}

[작업]
주제에 가장 어울리는 자연스러운 형식을 직접 판단해서 개요를 설계해.
"이 글을 사람이 썼다면 어떻게 썼을까"를 기준으로.

[형식 — 참고용. 정형적으로 안 따라도 됨]
- 핵심 통찰 위주의 에세이형 (가장 사람티 남)
- 진짜 비교할 게 있을 때만: 비교/리뷰
- 진짜 단계가 있을 때만: 가이드
- 진짜 자주 묻는 질문일 때만: Q&A
- 사례로 풀어내기
※ 절대 "TOP 5" 같은 거 무조건 만들지 마. 주제가 자연스럽게 TOP5에 맞아야만.

[섹션 설계]
- 섹션 3~5개. 4개 권장.
- 모든 섹션이 똑같은 비중일 필요 X — 핵심 섹션은 길고, 보조는 짧고.
- 섹션 제목도 정형적이지 않게. "장점/단점/결론" 같은 거 X.
  좋은 예: "왜 갑자기 다들 이걸 찾을까", "솔직히 단점부터", "이거 하나는 진짜 다름"
- 마지막 섹션은 결론이 아니라도 됨 — 본문 흐름이 자연스럽게 끝나면 결론 따로 X.

[이미지 검색어]
- 각 섹션마다 영문 검색어 폴백 체인 3단계 (구체→중간→일반).
  예: ["cappadocia hot air balloon turkey", "cappadocia balloon", "hot air balloon"]
- 대표 이미지도 같은 형식.
- 반드시 영문. Pexels는 영문 검색이 훨씬 정확.

[제목 규칙]
- 클릭 유도하되 자극적/낚시성 X.
- "완벽 가이드", "총정리", "꿀팁 모음" 같은 AI 티 나는 표현 X.
- 사람이 쓸 법한 톤: 솔직한 질문, 구체적 약속, 의외성.
- 좋은 예: "카파도키아 열기구, 가격보다 시즌이 진짜 중요한 이유", "전세 사기 안 당하는 법, 변호사 말고 부동산이 알려줌"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[밈/유행어 사용 여부 — 기본값은 "사용 X". 확신 들 때만 사용]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

이 주제에 한국 인터넷 밈/유행어가 자연스럽게 녹는지 직접 판단.

[원칙 — 매우 보수적으로]
- **기본값은 use_memes: false**. 억지로 끼우려 하지 마.
- 밈 없어도 글은 잘 써져. 정보의 가치가 우선.
- "약간 어울릴 것 같다" 정도면 패스. "이거 안 넣으면 어색할 정도"일 때만 넣어.
- 의심 들면 false. 후회는 false 쪽이 덜 함.

[판단 기준]
- 진중/민감 주제 (건강·의료, 금융·투자, 법, 사고·사망, 정치 등) → 무조건 false.
- 일반 정보성 주제 (역사, 문화, 일반 지식, 학습 등) → 기본 false. 정보 신뢰감 우선.
- 매우 가벼운 일상/엔터/유머 코드가 있는 주제일 때만 true 고려.
  예: "MZ가 좋아하는 카페 인테리어", "넷플릭스 신작 리액션", "갓생 사는 친구의 루틴"

[후보 풀 — 여기서 고르거나 더 좋은 거 떠올려도 OK]
- 확언/팩트: "ㄹㅇ", "ㄹㅇ로", "팩트는", "솔직히", "사실은"
- 감정/리액션: "현타", "킹받", "오졌", "쩐다", "역대급", "오히려"
- 추측/정리: "~인 듯", "~인 거 같음", "TMI", "내 생각엔"
- 가벼운 강조: "찐", "찐맛", "ㄷㄷ"
- 상황 묘사: "야르 (야 이건 무리야)", "거제 야호 (놀랍거나 통쾌)"
- 자기 떨떠름함: "내가 이걸 왜...", "근데 진짜로"

[금지]
- 차별/혐오/정치 밈 X
- 일반 독자가 모를 정도로 마이너한 밈 X
- 한물간 죽은 밈 ("ㅇㄱㄹㅇ", "헐랭" 같은 옛 톤) X
- 비속어/은어 X (애드센스 정책)

[중요 — 강제로 쓰지 마]
- "안 쓰는 것"이 가장 안전한 선택. 의심되면 무조건 false.
- 쓸 거면 글 전체에서 1~2번. 한 단락에 2개 이상 X. (3개도 많음, 1~2개로 자제)
- 글의 정보 가치를 해치지 않는 선에서만.
- 억지로 끼워넣으면 그게 더 어색하고 AI 티 남. 자연스러운 게 최우선.

JSON만 응답 (코드블록 없이):
{{
  "format": "선택한 형식 (자유 서술)",
  "format_reason": "왜 이 형식이 이 주제에 자연스러운가 (한 문장)",
  "title": "클릭하고 싶은 한국어 제목",
  "hero_image_query": ["구체적 영문", "중간 영문", "일반 영문"],
  "sections": [
    {{
      "heading": "사람 티 나는 섹션 제목",
      "key_points": ["다룰 포인트 2~3개"],
      "image_query": ["구체적 영문", "중간 영문", "일반 영문"]
    }}
  ],
  "meme_plan": {{
    "use_memes": true,
    "memes": [
      {{"term": "ㄹㅇ로", "how_to_use": "팩트 강조 한 줄에"}},
      {{"term": "현타", "how_to_use": "솔직한 단점 짚을 때"}}
    ],
    "reason": "왜 쓰거나 안 쓰는지 한 문장"
  }}
}}""",
        max_tokens=4096,
    )
    title: str = s2["title"]
    fmt: str = s2["format"]
    sections: list[dict] = s2["sections"]
    hero_query: list[str] = s2["hero_image_query"]
    meme_plan: dict = s2.get("meme_plan") or {"use_memes": False, "memes": [], "reason": ""}

    # 섹션 개요를 본문 작성용 텍스트로 정리
    outline_text = "\n\n".join(
        f"섹션 {i+1}: {sec['heading']}\n"
        f"  포인트: {', '.join(sec['key_points'])}\n"
        f"  이미지 위치: __IMG_{i+1}__"
        for i, sec in enumerate(sections)
    )

    # ────────────────────────────────────────────────────────────
    # 3단계: 개요 기반 본문 작성 — 밈 가이드 반영
    # ────────────────────────────────────────────────────────────
    if meme_plan.get("use_memes") and meme_plan.get("memes"):
        meme_lines = "\n".join(
            f"  - \"{m['term']}\" — {m.get('how_to_use', '자연스럽게')}"
            for m in meme_plan["memes"]
        )
        meme_block = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[이 글에 사용할 밈 — 2단계에서 골라둔 것]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

다음 밈만 자연스럽게 본문에 녹여 써:
{meme_lines}

- 글 전체에서 합쳐서 1~3번만. 한 단락에 2개 이상 X.
- 위 리스트 외 다른 슬랭/밈은 절대 추가 X.
- 어색하면 그 밈은 빼. 강제로 다 쓸 필요 없음.
"""
    else:
        meme_block = """━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[이 글에 밈 사용 X — 2단계 판단]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

이 주제는 진중하거나 밈이 어울리지 않아서 밈/슬랭 없이 작성.
"솔직히", "근데 이게" 같은 일반적 캐주얼 표현은 적당히 OK.
하지만 "ㄹㅇ", "현타", "킹받" 같은 명백한 밈은 X.
"""

    s3 = await _generate_json(
        client,
        prompt=f"""주제: {topic}
형식: {fmt}
제목: {title}
검증된 팩트:
{facts_text}

[개요]
{outline_text}

[작업]
위 개요로 한국어 블로그 HTML 본문을 써.

{meme_block}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[페르소나 — 매 글 공통]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

"정보는 빠삭한데 말투는 친한 동생 같은 2030 청년 블로거"
- 솔직, 위트, 약간 시니컬한 통찰
- 가벼운 말투 ≠ 가벼운 정보. 팩트는 단단하게, 톤만 친근하게.
- 진실됨이 핵심. 모르면 "이건 나도 모름" 솔직히. 추측 X.
- 평어체 (반말). 격식체 ("~합니다", "~하시기 바랍니다") X.
- "ㅋ" 한 글에 1번 정도까지만. 남용 X.

[절대 금지 — 한 번이라도 나오면 글 망함]
- "안녕하세요", "오늘은 ~알아보겠습니다", "~에 대해 알아볼까요"
- "도움이 되셨길", "구독과 좋아요", "댓글로 알려주세요"
- "결론적으로", "정리하자면", "마무리하며"
- "~하시면 됩니다", "~하시기 바랍니다"
- 비속어, 욕설, 차별 표현 (애드센스 정책)
- "최고의", "완벽한", "환상적인" 같은 광고 카피 표현
- 위 [밈 가이드]에 명시되지 않은 슬랭 ("ㄹㅇ", "현타" 등이 가이드에 없으면 안 씀)

[최신성]
- "2019년 기준", "작년에는" 같은 구체적 시점 X (구식 느낌).
- 대신: "요즘", "최근", "지금 보면", "예전이랑 다르게"
- 옛날 사례 가져오기 X. 지금도 유효한 정보 위주.

[정보 다루는 방식]
- 단순 나열 X. "이게 왜 그런지", "그래서 뭐가 다른지" 맥락 포함.
- 흔한 정보는 빼고 의외성/통찰 위주.
- 솔직한 단점/한계도 짚어주기. (이게 신뢰감 만듦)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[구조 — AI스럽지 않게]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- 인트로: 50~100자. 강한 훅(질문/공감/충격) 한 줄. 길게 늘이지 마.
- 본문 흐름: 단순 나열 X. 주제에 맞게 자연스럽게 (점진/반전/비교/Q&A 등 주제에 맞춰).
- 본문 섹션들: 모든 섹션이 똑같은 분량 X. 핵심은 길게, 부수적은 짧게.
- 마무리: 결론 헤더 안 만들어도 됨. 자연스럽게 닫히면 그걸로 끝.
  만들 거면 한두 줄로 툭. "결론적으로" 절대 X.
- 강조 요소: 콜아웃/TL;DR/표 중 1개만. 모두 다 넣지 마. 안 어울리면 다 빼.
- 목차: 만들지 마. 짧은 글에 목차는 AI 티 최강.
- 불릿 리스트: 3개 이하. 4개 넘으면 글로 풀어 써.

[분량]
- 전체 1500~2000자 (HTML 태그 제외 본문 텍스트 기준)
- 애드센스에 적당. 너무 길면 이탈, 너무 짧으면 광고 자리 부족.

[이미지 위치]
- 각 섹션마다 본문 흐름이 자연스러운 곳에 정확히 한 번:
  <div class="img-wrap"><img src="__IMG_N__" alt="설명"></div>
- N은 1부터 섹션 순서대로. __IMG_1__, __IMG_2__ ... 그대로 사용.
- 섹션 시작 직후보다 중간/끝이 자연스러움.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[CSS — MZ 톤. 다만 카드 박스 떡칠 X]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

원칙: 본문은 블로그 정통 (긴 글 읽기 좋게), 포인트만 트렌디하게.

[폰트 / 본문 베이스]
- font-family: "Pretendard", -apple-system, "Apple SD Gothic Neo", system-ui, sans-serif
- 본문 폰트 17px, 행간 1.8
- 본문 색상 #1a1a1a (완전 검정보단 약간 부드럽게)
- 단락 사이 margin-bottom 1.4em

[포인트 컬러 — 글마다 다르게 골라]
다음 중 주제 분위기에 맞는 거 하나 선택:
- 활기/일상: #FF3D7F (핫핑크) 또는 #FF6B35 (오렌지)
- 신뢰/금융/IT: #6366F1 (인디고) 또는 #0EA5E9 (스카이)
- 자연/건강: #10B981 (에메랄드) 또는 #84CC16 (라임)
- 진중함: #1F2937 (차콜) + 보조 포인트 #F59E0B

[제목 / 헤딩]
- 제목(h1)은 안 만들어. WordPress가 알아서 렌더.
- h2: font-size 26px, font-weight 800, margin-top 2.5em
  좌측에 두꺼운 포인트 컬러 바 (border-left: 6px solid <포인트>; padding-left: 14px)

[키워드 강조 — 적극적으로]
- 핵심 키워드는 <strong> 또는 <mark>로 강조.
- <strong>: 굵게만. font-weight 700.
- <mark>: 형광펜 효과. 흰 배경에 옅은 포인트 컬러 (예: background: linear-gradient(transparent 60%, #FF3D7F33 60%); padding: 0 2px;)
- 한 단락에 1~2개. 남용하면 가독성 망함.

[콜아웃 박스 — 1개만, 정말 중요한 한 줄에]
.callout {{
  border-left: 5px solid <포인트>;
  background: <포인트>0D (투명도 5%);
  padding: 16px 20px;
  border-radius: 0 12px 12px 0;
  margin: 28px 0;
  font-size: 16px;
}}
※ 안 어울리면 안 만들어. 강제 X.

[이미지]
- width: 100%, border-radius: 16px
- margin: 32px 0
- box-shadow: 0 4px 20px rgba(0,0,0,0.08) (살짝 떠 보이게)

[표 — 진짜 비교할 때만]
- border-collapse: collapse
- th: 배경 #F8F9FA, font-weight 700, padding 12px
- td: padding 12px, border-bottom: 1px solid #E5E7EB
- hover 효과 X (AI티 남)

[TL;DR — 글 맨 위 또는 맨 아래에 1개 옵션]
.tldr {{
  background: <포인트>0D;
  border-radius: 14px;
  padding: 18px 22px;
  margin: 24px 0;
  font-size: 15px;
}}
.tldr-label {{
  display: inline-block;
  font-weight: 800;
  font-size: 13px;
  color: <포인트>;
  letter-spacing: 0.5px;
  margin-bottom: 6px;
}}
사용 예: <div class="tldr"><div class="tldr-label">TL;DR</div>한 줄 요약 본문...</div>
※ 자연스러우면 넣고, 억지면 빼.

[금지 — AI 디자인 티 폭발]
- 카드형 배경 박스 떡칠 (배경색 깔린 div 여러 개) X
- 그라데이션 배경 X (오직 <mark> 형광펜에만)
- 박스 안에 또 박스 X
- 모든 단락마다 박스/구분선 X
- 너무 화려한 색 조합 X (포인트는 1색만)

[자기 검증 — 작성 후 다시 보고 수정]
체크리스트:
1. "안녕하세요" / "알아보겠습니다" / "결론적으로" 들어갔나? → 다 지우고 다시 써
2. "~하시기 바랍니다" 같은 격식체 들어갔나? → 평어체로
3. 모든 섹션이 비슷한 길이로 깔끔하게 정렬돼 있나? → 일부러 불균형하게
4. 인트로가 100자 넘나? → 줄여
5. 결론을 억지로 만들었나? → 자연스럽지 않으면 빼
6. __IMG_N__ 플레이스홀더가 섹션 개수만큼 정확히 있나?
7. [밈 가이드]에 명시된 밈만 썼나? 지정된 횟수(1~3번) 지켰나?
8. 같은 표현을 너무 반복하지 않았나? → 분산

JSON만 응답 (코드블록 없이):
{{
  "content": "전체 HTML (<style>부터 끝까지)",
  "excerpt": "150자 이내 발췌. 본문 톤 그대로. 인사 X."
}}""",
        max_tokens=32768,
    )

    # 본문 이미지 검색어 배열을 인덱스 1부터로 정렬 (placeholder는 1-base)
    # replace_body_images는 placeholder 번호 그대로를 index로 쓰므로
    # 0번 슬롯을 비워둠
    image_queries: list[list[str]] = [[]]
    for sec in sections:
        image_queries.append(sec["image_query"])

    return {
        "title": title,
        "content": s3["content"],
        "excerpt": s3["excerpt"],
        "topic": topic,
        "format": fmt,
        "hero_image_query": hero_query,
        "image_queries": image_queries,
    }
