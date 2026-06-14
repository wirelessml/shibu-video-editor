"""shibu-edit CLI: Claude API ベース受講生インタビュー編集パイプラインのコマンドライン UI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .chapters import render_chapters, render_description, render_tags, render_title
from .cuts import (
    compute_keep_segments,
    generate_ffmpeg_concat_script,
    write_keep_segments_csv,
)
from .plan import EditingPlan, generate_plan
from .transcribe import (
    extract_audio_with_ffmpeg,
    load_transcript,
    transcribe_with_elevenlabs,
    transcribe_with_whisper,
)

app = typer.Typer(
    add_completion=False,
    help="Claude API ベース 受講生インタビュー動画 編集パイプライン",
    rich_markup_mode="rich",
)
console = Console()


def _probe_duration_seconds(video: Path) -> float:
    """ffprobe で動画長を取得."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def _transcribe_video(
    video: Path,
    output: Path,
    *,
    backend: str = "whisper",
    model: str = "large-v3",
) -> int:
    """動画 → word-level transcript JSON を書き出す純関数.

    CLI コマンド (`transcribe`) と一括実行 (`pipeline`) で共有する。
    pipeline から typer.Context 経由で呼ぶ旧実装は Typer/Click で壊れて
    いたため、関数共有に切り出した (Codex review #1)。返り値は word 数。
    """
    audio_tmp = video.with_suffix(".tmp.wav")
    console.print(f"[cyan]🎙️  音声抽出中: {video.name} → {audio_tmp.name}[/cyan]")
    extract_audio_with_ffmpeg(video, audio_tmp)

    try:
        if backend == "whisper":
            console.print(f"[cyan]🤖 Whisper {model} で起こし中...[/cyan]")
            words = transcribe_with_whisper(audio_tmp, model=model)
        elif backend == "elevenlabs":
            api_key = os.environ.get("ELEVENLABS_API_KEY")
            if not api_key:
                console.print("[red]ELEVENLABS_API_KEY 環境変数を設定してください。[/red]")
                raise typer.Exit(1)
            console.print("[cyan]🤖 ElevenLabs Scribe で起こし中...[/cyan]")
            words = transcribe_with_elevenlabs(audio_tmp, api_key=api_key)
        else:
            console.print(f"[red]未知のバックエンド: {backend}[/red]")
            raise typer.Exit(1)
    finally:
        if audio_tmp.exists():
            audio_tmp.unlink()

    output.write_text(
        json.dumps({"words": words}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    console.print(f"[green]✅ 完了: {len(words)} words → {output}[/green]")
    return len(words)


@app.command()
def transcribe(
    video: Path = typer.Argument(..., help="動画ファイル (.mp4 等)", exists=True),
    output: Path = typer.Option(
        ..., "--output", "-o", help="出力 JSON パス (word-level timestamp)"
    ),
    backend: str = typer.Option(
        "whisper", "--backend", "-b", help="whisper / elevenlabs"
    ),
    model: str = typer.Option("large-v3", "--model", "-m", help="Whisper モデル名"),
) -> None:
    """動画 → word-level timestamp 起こし JSON (manual §6.1 Step 1, §6.2)."""
    _transcribe_video(video, output, backend=backend, model=model)


@app.command()
def plan(
    transcript: Path = typer.Argument(..., help="word-level transcript JSON", exists=True),
    output: Path = typer.Option(..., "--output", "-o", help="出力プラン JSON"),
    nickname: str = typer.Option(..., "--nickname", "-n", help="受講生ニックネーム"),
    profile: str = typer.Option(..., "--profile", "-p", help="プロフィール (例: '33歳 実家暮らし')"),
    cohort: int = typer.Option(..., "--cohort", "-c", help="第 N 期"),
    raw_duration: Optional[float] = typer.Option(
        None, "--raw-duration", help="動画尺 (秒)。省略時は ffprobe で自動取得"
    ),
    video: Optional[Path] = typer.Option(
        None, "--video", help="raw 動画 (raw-duration 自動取得用)", exists=True
    ),
    target_min: int = typer.Option(28 * 60, "--target-min", help="想定出力尺の下限 (秒)"),
    target_max: int = typer.Option(32 * 60, "--target-max", help="想定出力尺の上限 (秒)"),
    filming_mode: str = typer.Option(
        "オンライン (ZOOM 越し + 受講生自宅映像)",
        "--filming-mode",
        help="撮影形式",
    ),
    user_notes: str = typer.Option("なし", "--notes", help="ユーザーから AI への補足"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="詳細ログ表示"),
    summary: Optional[Path] = typer.Option(
        None, "--summary", help="サマリー markdown を別ファイルに書き出す"
    ),
) -> None:
    """word-level transcript → 4 階層フレーム編集計画 (manual §6.1 Step 2, §6.3)."""
    words = load_transcript(transcript)

    if raw_duration is None:
        if video is None:
            # transcript の最終 word の end_ms から推定
            if not words:
                console.print("[red]raw_duration を指定するか --video を渡してください[/red]")
                raise typer.Exit(1)
            raw_duration = words[-1]["end_ms"] / 1000.0
        else:
            raw_duration = _probe_duration_seconds(video)

    console.print(f"[bold]📝 編集計画生成: {nickname}さん 第 {cohort} 期[/bold]")
    console.print(f"   raw 動画長: {int(raw_duration // 60)}:{int(raw_duration % 60):02d}")
    console.print(f"   想定出力: {target_min // 60}:{target_min % 60:02d} 〜 {target_max // 60}:{target_max % 60:02d}")

    plan_obj = generate_plan(
        transcript=words,
        nickname=nickname,
        profile=profile,
        cohort_number=cohort,
        raw_duration_seconds=raw_duration,
        target_min_seconds=target_min,
        target_max_seconds=target_max,
        filming_mode=filming_mode,
        user_notes=user_notes,
        verbose=verbose,
    )

    output.write_text(
        plan_obj.model_dump_json(indent=2, exclude_none=True),
        encoding="utf-8",
    )

    if summary is not None:
        summary.write_text(plan_obj.summary_markdown, encoding="utf-8")
        console.print(f"[green]✅ サマリー: {summary}[/green]")

    _print_plan_summary(plan_obj)
    console.print(f"[green]✅ 計画書: {output}[/green]")


def _print_plan_summary(plan: EditingPlan) -> None:
    """編集計画の主要数値を表示."""
    table = Table(title="編集計画サマリー", show_header=True)
    table.add_column("項目", style="cyan")
    table.add_column("値", style="green")

    table.add_row("出演", plan.video.cast)
    table.add_row(
        "raw 尺",
        f"{int(plan.video.raw_duration_seconds // 60)}:{int(plan.video.raw_duration_seconds % 60):02d}",
    )
    table.add_row(
        "想定尺",
        f"{int(plan.video.estimated_output_seconds_min // 60)}:{int(plan.video.estimated_output_seconds_min % 60):02d} 〜 "
        f"{int(plan.video.estimated_output_seconds_max // 60)}:{int(plan.video.estimated_output_seconds_max % 60):02d}",
    )
    table.add_row("セクション数", str(len(plan.sections)))
    table.add_row("必須カット", str(len(plan.must_cuts)))
    table.add_row("テンポ調整 (要承認)", str(len(plan.tempo_adjustments)))
    table.add_row("触らない範囲", str(len(plan.do_not_touch)))
    table.add_row("インタビュー質問", f"{len(plan.interview_questions)} / 8")
    table.add_row("チャプター", f"{len(plan.chapters_for_description)} / 14")

    console.print(table)


@app.command()
def cuts(
    plan_path: Path = typer.Argument(..., help="編集計画 JSON", exists=True),
    video: Path = typer.Argument(..., help="raw 動画", exists=True),
    output_video: Path = typer.Option(..., "--output", "-o", help="出力動画パス"),
    apply_tempo: bool = typer.Option(
        False, "--apply-tempo", help="テンポ調整 (任意・要相談) も適用"
    ),
    script_only: bool = typer.Option(
        False, "--script-only", help="ffmpeg スクリプトを書き出すだけで実行しない"
    ),
    csv_path: Optional[Path] = typer.Option(
        None, "--csv", help="残す範囲を CSV でも出力 (DaVinci Resolve 取り込み用)"
    ),
) -> None:
    """編集計画 + raw 動画 → ffmpeg カット & レンダー (manual §6.1 Step 4-5)."""
    plan_obj = EditingPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    keeps = compute_keep_segments(plan_obj, apply_tempo_adjustments=apply_tempo)
    total_kept = sum(e - s for s, e in keeps)

    console.print("[bold]✂️  カット生成[/bold]")
    console.print(f"   残す範囲: {len(keeps)} セグメント、合計 {int(total_kept // 60)}:{int(total_kept % 60):02d}")
    console.print(f"   テンポ調整: {'適用' if apply_tempo else '未適用 (--apply-tempo で適用)'}")

    if csv_path is not None:
        write_keep_segments_csv(plan_obj, csv_path, apply_tempo_adjustments=apply_tempo)
        console.print(f"[green]✅ CSV: {csv_path}[/green]")

    script = generate_ffmpeg_concat_script(
        plan_obj, video, output_video, apply_tempo_adjustments=apply_tempo
    )
    script_path = output_video.with_suffix(".ffmpeg.sh")
    script_path.write_text(script, encoding="utf-8")
    script_path.chmod(0o755)
    console.print(f"[green]✅ ffmpeg スクリプト: {script_path}[/green]")

    if script_only:
        console.print("[yellow]--script-only: スクリプトのみ生成、レンダーはスキップ[/yellow]")
        return

    console.print(f"[cyan]🎬 ffmpeg でレンダー中: {output_video}[/cyan]")
    subprocess.run(["bash", str(script_path)], check=True)
    console.print(f"[green]✅ 完了: {output_video}[/green]")


@app.command()
def metadata(
    plan_path: Path = typer.Argument(..., help="編集計画 JSON", exists=True),
    nickname: str = typer.Option(..., "--nickname", "-n"),
    age: str = typer.Option(..., "--age"),
    layout: str = typer.Option(..., "--layout", help="例: 1LDK, 4LDK"),
    living_style: str = typer.Option(..., "--living", help="例: '1人暮らし'"),
    transition_1: Optional[str] = typer.Option(None, "--transition-1", help="タイトル数値 1 (例: '不用品が26万円')"),
    transition_2: Optional[str] = typer.Option(None, "--transition-2", help="タイトル数値 2 (例: '家賃も半額に')"),
    redacted: bool = typer.Option(
        False, "--redacted", help="削除依頼後の匿名化フォーマット"
    ),
    output_dir: Path = typer.Option(
        Path("."), "--output-dir", "-o", help="title/description/tags の出力ディレクトリ"
    ),
) -> None:
    """編集計画から YouTube メタデータ (タイトル / description / タグ) 生成 (manual §3.3-3.6)."""
    plan_obj = EditingPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)

    description = render_description(
        nickname=nickname,
        age=age,
        layout=layout,
        living_style=living_style,
        plan=plan_obj,
        redacted=redacted,
    )
    (output_dir / "description.txt").write_text(description, encoding="utf-8")
    console.print(f"[green]✅ description: {output_dir / 'description.txt'}[/green]")

    if transition_1 and transition_2:
        title = render_title(transition_1, transition_2, nickname)
        (output_dir / "title.txt").write_text(title, encoding="utf-8")
        console.print(f"[green]✅ title: {output_dir / 'title.txt'}[/green]")
        console.print(f"   {title}")

    tags = render_tags()
    (output_dir / "tags.txt").write_text(", ".join(tags), encoding="utf-8")
    console.print(f"[green]✅ tags ({len(tags)}): {output_dir / 'tags.txt'}[/green]")

    chapters = render_chapters(plan_obj.chapters_for_description)
    (output_dir / "chapters.txt").write_text(chapters, encoding="utf-8")
    console.print(f"[green]✅ chapters: {output_dir / 'chapters.txt'}[/green]")


@app.command()
def pipeline(
    video: Path = typer.Argument(..., help="raw 動画", exists=True),
    nickname: str = typer.Option(..., "--nickname", "-n"),
    profile: str = typer.Option(..., "--profile", "-p"),
    cohort: int = typer.Option(..., "--cohort", "-c"),
    output_dir: Path = typer.Option(Path("."), "--output-dir", "-o"),
    target_min: int = typer.Option(28 * 60, "--target-min"),
    target_max: int = typer.Option(32 * 60, "--target-max"),
    transcript: Optional[Path] = typer.Option(
        None, "--transcript", help="既存 transcript JSON (省略時は Whisper で生成)"
    ),
    apply_tempo: bool = typer.Option(False, "--apply-tempo"),
    script_only: bool = typer.Option(False, "--script-only"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """raw 動画 → 完成動画 + メタデータ。フル編集ワークフローを 1 コマンドで実行."""
    output_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = transcript or (output_dir / "transcript.json")
    plan_path = output_dir / "plan.json"
    summary_path = output_dir / "plan.md"
    output_video = output_dir / f"{nickname}-cut.mp4"

    if transcript is None:
        console.print("[bold]Step 1/4: 文字起こし[/bold]")
        _transcribe_video(
            video,
            transcript_path,
            backend="whisper",
            model="large-v3",
        )
    else:
        console.print(f"[bold]Step 1/4: 文字起こし (既存): {transcript_path}[/bold]")

    console.print("[bold]Step 2/4: 編集計画生成[/bold]")
    raw_duration = _probe_duration_seconds(video)
    plan_obj = generate_plan(
        transcript=load_transcript(transcript_path),
        nickname=nickname,
        profile=profile,
        cohort_number=cohort,
        raw_duration_seconds=raw_duration,
        target_min_seconds=target_min,
        target_max_seconds=target_max,
        verbose=verbose,
    )
    plan_path.write_text(plan_obj.model_dump_json(indent=2), encoding="utf-8")
    summary_path.write_text(plan_obj.summary_markdown, encoding="utf-8")
    _print_plan_summary(plan_obj)

    console.print("[bold]Step 3/4: カット & レンダー[/bold]")
    script = generate_ffmpeg_concat_script(
        plan_obj, video, output_video, apply_tempo_adjustments=apply_tempo
    )
    script_path = output_video.with_suffix(".ffmpeg.sh")
    script_path.write_text(script, encoding="utf-8")
    script_path.chmod(0o755)

    if script_only:
        console.print(f"[yellow]--script-only: {script_path} を生成、レンダー省略[/yellow]")
    else:
        subprocess.run(["bash", str(script_path)], check=True)
        console.print(f"[green]✅ 動画: {output_video}[/green]")

    console.print("[bold]Step 4/4: メタデータ生成 (description / tags / chapters)[/bold]")
    chapters_path = output_dir / "chapters.txt"
    chapters_path.write_text(render_chapters(plan_obj.chapters_for_description), encoding="utf-8")
    tags_path = output_dir / "tags.txt"
    tags_path.write_text(", ".join(render_tags()), encoding="utf-8")
    console.print(f"[green]✅ メタデータ: {output_dir}[/green]")

    console.print("\n[bold green]🎉 パイプライン完了[/bold green]")
    console.print("最終承認: モザイク漏れ二重確認 → 運営者最終承認 → 公開")


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
