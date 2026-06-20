import asyncio
import schedule
import time

from config import load_config
from ai_writer.generator import pick_next_category, save_state, generate_post
from wordpress.categories import fetch_categories
from wordpress.poster import post_to_wordpress


async def run_once() -> None:
    """카테고리 선택 → 주제 선정 → 글 작성 → 포스팅 1회 실행."""
    config = load_config()

    # 1. 카테고리 목록 가져오기
    categories = await fetch_categories(config)
    if not categories:
        print("[ERROR] WordPress에서 카테고리를 가져오지 못했습니다.")
        return

    # 2. 다음 카테고리 순환 선택
    category, next_index = pick_next_category(categories)
    print(f"[INFO] 카테고리: {category['name']} ({next_index + 1}/{len(categories)})")

    # 3. AI 글 생성 (주제 선정 → 본문 작성)
    try:
        post = await generate_post(category["name"], config)
        print(f"[INFO] 주제: {post['topic']}")
        print(f"[INFO] 제목: {post['title']}")
    except Exception as e:
        print(f"[ERROR] 글 생성 실패: {e}")
        return

    # 4. WordPress 포스팅
    success = await post_to_wordpress(
        topic=post["topic"],
        post=post,
        config=config,
        category_id=category["id"],
    )

    # 5. 성공 시에만 카테고리 인덱스 저장
    if success:
        save_state(next_index)


def job() -> None:
    """schedule 라이브러리에서 호출하는 동기 래퍼."""
    asyncio.run(run_once())


def main() -> None:
    """스케줄러를 설정하고 실행 루프를 시작."""
    config = load_config()
    post_time = config.post_time

    schedule.every().day.at(post_time).do(job)
    print(f"[SCHEDULE] 매일 {post_time} 에 자동 포스팅 예약")
    print("[INFO] 스케줄러 시작. Ctrl+C로 종료.")

    job()  # 시작 즉시 1회 실행

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
