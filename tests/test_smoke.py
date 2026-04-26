"""Smoke tests — Claude API を呼ばずに動作確認."""

from __future__ import annotations

from pathlib import Path

import pytest

from shibu_editor.chapters import (
    render_chapters,
    render_description,
    render_tags,
    render_title,
)
from shibu_editor.config import (
    DURATION_TARGET_MAX,
    DURATION_TARGET_MIN,
    INTERVIEW_QUESTIONS,
    SECTION_RATIOS,
)
from shibu_editor.cuts import compute_keep_segments, generate_ffmpeg_concat_script
from shibu_editor.plan import Chapter, EditingPlan, MustCut, Section, TechSettings, VideoMetadata


def _build_dummy_plan() -> EditingPlan:
    """ZaCijqXrK0k 構造を模した最小プラン."""
    return EditingPlan(
        video=VideoMetadata(
            raw_duration_seconds=2560.0,
            estimated_output_seconds_min=1680.0,
            estimated_output_seconds_max=1920.0,
            cast="しぶ × みかん",
        ),
        sections=[
            Section(name="highlights", start_seconds=0, end_seconds=97, estimated_output_seconds=80, notes="フック"),
            Section(name="coaching_day1", start_seconds=97, end_seconds=365, estimated_output_seconds=240, notes=""),
            Section(name="coaching_day2", start_seconds=365, end_seconds=573, estimated_output_seconds=180, notes=""),
            Section(name="coaching_day3", start_seconds=573, end_seconds=799, estimated_output_seconds=200, notes=""),
            Section(name="before_after", start_seconds=799, end_seconds=827, estimated_output_seconds=28, notes=""),
            Section(name="interview", start_seconds=827, end_seconds=2244, estimated_output_seconds=1380, notes=""),
        ],
        must_cuts=[
            MustCut(
                pattern_id="retake_name_mistake",
                start_seconds=3.0,
                end_seconds=27.0,
                trigger_text="ごめんなさい、もう一回",
                reason="冒頭撮り直し",
            ),
        ],
        chapters_for_description=[
            Chapter(timestamp="0:00", title="ハイライト"),
            Chapter(timestamp="14:15", title="自己紹介"),
            Chapter(timestamp="32:42", title="視聴者さんへのメッセージ"),
        ],
        tech_settings=TechSettings(),
    )


def test_section_ratios_sum_to_almost_one() -> None:
    """4 大セクション尺配分の合計がほぼ 1 になる."""
    total = sum(SECTION_RATIOS.values())
    assert 0.98 <= total <= 1.0


def test_interview_has_8_questions() -> None:
    """インタビュー質問は ZaCijqXrK0k の正規 8 問."""
    assert len(INTERVIEW_QUESTIONS) == 8
    assert INTERVIEW_QUESTIONS[0]["title"] == "自己紹介"
    assert INTERVIEW_QUESTIONS[7]["title"] == "視聴者さんへのメッセージ"


def test_q4_q6_q8_are_do_not_touch() -> None:
    """質問 4 / 6 / 8 は触らない (核となる成果 / 評価 / セールス)."""
    must_protect = {q["n"] for q in INTERVIEW_QUESTIONS if q.get("do_not_touch")}
    assert {4, 6, 8} <= must_protect


def test_target_range() -> None:
    """想定尺は 28-32 分."""
    assert DURATION_TARGET_MIN == 28 * 60
    assert DURATION_TARGET_MAX == 32 * 60


def test_compute_keep_segments_excludes_must_cut() -> None:
    """必須カット範囲が除外される."""
    plan = _build_dummy_plan()
    keeps = compute_keep_segments(plan, apply_tempo_adjustments=False)
    # raw 2560s から 3-27s をカット → 0-3, 27-2560 が残るはず
    assert len(keeps) == 2
    assert keeps[0] == (0.0, 3.0)
    assert keeps[1] == (27.0, 2560.0)
    assert sum(e - s for s, e in keeps) == pytest.approx(2536.0)


def test_ffmpeg_script_is_executable_format() -> None:
    """生成された ffmpeg スクリプトに必須要素が含まれる."""
    plan = _build_dummy_plan()
    script = generate_ffmpeg_concat_script(plan, Path("input.mp4"), Path("output.mp4"))
    assert script.startswith("#!/usr/bin/env bash")
    assert "ffmpeg -y" in script
    assert "1280:720" in script
    assert "fps=25" in script
    assert "-c:v libx264" in script
    assert "between(t," in script  # select filter


def test_render_chapters_format() -> None:
    """チャプターは 'mm:ss タイトル' 形式."""
    plan = _build_dummy_plan()
    text = render_chapters(plan.chapters_for_description)
    lines = text.split("\n")
    assert lines[0] == "0:00 ハイライト"
    assert lines[1] == "14:15 自己紹介"
    assert lines[2] == "32:42 視聴者さんへのメッセージ"


def test_render_description_normal() -> None:
    """通常公開時 description にプロフィールと ☑️ 6 項目が入る."""
    plan = _build_dummy_plan()
    desc = render_description(
        nickname="みかん",
        age="33",
        layout="実家",
        living_style="実家暮らし",
        plan=plan,
    )
    assert "みかんさん/33/実家/実家暮らし" in desc
    assert "☑️ミニマリストしぶ本人による3ヶ月の直接指導" in desc
    assert desc.count("☑️") == 6


def test_render_description_redacted() -> None:
    """削除依頼後フォーマットは ■ 4 項目 + プロフィール削除."""
    plan = _build_dummy_plan()
    desc = render_description(
        nickname="みかん",
        age="33",
        layout="実家",
        living_style="実家暮らし",
        plan=plan,
        redacted=True,
    )
    assert "みかんさん/33/" not in desc
    assert "📣YouTubeに出なくても受講可能！" in desc
    assert desc.count("■") == 4
    assert desc.count("☑️") == 0


def test_render_title_format() -> None:
    """タイトル定型に当てはまる."""
    title = render_title(
        transition_1="不用品が26万円",
        transition_2="家賃も半額に",
        nickname="みかん",
    )
    assert title == "【コーチング実績】不用品が26万円、家賃も半額に「みかん」さん"


def test_tags_are_official_eleven() -> None:
    """公式タグは 11 種."""
    tags = render_tags()
    assert len(tags) == 11
    assert "ミニマリスト" in tags
    assert "VLOG" in tags


def test_protected_section_is_kept() -> None:
    """do_not_touch は保護される."""
    from shibu_editor.plan import DoNotTouch

    plan = _build_dummy_plan()
    # 質問 8 (32:42〜37:24) を保護
    plan.do_not_touch.append(
        DoNotTouch(
            reason="sales_section_q8",
            start_seconds=1962.0,
            end_seconds=2244.0,
            description="視聴者へのメッセージ - 触らない",
        )
    )
    # 偽の must_cut が保護範囲を踏もうとしても無視される
    plan.must_cuts.append(
        MustCut(
            pattern_id="silence_with_breath",
            start_seconds=2000.0,
            end_seconds=2010.0,
            trigger_text="(誤判定の無音)",
            reason="保護範囲内なので無視されるべき",
        )
    )
    keeps = compute_keep_segments(plan)
    # 2000-2010 がカットされていないことを確認
    assert any(s <= 2000.0 < e for s, e in keeps)
    assert any(s < 2010.0 <= e for s, e in keeps)
