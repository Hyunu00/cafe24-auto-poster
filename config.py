import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    gemini_api_key: str
    pexels_api_key: str
    unsplash_access_key: str
    wp_url: str
    wp_username: str
    wp_app_password: str
    post_status: str
    post_category_id: int
    post_time: str


def load_config() -> Config:
    """환경변수에서 설정값을 로드해 Config 객체로 반환."""
    return Config(
        gemini_api_key=os.environ["GEMINI_API_KEY"],
        pexels_api_key=os.environ["PEXELS_API_KEY"],
        unsplash_access_key=os.getenv("UNSPLASH_ACCESS_KEY", ""),
        wp_url=os.environ["WP_URL"].rstrip("/"),
        wp_username=os.environ["WP_USERNAME"],
        wp_app_password=os.environ["WP_APP_PASSWORD"],
        post_status=os.getenv("POST_STATUS", "publish"),
        post_category_id=int(os.getenv("POST_CATEGORY_ID", "1")),
        post_time=os.getenv("POST_TIME", "12:00"),
    )
