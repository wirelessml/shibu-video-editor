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

    # do_not_touch と重なる部分を各カットから差し引く (保護範囲は必ず残す)。
    # 旧実装は少しでも重なるカットを丸ごと捨てており、保護範囲外の前後まで
    # 切れずに残っていた (Codex review #6)。完全内包される誤カットは
    # 差し引き後に空になり、従来どおり無視される。
    protected: list[tuple[float, float]] = [
        (d.start_seconds, d.end_seconds) for d in plan.do_not_touch
    ]
    subtracted: list[tuple[float, float]] = []
    for s, e in cut_ranges:
        subtracted.extend(_subtract_ranges(s, e, protected))
    cut_ranges = subtracted

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


def _subtract_ranges(
    s: float, e: float, protected: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """範囲 (s, e) から protected 群と重なる部分を差し引いた残りを返す."""
    segments: list[tuple[float, float]] = [(s, e)]
    for ps, pe in protected:
        nxt: list[tuple[float, float]] = []
        for cs, ce in segments:
            if pe <= cs or ps >= ce:
                nxt.append((cs, ce))  # 重なりなし
                continue
            if cs < ps:
                nxt.append((cs, ps))  # 保護範囲の手前
            if pe < ce:
                nxt.append((pe, ce))  # 保護範囲の後ろ
        segments = nxt
    return [(a, b) for a, b in segments if b - a > 1e-9]


def generate_ffmpeg_concat_script(
    plan: EditingPlan,
    input_video: Path,
    output_video: Path,
    *,
    apply_tempo_adjustments: bool = False,
    padding_ms: int = WORD_BOUNDARY_PADDING_MS,
    fade_ms: int = CROSSFADE_MS,
) -> str:
    """残す範囲を ffmpeg trim/atrim + concat で結合するスクリプトを生成.

    各セグメントを個別に trim し concat で連結することで、境界ごとに
    短い afade (in/out) を挿入できる。旧実装は select/aselect で全体を
    1 本にまとめ冒頭だけ fade-in していたため、CROSSFADE_MS が狙う境界の
    ブツ音防止が効いていなかった (Codex review #2)。
    """
    keeps = compute_keep_segments(plan, apply_tempo_adjustments=apply_tempo_adjustments)
    if not keeps:
        raise ValueError(
            "残す範囲が 0 セグメントです (全区間がカット対象)。"
            " must_cuts / tempo_adjustments が動画全体を覆っていないか確認してください。"
        )

    pad_s = padding_ms / 1000.0
    fade_s = fade_ms / 1000.0
    raw_duration = plan.video.raw_duration_seconds

    # 各セグメントに padding を加える
    padded: list[tuple[float, float]] = []
    for s, e in keeps:
        padded.append((max(0.0, s - pad_s), min(raw_duration, e + pad_s)))

    width, height = RESOLUTION.split("x")

    # trim/atrim セグメント + 境界フェード → concat
    graph_parts: list[str] = []
    concat_inputs: list[str] = []
    for i, (s, e) in enumerate(padded):
        seg_dur = e - s
        # フェード長はセグメント尺の半分を超えない (in/out の重なり防止)
        seg_fade = min(fade_s, seg_dur / 2.0) if seg_dur > 0 else 0.0
        fade_out_st = max(0.0, seg_dur - seg_fade)
        graph_parts.append(
            f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}]"
        )
        graph_parts.append(
            f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS,"
            f"afade=t=in:st=0:d={seg_fade:.3f},"
            f"afade=t=out:st={fade_out_st:.3f}:d={seg_fade:.3f}[a{i}]"
        )
        concat_inputs.append(f"[v{i}][a{i}]")

    n = len(padded)
    graph_parts.append("".join(concat_inputs) + f"concat=n={n}:v=1:a=1[vc][a]")
    graph_parts.append(f"[vc]fps={FPS},scale={width}:{height}[v]")
    filtergraph = ";".join(graph_parts)

    cmd_lines = [
        "#!/usr/bin/env bash",
        "# 自動生成: takeru-video-editor (manual §4.6 Step 5)",
        f"# input: {_safe_comment(input_video)}",
        f"# output: {_safe_comment(output_video)}",
        f"# segments: {len(keeps)}",
        f"# total kept seconds: {sum(e - s for s, e in keeps):.1f}",
        "",
        "set -euo pipefail",
        "",
        "ffmpeg -y \\",
        f"  -i {_shell_quote(str(input_video))} \\",
        f"  -filter_complex {_shell_quote(filtergraph)} \\",
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


def _safe_comment(value: object) -> str:
    """コメント行に埋め込むパスから改行・制御文字を除去.

    `# input: {path}` のコメントは 1 行しかコメントアウトしないため、
    改行を含むファイル名をそのまま埋め込むと後続が実行行になり
    script injection になり得る (Codex review §6)。印字不可文字は空白へ。
    """
    return "".join(ch if ch.isprintable() else " " for ch in str(value))


def write_keep_segments_csv(plan: EditingPlan, path: Path, *, apply_tempo_adjustments: bool = False) -> None:
    """残す範囲を CSV で出力 (DaVinci Resolve / Premiere に取り込み可能)."""
    keeps = compute_keep_segments(plan, apply_tempo_adjustments=apply_tempo_adjustments)
    lines = ["start_seconds,end_seconds,duration_seconds"]
    for s, e in keeps:
        lines.append(f"{s:.3f},{e:.3f},{e - s:.3f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
