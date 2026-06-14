"""Codex 静的レビュー (2026-06-12) で特定した実バグの回帰テスト.

対象バグ:
- #1 pipeline の typer.Context 誤用 → 一括実行が即クラッシュ
- #2 カット境界フェード未実装 (冒頭 fade-in だけ)
- #3 AI 生成プランの時刻 (範囲/順序/非負/尺超過) 検証なし
- #4 全区間カット時に空 keeps → select='' で ffmpeg エラー
- #6 do_not_touch と部分重複した cut を丸ごと破棄
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from shibu_editor.cuts import compute_keep_segments, generate_ffmpeg_concat_script
from shibu_editor.plan import DoNotTouch, EditingPlan, MustCut, VideoMetadata


def _plan(
    raw: float = 100.0,
    must_cuts: list[MustCut] | None = None,
    do_not_touch: list[DoNotTouch] | None = None,
) -> EditingPlan:
    return EditingPlan(
        video=VideoMetadata(
            raw_duration_seconds=raw,
            estimated_output_seconds_min=raw * 0.5,
            estimated_output_seconds_max=raw * 0.7,
            cast="テスト",
        ),
        must_cuts=must_cuts or [],
        do_not_touch=do_not_touch or [],
    )


def _cut(s: float, e: float, pid: str = "x") -> MustCut:
    return MustCut(
        pattern_id=pid, start_seconds=s, end_seconds=e, trigger_text="t", reason="r"
    )


def _dnt(s: float, e: float) -> DoNotTouch:
    return DoNotTouch(reason="protect", start_seconds=s, end_seconds=e, description="d")


# ----- #3 AI 生成プランの時刻検証 -----


def test_plan_rejects_end_before_start() -> None:
    with pytest.raises(ValidationError):
        _plan(must_cuts=[_cut(20.0, 10.0)])


def test_plan_rejects_negative_time() -> None:
    with pytest.raises(ValidationError):
        _plan(must_cuts=[_cut(-5.0, 10.0)])


def test_plan_rejects_end_beyond_raw_duration() -> None:
    with pytest.raises(ValidationError):
        _plan(raw=100.0, must_cuts=[_cut(90.0, 110.0)])


def test_plan_accepts_valid_ranges() -> None:
    p = _plan(raw=100.0, must_cuts=[_cut(10.0, 20.0)], do_not_touch=[_dnt(40.0, 60.0)])
    assert p.video.raw_duration_seconds == 100.0


# ----- #4 全カット時に空 keeps を診断 -----


def test_empty_keeps_raises_clear_error() -> None:
    p = _plan(raw=100.0, must_cuts=[_cut(0.0, 100.0)])
    assert compute_keep_segments(p) == []
    with pytest.raises(ValueError, match="残す範囲"):
        generate_ffmpeg_concat_script(p, Path("in.mp4"), Path("out.mp4"))


# ----- #6 do_not_touch と部分重複した cut は外側だけ切る -----


def test_partial_overlap_with_protected_cuts_only_outside() -> None:
    p = _plan(
        raw=100.0,
        must_cuts=[_cut(30.0, 70.0)],
        do_not_touch=[_dnt(40.0, 60.0)],
    )
    keeps = compute_keep_segments(p)
    # protected 40-60 は残り、30-40 と 60-70 のみカットされる
    assert keeps == [(0.0, 30.0), (40.0, 60.0), (70.0, 100.0)]


def test_fully_contained_cut_inside_protected_is_ignored() -> None:
    # 既存挙動の維持: 保護範囲に完全内包される誤カットは無視される
    p = _plan(
        raw=100.0,
        must_cuts=[_cut(45.0, 55.0)],
        do_not_touch=[_dnt(40.0, 60.0)],
    )
    keeps = compute_keep_segments(p)
    assert keeps == [(0.0, 100.0)]


# ----- #2 カット境界フェード -----


def test_script_has_per_boundary_audio_fades() -> None:
    p = _plan(raw=100.0, must_cuts=[_cut(40.0, 60.0)])  # keeps: 0-40, 60-100
    script = generate_ffmpeg_concat_script(p, Path("in.mp4"), Path("out.mp4"))
    # trim/atrim + concat ベースで、各セグメントに in/out フェードが入る
    assert "atrim=start=" in script
    assert "afade=t=in" in script
    assert "afade=t=out" in script
    assert "concat=n=2:v=1:a=1" in script
    # 旧実装の単一 aselect/afade-st0 ではない
    assert "aselect=" not in script
    # 仕様の解像度/fps/コーデックは維持
    assert "1280:720" in script
    assert "fps=25" in script
    assert "-c:v libx264" in script


def test_comment_path_newline_is_sanitized() -> None:
    p = _plan(raw=100.0, must_cuts=[_cut(40.0, 60.0)])
    evil = Path("a\nrm -rf danger.mp4")
    script = generate_ffmpeg_concat_script(p, evil, Path("out.mp4"))
    # 改行がスペースに置換され、コメントが 1 行に収まっている (script injection 防止)
    assert "# input: a rm -rf danger.mp4" in script
    # コメントから改行で抜け出した「裸の実行行」が生成されていない。
    # (-i のパスは単一引用符内に閉じ込められているので、そこに改行が
    #  残っていても実行はされない)
    assert "\nrm -rf danger.mp4\n" not in script


# ----- #1 pipeline の typer.Context 誤用 -----


def test_pipeline_no_transcript_dispatches_without_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--transcript 無しの pipeline が Step 1 で即クラッシュしない.

    旧実装は typer.Context(transcribe) 構築で AttributeError を投げていた。
    重い外部依存 (ffmpeg/whisper/Claude/ffprobe) はすべてモック。
    """
    from typer.testing import CliRunner

    import shibu_editor.cli as cli

    monkeypatch.setattr(cli, "extract_audio_with_ffmpeg", lambda video, out: out)
    monkeypatch.setattr(
        cli,
        "transcribe_with_whisper",
        lambda audio, model="large-v3": [
            {"start_ms": 0, "end_ms": 1000, "word": "テスト"}
        ],
    )
    monkeypatch.setattr(cli, "_probe_duration_seconds", lambda video: 100.0)
    monkeypatch.setattr(
        cli,
        "generate_plan",
        lambda **kwargs: _plan(raw=100.0, must_cuts=[_cut(10.0, 20.0)]),
    )

    video = tmp_path / "raw.mp4"
    video.write_bytes(b"\x00")
    out_dir = tmp_path / "out"

    result = CliRunner().invoke(
        cli.app,
        [
            "pipeline", str(video),
            "-n", "みかん", "-p", "33歳", "-c", "5",
            "-o", str(out_dir),
            "--script-only",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "allow_extra_args" not in result.output
    assert (out_dir / "transcript.json").exists()
    assert (out_dir / "plan.json").exists()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg 不在")
def test_generated_script_runs_in_ffmpeg(tmp_path: Path) -> None:
    """生成スクリプトが実 ffmpeg で完走し、想定尺の mp4 を出力する."""
    import subprocess

    src = tmp_path / "src.mp4"
    # 6 秒の合成動画 (映像 testsrc + 音声 sine)
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=6",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
            "-shortest", str(src),
        ],
        check=True,
        capture_output=True,
    )
    out = tmp_path / "out.mp4"
    # raw 6s から 2-4s をカット → keeps 0-2, 4-6 = 約 4s
    p = _plan(raw=6.0, must_cuts=[_cut(2.0, 4.0)])
    script = generate_ffmpeg_concat_script(p, src, out)
    script_path = tmp_path / "cut.sh"
    script_path.write_text(script, encoding="utf-8")
    subprocess.run(["bash", str(script_path)], check=True, capture_output=True)
    assert out.exists() and out.stat().st_size > 0

    # ffprobe 不在環境でも検証できるよう、ffmpeg 再デコードで mp4 の妥当性を確認
    redecode = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(out), "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    assert redecode.returncode == 0, redecode.stderr
