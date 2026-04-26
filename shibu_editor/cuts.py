"""編集計画 → ffmpeg cut スクリプト変換 (manual §4.6 Step 4-5)."""

from __future__ import annotations

from pathlib import Path

from .config import CROSSFADE_MS, FPS, RESOLUTION, WORD_BOUNDARY_PADDING_MS
from .plan import EditingPlan


def compute_keep_segments(
    plan: EditingPlan,
    apply_tempo_adjustments: bool = False,
) -> list[tuple[float, float]]:
    """編集計画から「残す範囲」リストを計算.

    raw 動画全体から must_cuts (+ 承認済みなら tempo_adjustments) を引いた残り。
    do_not_touch は明示的に「残す」ことを保証する。
    """
    raw_duration = plan.video.raw_duration_seconds

    # カットする時間範囲 (start, end) を集約
    cut_ranges: list[tuple[float, float]] = []
    for cut in plan.must_cuts:
        cut_ranges.append((cut.start_seconds, cut.end_seconds))

    if apply_tempo_adjustments:
        for adj in plan.tempo_adjustments:
            cut_ranges.append((adj.start_seconds, adj.end_seconds))

    # do_not_touch とぶつかるカットは除外 (保護)
    protected: list[tuple[float, float]] = [
        (d.start_seconds, d.end_seconds) for d in plan.do_not_touch
    ]
    cut_ranges = [
        (s, e) for (s, e) in cut_ranges if not _overlaps_any(s, e, protected)
    ]

    # ソート + マージ
    cut_ranges.sort()
    merged: list[tuple[float, float]] = []
    for s, e in cut_ranges:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    # 残す範囲 = 全体 - カット範囲
    keeps: list[tuple[float, float]] = []
    cursor = 0.0
    for s, e in merged:
        if s > cursor:
            keeps.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < raw_duration:
        keeps.append((cursor, raw_duration))

    return keeps


def _overlaps_any(s: float, e: float, ranges: list[tuple[float, float]]) -> bool:
    return any(not (e <= rs or s >= re) for rs, re in ranges)


def generate_ffmpeg_concat_script(
    plan: EditingPlan,
    input_video: Path,
    output_video: Path,
    *,
    apply_tempo_adjustments: bool = False,
    padding_ms: int = WORD_BOUNDARY_PADDING_MS,
    fade_ms: int = CROSSFADE_MS,
) -> str:
    """残す範囲を ffmpeg select / concat フィルターで結合するスクリプトを生成.

    word boundary padding と クロスフェードを技術設定に従って適用。
    """
    keeps = compute_keep_segments(plan, apply_tempo_adjustments=apply_tempo_adjustments)
    pad_s = padding_ms / 1000.0
    fade_s = fade_ms / 1000.0

    # 各セグメントに padding を加える
    padded: list[tuple[float, float]] = []
    for s, e in keeps:
        padded.append((max(0.0, s - pad_s), min(plan.video.raw_duration_seconds, e + pad_s)))

    # ffmpeg select filter: between(t,a,b)+between(t,c,d)+...
    select_clauses_v = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in padded)
    select_clauses_a = select_clauses_v

    width, height = RESOLUTION.split("x")

    cmd_lines = [
        "#!/usr/bin/env bash",
        "# 自動生成: shibu-video-editor (manual §4.6 Step 5)",
        f"# input: {input_video}",
        f"# output: {output_video}",
        f"# segments: {len(keeps)}",
        f"# total kept seconds: {sum(e - s for s, e in keeps):.1f}",
        "",
        "set -euo pipefail",
        "",
        "ffmpeg -y \\",
        f"  -i {_shell_quote(str(input_video))} \\",
        "  -filter_complex \\",
        f"    \"[0:v]select='{select_clauses_v}',setpts=N/FRAME_RATE/TB,fps={FPS},scale={width}:{height}[v]; \\",
        f"     [0:a]aselect='{select_clauses_a}',asetpts=N/SR/TB,afade=t=in:d={fade_s}:st=0[a]\" \\",
        '  -map "[v]" -map "[a]" \\',
        f"  -c:v libx264 -preset medium -crf 18 -r {FPS} \\",
        "  -c:a aac -b:a 192k \\",
        f"  {_shell_quote(str(output_video))}",
        "",
    ]
    return "\n".join(cmd_lines)


def _shell_quote(s: str) -> str:
    """シェル安全引用."""
    return "'" + s.replace("'", "'\\''") + "'"


def write_keep_segments_csv(plan: EditingPlan, path: Path, *, apply_tempo_adjustments: bool = False) -> None:
    """残す範囲を CSV で出力 (DaVinci Resolve / Premiere に取り込み可能)."""
    keeps = compute_keep_segments(plan, apply_tempo_adjustments=apply_tempo_adjustments)
    lines = ["start_seconds,end_seconds,duration_seconds"]
    for s, e in keeps:
        lines.append(f"{s:.3f},{e:.3f},{e - s:.3f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
