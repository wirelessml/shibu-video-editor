"""マニュアル §3.1 / §5.2 / §3.5 に基づく定数定義."""

# 動画フォーマット仕様 (manual §3.1)
RESOLUTION = "1280x720"
FPS = 25
WORD_BOUNDARY_PADDING_MS = 100  # 80-120ms range, midpoint
CROSSFADE_MS = 30
CHANNEL_PROFILE = {
    "subtitle_burnin": False,
    "color_grading": False,
    "loudness_normalization": False,
    "bgm_minimal": True,
}

# 4 大セクション尺配分 (manual §1.2、ZaCijqXrK0k 基準)
SECTION_RATIOS = {
    "highlights": 0.04,   # ハイライト
    "coaching": 0.31,     # 実際のコーチング 3 日間
    "before_after": 0.01, # ビフォーアフター
    "interview": 0.63,    # 受講生インタビュー 8 問
}

# インタビュー 8 問 (manual §5、ZaCijqXrK0k チャプターから抽出)
INTERVIEW_QUESTIONS = [
    {
        "n": 1,
        "title": "自己紹介",
        "weight_ratio_ref": 0.046,  # 1:04 / 23:09
        "type": "core",
        "do_not_touch": False,
    },
    {
        "n": 2,
        "title": "なぜコーチングを購入しようと思ったの？",
        "weight_ratio_ref": 0.105,
        "type": "story",
        "do_not_touch": False,
    },
    {
        "n": 3,
        "title": "コーチングを受ける前の悩みは？",
        "weight_ratio_ref": 0.130,
        "type": "story",
        "do_not_touch": False,
    },
    {
        "n": 4,
        "title": "コーチングを受けての変化は？",
        "weight_ratio_ref": 0.176,
        "type": "core_value",
        "do_not_touch": True,
    },
    {
        "n": 5,
        "title": "オンラインコーチングに対する不安はあった？",
        "weight_ratio_ref": 0.027,
        "type": "online_specific",
        "do_not_touch": False,
        "skippable_for_offline": True,
    },
    {
        "n": 6,
        "title": "コーチングの内容で良かったところは？",
        "weight_ratio_ref": 0.184,
        "type": "evaluation",
        "do_not_touch": True,
    },
    {
        "n": 7,
        "title": "とくに頑張ったところは？",
        "weight_ratio_ref": 0.130,
        "type": "effort",
        "do_not_touch": False,
    },
    {
        "n": 8,
        "title": "視聴者さんへのメッセージ",
        "weight_ratio_ref": 0.203,
        "type": "sales",
        "do_not_touch": True,
    },
]

# 必須カット 5 種 (manual §5.2.1)
MUST_CUT_PATTERNS = [
    {
        "id": "retake_name_mistake",
        "trigger_text": ["ごめんなさい、もう一回", "もう 1 回", "もう一度"],
        "description": "撮り直し（名前間違い）",
    },
    {
        "id": "retake_introduction",
        "trigger_text": ["もう一度お願いします", "もう一回お願い", "撮り直し"],
        "description": "自己紹介取り直し",
    },
    {
        "id": "self_edit_directive",
        "trigger_text": [
            "編集でカットしておきます",
            "編集で",
            "ちょっとこれすいません",
            "カットして",
        ],
        "description": "本人の自己編集指示",
    },
    {
        "id": "stutter",
        "trigger_pattern": r"(\S+)、\s*\1、",  # 「して、して、」
        "description": "つかえ（短語反復）",
    },
    {
        "id": "silence_with_breath",
        "min_silence_ms": 5000,
        "non_verbal": ["鼻すすり", "咳払い", "ため息"],
        "description": "無音 + 鼻すすり等のノンバーバル",
    },
]

# テンポ調整 3 種 (manual §5.2.2)
TEMPO_PATTERNS = [
    {
        "id": "filler_aizuchi",
        "trigger_text": ["うんうん", "うん、うん"],
        "duration_ms_max": 1000,
        "duration_ms_min": 300,
        "action": "halve",  # 半分カット
    },
    {
        "id": "long_silence",
        "min_ms": 500,
        "action": "shorten_mechanical",
        "preserve": "natural_pause_within_speech",
    },
    {
        "id": "filler_clusters",
        "trigger_text": ["あの", "えっと", "もう", "なんか"],
        "min_consecutive": 3,
        "action": "tighten_at_clause_boundary",
    },
]

# 触らない 3 種 (manual §5.2.3)
DO_NOT_TOUCH = [
    "question_order",  # 質問 1〜8 の順番
    "emotional_peaks",  # 笑い声・感情ピーク
    "sales_section_q8",  # 視聴者へのメッセージ全長
]

# 想定尺レンジ (manual §3.2、25 本範囲)
DURATION_TARGET_MIN = 28 * 60  # 28:00
DURATION_TARGET_MAX = 32 * 60  # 32:00
DURATION_OBSERVED_RANGE = (21 * 60 + 22, 55 * 60 + 53)  # 21:22 - 55:53
DURATION_OBSERVED_MEDIAN = 42 * 60 + 34
DURATION_OBSERVED_MEAN_AI_ERA = 44 * 60 + 48

# Claude API
MODEL = "claude-opus-4-7"
EFFORT = "high"  # manual の品質要求から high を選択

# description テンプレート (manual §3.4.1)
DESCRIPTION_TEMPLATE = """{nickname}さん/{age}/{layout}/{living_style}

ミニマルライフ・プログラム
https://www.minimal-life-program.com

☑️ミニマリストしぶ本人による3ヶ月の直接指導
☑️しぶ本人へLINEで質問し放題。
☑️しぶ本人と片付けできるグループZOOM(週2回)
☑️モノ・お金・デジタルを整える50の講義を配布
☑️受講生グループチャット(3ヶ月後も無料で継続可能)
☑️受講生だけのオフ会(3ヶ月後も無料で継続可能)

{chapters}"""

# 削除依頼後 description (manual §3.4.2)
DESCRIPTION_REDACTED_TEMPLATE = """📣YouTubeに出なくても受講可能！
コーチングの詳細はこちら
https://mono-herashi.studio.site

■オンラインor対面式の2種で指導
■2日の短期集中コーチングと3ヶ月のアフターサポート
■ミニマリストしぶ本人とLINEし放題
■コーチング受講生のみが入れる限定コミュニティ

{chapters}"""

# タグ (manual §3.6)
DEFAULT_TAGS = [
    "ミニマリスト",
    "持たない暮らし",
    "少ない物で暮らす",
    "片付け",
    "捨てる",
    "捨て活",
    "シンプルライフ",
    "シンプリスト",
    "整理整頓",
    "ルーティン",
    "VLOG",
]

# タイトル定型 (manual §3.3)
TITLE_FORMAT = "【コーチング実績】{transition_1}、{transition_2}「{nickname}」さん"
