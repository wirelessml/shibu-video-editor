"""description チャプター生成 (manual §3.5)."""

from __future__ import annotations

from .config import (
    DEFAULT_TAGS,
    DESCRIPTION_REDACTED_TEMPLATE,
    DESCRIPTION_TEMPLATE,
    TITLE_FORMAT,
)
from .plan import Chapter, EditingPlan


def render_chapters(chapters: list[Chapter]) -> str:
    """チャプターを description 末尾用の 14 行テキストに整形.

    YouTube 公式の検出仕様に合わせる:
    - 先頭は 00:00 (ゼロ詰め)
    - 全角括弧（）でラップ (しぶチャンネル既定)
    - 末尾改行で description 全体の体裁維持
    """
    return "\n".join(f"{c.timestamp} {c.title}" for c in chapters) + "\n"


def render_description(
    nickname: str,
    age: str,
    layout: str,
    living_style: str,
    plan: EditingPlan,
    *,
    redacted: bool = False,
) -> str:
    """通常公開時または削除依頼後の description を生成 (manual §3.4)."""
    chapters_text = render_chapters(plan.chapters_for_description)
    tmpl = DESCRIPTION_REDACTED_TEMPLATE if redacted else DESCRIPTION_TEMPLATE
    return tmpl.format(
        nickname=nickname,
        age=age,
        layout=layout,
        living_style=living_style,
        chapters=chapters_text,
    )


def render_title(transition_1: str, transition_2: str, nickname: str) -> str:
    """タイトル定型に当てはめて生成 (manual §3.3)."""
    return TITLE_FORMAT.format(
        transition_1=transition_1,
        transition_2=transition_2,
        nickname=nickname,
    )


def render_tags() -> list[str]:
    """公式タグ 11 種を返す (manual §3.6)."""
    return list(DEFAULT_TAGS)
