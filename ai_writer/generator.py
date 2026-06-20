import json
import re
from pathlib import Path

from google import genai
from config import Config

STATE_PATH = Path("logs/state.json")


def pick_next_category(categories: list[dict]) -> tuple[dict, int]:
    """카테고리를 순환 선택. (선택된 카테고리, 새 인덱스) 반환."""
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    next_index = (state.get("last_category_index", -1) + 1) % len(categories)
    return categories[next_index], next_index


def save_state(index: int) -> None:
    """사용한 카테고리 인덱스를 저장."""
    STATE_PATH.write_text(
        json.dumps({"last_category_index": index}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _clean_json(raw: str) -> str:
    """마크다운 코드블록 제거 후 반환."""
    return re.sub(r"^```[a-z]*\n?|```$", "", raw.strip())


async def generate_post(category_name: str, config: Config) -> dict:
    """2단계로 글 생성: 주제+팩트 선정 → 본문 작성."""
    client = genai.Client(api_key=config.gemini_api_key)

    # 1단계: 트렌딩 주제 선정 + 팩트 자체 검증
    step1 = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"""카테고리 [{category_name}] 기준으로 지금 한국인이 가장 많이 검색할 법한 주제를 하나 골라주세요.

그 다음, 해당 주제에 대해 네가 확실히 알고 있는 팩트만 정리해줘.
- 수치나 출처가 불분명한 내용은 포함하지 마.
- 확신할 수 없으면 "~로 알려져 있다" 표현 사용.
- 팩트는 5~7개, 핵심만.

JSON으로만 응답 (코드블록 없이):
{{
  "topic": "선정한 주제",
  "verified_facts": ["팩트1", "팩트2", "팩트3", "팩트4", "팩트5"]
}}""",
    )
    s1 = json.loads(_clean_json(step1.text))
    topic: str = s1["topic"]
    facts: str = "\n".join(f"- {f}" for f in s1["verified_facts"])

    # 2단계: 검증된 팩트 기반 블로그 본문 작성
    step2 = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"""주제: {topic}
검증된 팩트:
{facts}

위 내용을 바탕으로 한국어 블로그 글을 HTML로 작성해줘.

[톤 — 이게 제일 중요]
- 10년차 블로거가 쓴 것처럼. 똑똑하고 감성 있는 사람.
- "안녕하세요", "오늘은 ~알아보겠습니다", "도움이 되셨으면" 같은 표현 절대 금지.
- 핵심만 간결하게. 읽다 보면 가끔 피식 하거나 공감되는 문장 하나씩.
- 구어체+문어체 자연스럽게 섞기. 친한 선배한테 설명 듣는 느낌.
- 불확실한 내용은 "~로 알려져 있다", "대체로 ~" 등으로 솔직하게 표현.

[HTML 구성]
- <style> 안에 세련된 CSS (카드형 레이아웃, 가독성 좋은 여백/폰트/색상)
- 상단 섹션 내비게이션 (앵커 링크)
- 이미지 자리마다 반드시 삽입:
  <div class="rt-img-box"><img src="/* 번호. 항목명 이미지 URL */" alt="항목명"></div>
- 구성: 공감 인트로(2~3문장) → 핵심 항목 5개(특징+장단점+한줄평) → 비교 요약 표 → 짧은 결론

JSON으로만 응답 (코드블록 없이):
{{
  "title": "제목 (클릭하고 싶고, TOP5 형식)",
  "content": "전체 HTML (<style>부터 끝까지)",
  "excerpt": "자연스러운 말투로 150자 이내 요약"
}}""",
    )
    result = json.loads(_clean_json(step2.text))
    result["topic"] = topic
    return result
