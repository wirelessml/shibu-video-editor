"""Claude API で 4 階層フレーム編集計画を生成 (manual §4.6 Step 3)."""

from __future__ import annotations

import json
import os
from typing import Any

import anthropic
from pydantic import BaseModel, Field

from .config import (
    DURATION_TARGET_MAX,
    DURATION_TARGET_MIN,
    EFFORT,
    MODEL,
)
from .prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE


class VideoMetadata(BaseModel):
    raw_duration_seconds: float
    estimated_output_seconds_min: float
    estimated_output_seconds_max: float
    cast: str


class Section(BaseModel):
    name: str
    start_seconds: float
    end_seconds: float
    estimated_output_seconds: float
    notes: str


class MustCut(BaseModel):
    pattern_id: str
    start_seconds: float
    end_seconds: float
    trigger_text: str
    reason: str


class TempoAdjustment(BaseModel):
    pattern_id: str
    start_seconds: float
    end_seconds: float
    action: str
    requires_approval: bool = True
    rationale: str


class DoNotTouch(BaseModel):
    reason: str
    start_seconds: float
    end_seconds: float
    description: str


class TechSettings(BaseModel):
    resolution: str = "1280x720"
    fps: int = 25
    cut_boundary: str = "word_boundary"
    padding_ms: int = 100
    fade_ms: int = 30
    subtitle_burnin: bool = False
    color_grading: bool = False


class InterviewQuestion(BaseModel):
    n: int
    title: str
    start_seconds: float
    end_seconds: float
    preserve: bool = False


class Chapter(BaseModel):
    timestamp: str
    title: str


class EditingPlan(BaseModel):
    """13:47 みかん計画書相当の編集方針案."""

    video: VideoMetadata
    sections: list[Section] = Field(default_factory=list)
    must_cuts: list[MustCut] = Field(default_factory=list)
    tempo_adjustments: list[TempoAdjustment] = Field(default_factory=list)
    do_not_touch: list[DoNotTouch] = Field(default_factory=list)
    tech_settings: TechSettings = Field(default_factory=TechSettings)
    interview_questions: list[InterviewQuestion] = Field(default_factory=list)
    chapters_for_description: list[Chapter] = Field(default_factory=list)
    summary_markdown: str = ""


def _format_seconds(s: float) -> str:
    s_int = int(s)
    return f"{s_int // 60}:{s_int % 60:02d}"


def generate_plan(
    transcript: list[dict[str, Any]],
    nickname: str,
    profile: str,
    cohort_number: int,
    raw_duration_seconds: float,
    *,
    target_min_seconds: int = DURATION_TARGET_MIN,
    target_max_seconds: int = DURATION_TARGET_MAX,
    filming_mode: str = "オンライン (ZOOM 越し + 受講生自宅映像)",
    user_notes: str = "なし",
    api_key: str | None = None,
    model: str = MODEL,
    effort: str = EFFORT,
    verbose: bool = False,
) -> EditingPlan:
    """4 階層フレーム編集計画を Claude API で生成.

    プロンプト caching を使用してシステムプロンプトを再利用可能に。
    adaptive thinking で複雑な判断を自動調整。
    """
    client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    user_prompt = USER_PROMPT_TEMPLATE.format(
        nickname=nickname,
        profile=profile,
        cohort_number=cohort_number,
        raw_duration_str=_format_seconds(raw_duration_seconds),
        target_min_str=_format_seconds(target_min_seconds),
        target_max_str=_format_seconds(target_max_seconds),
        filming_mode=filming_mode,
        transcript_json=json.dumps(transcript, ensure_ascii=False, separators=(",", ":")),
        user_notes=user_notes,
    )

    if verbose:
        from rich.console import Console

        console = Console()
        console.print(f"[bold cyan]Calling {model} (effort={effort}) ...[/bold cyan]")
        console.print(f"  transcript: {len(transcript)} words")
        console.print(f"  raw duration: {_format_seconds(raw_duration_seconds)}")
        console.print(f"  target output: {_format_seconds(target_min_seconds)} 〜 {_format_seconds(target_max_seconds)}")

    # 大きな出力を扱うため streaming を使用 (claude-api skill 推奨)
    accumulated_text = ""
    with client.messages.stream(
        model=model,
        max_tokens=64000,
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},  # システムプロンプトをキャッシュ
            }
        ],
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        for text_chunk in stream.text_stream:
            accumulated_text += text_chunk
            if verbose:
                print(text_chunk, end="", flush=True)
        final_message = stream.get_final_message()

    if verbose:
        from rich.console import Console

        console = Console()
        usage = final_message.usage
        console.print()
        console.print(
            f"[dim]usage: input={usage.input_tokens} "
            f"cache_read={usage.cache_read_input_tokens} "
            f"cache_create={usage.cache_creation_input_tokens} "
            f"output={usage.output_tokens}[/dim]"
        )

    # JSON 抽出 (Claude が markdown コードフェンスで包む可能性に備える)
    text = accumulated_text.strip()
    if text.startswith("```"):
        # ```json ... ``` を剥がす
        lines = text.split("\n")
        text = "\n".join(line for line in lines[1:-1] if line.strip())

    try:
        plan_dict = json.loads(text)
    except json.JSONDecodeError as e:
        # JSON 開始位置を検索して切り出し
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace > first_brace:
            try:
                plan_dict = json.loads(text[first_brace : last_brace + 1])
            except json.JSONDecodeError:
                raise ValueError(f"Claude のレスポンスから JSON を抽出できませんでした: {e}\n\n--- raw response ---\n{text[:2000]}") from e
        else:
            raise ValueError(f"Claude のレスポンスから JSON を抽出できませんでした: {e}\n\n--- raw response ---\n{text[:2000]}") from e

    return EditingPlan.model_validate(plan_dict)
