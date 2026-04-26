"""ZaCijqXrK0k (サンプル動画 37:24) 実走行テストの入力データ生成.

VTT 字幕を word-level JSON に変換し、既知のチャプター構造から
ground-truth な編集計画 JSON を構築する。

API キーが無くても downstream 全ステージ (cuts / metadata / chapters)
の挙動を検証できる。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from shibu_editor.plan import (  # noqa: E402
    Chapter,
    DoNotTouch,
    EditingPlan,
    InterviewQuestion,
    MustCut,
    Section,
    TempoAdjustment,
    TechSettings,
    VideoMetadata,
)


def parse_vtt_to_words(vtt_path: Path) -> list[dict]:
    """VTT 字幕を line-level の "word" JSON に変換 (word-level Whisper 代替)."""
    text = vtt_path.read_text(encoding="utf-8")
    words: list[dict] = []
    seen_phrases: set[str] = set()
    blocks = text.split("\n\n")
    ts_re = re.compile(r"(\d+):(\d+):(\d+)\.(\d+)\s*-->\s*(\d+):(\d+):(\d+)\.(\d+)")
    for block in blocks:
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        ts_match = next((ts_re.search(line) for line in lines if ts_re.search(line)), None)
        if not ts_match:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, ts_match.groups())
        start_ms = ((h1 * 60 + m1) * 60 + s1) * 1000 + ms1
        end_ms = ((h2 * 60 + m2) * 60 + s2) * 1000 + ms2
        # テキスト行 (タイムスタンプ行以外)
        text_lines = [
            re.sub(r"<[^>]+>", "", line)
            for line in lines
            if not ts_re.search(line) and not line.startswith("WEBVTT") and not line.startswith("Kind") and not line.startswith("Language")
        ]
        if not text_lines:
            continue
        phrase = "".join(text_lines).strip()
        if not phrase or phrase in seen_phrases:
            continue
        seen_phrases.add(phrase)
        words.append({"start_ms": start_ms, "end_ms": end_ms, "word": phrase})
    return words


def build_ground_truth_plan() -> EditingPlan:
    """ZaCijqXrK0k のチャプター構造 (description 既知) から正解プランを構築.

    タイムスタンプは公式 chapters 由来。raw 動画長は 37:24 = 2244 秒。
    """
    raw = 2244.0
    # 4 大セクション + 8 問のチャプター (公式 description より)
    chapters_data = [
        ("00:00", "ハイライト", 0.0),
        ("1:37", "実際のコーチング（1日目）", 97.0),
        ("6:05", "実際のコーチング（2日目）", 365.0),
        ("9:33", "実際のコーチング（3日目）", 573.0),
        ("13:19", "ビフォーアフター", 799.0),
        ("13:47", "コーチング受講生インタビュー", 827.0),
        ("14:15", "自己紹介", 855.0),
        ("15:19", "なぜコーチングを購入しようと思ったの？", 919.0),
        ("17:45", "コーチングを受ける前の悩みは？", 1065.0),
        ("20:45", "コーチングを受けての変化は？", 1245.0),
        ("24:49", "オンラインコーチングに対する不安はあった？", 1489.0),
        ("25:26", "コーチングの内容で良かったところは？", 1526.0),
        ("29:41", "とくに頑張ったところは？", 1781.0),
        ("32:42", "視聴者さんへのメッセージ", 1962.0),
    ]
    # 4 大セクション
    sections = [
        Section(name="highlights", start_seconds=0, end_seconds=97, estimated_output_seconds=80, notes="フック (印象的シーン抜粋)"),
        Section(name="coaching_day1", start_seconds=97, end_seconds=365, estimated_output_seconds=240, notes="初対面、状況把握、片付け方針"),
        Section(name="coaching_day2", start_seconds=365, end_seconds=573, estimated_output_seconds=180, notes="実作業、しぶ指導"),
        Section(name="coaching_day3", start_seconds=573, end_seconds=799, estimated_output_seconds=200, notes="仕上げ、結果確認"),
        Section(name="before_after", start_seconds=799, end_seconds=827, estimated_output_seconds=28, notes="視覚的対比"),
        Section(name="interview", start_seconds=827, end_seconds=raw, estimated_output_seconds=1380, notes="質問 8 問"),
    ]
    # インタビュー 8 問
    interview = [
        InterviewQuestion(n=1, title="自己紹介", start_seconds=855, end_seconds=919, preserve=False),
        InterviewQuestion(n=2, title="なぜコーチングを購入しようと思ったの？", start_seconds=919, end_seconds=1065, preserve=False),
        InterviewQuestion(n=3, title="コーチングを受ける前の悩みは？", start_seconds=1065, end_seconds=1245, preserve=False),
        InterviewQuestion(n=4, title="コーチングを受けての変化は？", start_seconds=1245, end_seconds=1489, preserve=True),
        InterviewQuestion(n=5, title="オンラインコーチングに対する不安はあった？", start_seconds=1489, end_seconds=1526, preserve=False),
        InterviewQuestion(n=6, title="コーチングの内容で良かったところは？", start_seconds=1526, end_seconds=1781, preserve=True),
        InterviewQuestion(n=7, title="とくに頑張ったところは？", start_seconds=1781, end_seconds=1962, preserve=False),
        InterviewQuestion(n=8, title="視聴者さんへのメッセージ", start_seconds=1962, end_seconds=raw, preserve=True),
    ]
    # 触らない (Q4 / Q6 / Q8)
    do_not_touch = [
        DoNotTouch(reason="emotional_peak", start_seconds=1245, end_seconds=1489, description="Q4 変化 (核となる成果)"),
        DoNotTouch(reason="emotional_peak", start_seconds=1526, end_seconds=1781, description="Q6 内容で良かったところ (セールス前納得材料)"),
        DoNotTouch(reason="sales_section_q8", start_seconds=1962, end_seconds=raw, description="Q8 視聴者メッセージ (収益化、ノーカット)"),
    ]
    # 想定された必須カット (対象動画は実値不明だが、フォーマット検証用に仮置き)
    must_cuts = [
        MustCut(
            pattern_id="self_edit_directive",
            start_seconds=120.5,
            end_seconds=125.0,
            trigger_text="ちょっとこれすいません、編集でカットしておきます",
            reason="しぶ本人が編集指示した雑談 (推定箇所)",
        ),
        MustCut(
            pattern_id="silence_with_breath",
            start_seconds=850.0,
            end_seconds=855.0,
            trigger_text="(無音 5 秒)",
            reason="インタビュー直前の無音、短く詰める",
        ),
    ]
    # テンポ調整 (要承認)
    tempo = [
        TempoAdjustment(
            pattern_id="filler_aizuchi",
            start_seconds=950.0,
            end_seconds=970.0,
            action="halve",
            requires_approval=True,
            rationale="「うんうん」相槌が密集、半分カットで流れ改善",
        ),
    ]
    return EditingPlan(
        video=VideoMetadata(
            raw_duration_seconds=raw,
            estimated_output_seconds_min=1680.0,
            estimated_output_seconds_max=1920.0,
            cast="コーチ × 受講生 (削除依頼後匿名化のサンプル)",
        ),
        sections=sections,
        must_cuts=must_cuts,
        tempo_adjustments=tempo,
        do_not_touch=do_not_touch,
        tech_settings=TechSettings(),
        interview_questions=interview,
        chapters_for_description=[Chapter(timestamp=ts, title=t) for ts, t, _ in chapters_data],
        summary_markdown="# Ground truth: ZaCijqXrK0k 編集方針案 (description chapters から再構築)\n\n…",
    )


def main() -> None:
    desktop = Path("/Users/yuika/Desktop")
    vtt = desktop / "yt-ZaCijqXrK0k.ja.vtt"
    out_dir = REPO_ROOT / "tests" / "fixtures"
    out_dir.mkdir(parents=True, exist_ok=True)

    transcript_path = out_dir / "ZaCijqXrK0k_transcript.json"
    plan_path = out_dir / "ZaCijqXrK0k_ground_truth_plan.json"

    print(f"[1/2] VTT → transcript JSON")
    words = parse_vtt_to_words(vtt)
    transcript_path.write_text(
        json.dumps({"words": words}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"   {len(words)} phrase-segments → {transcript_path.name}")

    print(f"[2/2] Ground truth plan (チャプター構造から構築)")
    plan = build_ground_truth_plan()
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    print(f"   sections={len(plan.sections)}, "
          f"questions={len(plan.interview_questions)}, "
          f"chapters={len(plan.chapters_for_description)} "
          f"→ {plan_path.name}")


if __name__ == "__main__":
    main()
