import argparse
import asyncio
import sys
import time
from datetime import datetime, timezone

import schedule

from config import load_config
from ai_writer.generator import pick_next_category, save_state, generate_post
from wordpress.categories import fetch_categories
from wordpress.poster import post_to_wordpress


def disable_quick_edit_mode() -> None:
    """Windows 콘솔의 Quick Edit Mode 비활성화 — 마우스 클릭으로 인한 일시정지 방지."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        STD_INPUT_HANDLE = -10
        ENABLE_QUICK_EDIT = 0x0040
        ENABLE_EXTENDED_FLAGS = 0x0080
        handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            new_mode = (mode.value & ~ENABLE_QUICK_EDIT) | ENABLE_EXTENDED_FLAGS
            kernel32.SetConsoleMode(handle, new_mode)
            print("[INFO] Windows 콘솔 Quick Edit Mode 비활성화 완료")
    except Exception as e:
        print(f"[WARN] Quick Edit Mode 비활성화 실패 (무시 가능): {e}")


async def run_once() -> None:
    """카테고리 선택 → 주제 선정 → 글 작성 → 포스팅 1회 실행."""
    config = load_config()

    categories = await fetch_categories(config)
    if not categories:
        print("[ERROR] WordPress에서 카테고리를 가져오지 못했습니다.")
        return

    category = pick_next_category(categories)
    print(f"[INFO] 카테고리: {category['name']} (현재 글 수: {category.get('count', 0)})")

    try:
        post = await generate_post(category["name"], config)
        print(f"[INFO] 주제: {post['topic']}")
        print(f"[INFO] 제목: {post['title']}")
    except Exception as e:
        print(f"[ERROR] 글 생성 실패: {e}")
        return

    success = await post_to_wordpress(
        topic=post["topic"],
        post=post,
        config=config,
        category_id=category["id"],
    )

    if success:
        save_state(category["id"], datetime.now(timezone.utc).isoformat())


def job() -> None:
    """schedule 라이브러리에서 호출하는 동기 래퍼."""
    print(f"[RUN] {datetime.now().isoformat(timespec='seconds')} 포스팅 시작")
    asyncio.run(run_once())


def run_scheduler() -> None:
    """스케줄러 모드: 즉시 1회 + 매일 POST_TIME 실행."""
    config = load_config()
    post_time = config.post_time

    schedule.every().day.at(post_time).do(job)
    print(f"[SCHEDULE] 매일 {post_time} 에 자동 포스팅 예약")
    print("[INFO] 스케줄러 시작. Ctrl+C로 종료.")

    job()  # 시작 즉시 1회 실행

    last_check_date = datetime.now().date()
    while True:
        schedule.run_pending()
        # 절전모드에서 깨어나 날짜가 바뀐 경우 누락된 스케줄 강제 점검
        now_date = datetime.now().date()
        if now_date != last_check_date:
            print(f"[INFO] 날짜 변경 감지: {last_check_date} → {now_date}")
            last_check_date = now_date
            schedule.run_pending()
        time.sleep(5)


def main() -> None:
    """진입점. --once 면 1회 실행 후 종료, 아니면 스케줄러 모드."""
    parser = argparse.ArgumentParser(description="cafe24 auto poster")
    parser.add_argument(
        "--once",
        action="store_true",
        help="스케줄 없이 1회만 실행하고 종료 (Windows 작업 스케줄러용)",
    )
    args = parser.parse_args()

    disable_quick_edit_mode()

    if args.once:
        print(f"[RUN] {datetime.now().isoformat(timespec='seconds')} 1회 실행 모드")
        asyncio.run(run_once())
        return

    run_scheduler()


if __name__ == "__main__":
    main()
