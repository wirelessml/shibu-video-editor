"""文字起こし (manual §6.1 Step 1)。

ElevenLabs Scribe / Whisper を使って word-level timestamp を生成。
プログラム本体は transcript JSON を受け取るだけなので、ここはオプショナル。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def transcribe_with_whisper(
    audio_path: Path,
    model: str = "large-v3",
    language: str = "ja",
) -> list[dict[str, Any]]:
    """openai-whisper を使った word-level transcription.

    pip install openai-whisper が前提。
    返り値: [{"start_ms": int, "end_ms": int, "word": str}, ...]
    """
    try:
        import whisper  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError(
            "openai-whisper が未インストール。pip install 'takeru-video-editor[transcribe]' を実行してください。"
        ) from e

    model_obj = whisper.load_model(model)
    result = model_obj.transcribe(
        str(audio_path),
        language=language,
        word_timestamps=True,
        verbose=False,
    )

    words: list[dict[str, Any]] = []
    for segment in result.get("segments", []):
        for w in segment.get("words", []):
            words.append(
                {
                    "start_ms": int(w["start"] * 1000),
                    "end_ms": int(w["end"] * 1000),
                    "word": w["word"].strip(),
                }
            )
    return words


def transcribe_with_elevenlabs(
    audio_path: Path,
    api_key: str,
) -> list[dict[str, Any]]:
    """ElevenLabs Scribe API での word-level transcription.

    pip install elevenlabs が前提。
    """
    try:
        from elevenlabs.client import ElevenLabs  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError(
            "elevenlabs SDK が未インストール。pip install 'takeru-video-editor[elevenlabs]' を実行してください。"
        ) from e

    client = ElevenLabs(api_key=api_key)
    with open(audio_path, "rb") as f:
        result = client.speech_to_text.convert(
            file=f,
            model_id="scribe_v1",
            language_code="jpn",
            timestamps_granularity="word",
        )

    words: list[dict[str, Any]] = []
    for w in getattr(result, "words", []):
        words.append(
            {
                "start_ms": int(getattr(w, "start", 0) * 1000),
                "end_ms": int(getattr(w, "end", 0) * 1000),
                "word": getattr(w, "text", "").strip(),
            }
        )
    return words


def extract_audio_with_ffmpeg(video_path: Path, output_path: Path) -> Path:
    """ffmpeg で動画から音声を抽出 (16kHz mono WAV)."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg が PATH に見つかりません。brew install ffmpeg を実行してください。")

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-acodec",
            "pcm_s16le",
            str(output_path),
        ],
        check=True,
        capture_output=True,
    )
    return output_path


def load_transcript(path: Path) -> list[dict[str, Any]]:
    """JSON ファイルから transcript を読み込み."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "words" in data:
        return data["words"]
    if isinstance(data, list):
        return data
    raise ValueError(f"予期しないトランスクリプト形式: {type(data)}")
