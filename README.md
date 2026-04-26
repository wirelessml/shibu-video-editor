# shibu-video-editor

> ミニマリストしぶ片付けコーチング **受講生インタビュー動画** を Claude API で半自動編集するオープンソース CLI。
> マスター構造リファレンス: [youtu.be/ZaCijqXrK0k](https://youtu.be/ZaCijqXrK0k)（37:24、4 大セクション + 8 問構造の最も透明な公開動画）。

2026-04-26 に Claude Opus 4.7 + adaptive thinking で 6 時間で構築した編集自動化システムを、
他のクリエイター・受講生インタビュー動画編集者が再利用できる形に整理したもの。

## できること

| ステップ | コマンド | 内容 |
|---|---|---|
| 1. 文字起こし | `shibu-edit transcribe` | 動画 → word-level timestamp JSON (Whisper / ElevenLabs Scribe) |
| 2. 計画生成 | `shibu-edit plan` | 起こし → 4 階層編集フレーム計画書 (Claude API + adaptive thinking) |
| 3. カット & レンダー | `shibu-edit cuts` | 計画 → ffmpeg 連結スクリプト → 完成動画 |
| 4. メタデータ | `shibu-edit metadata` | 計画 → description / chapters / title / tags |
| 一括 | `shibu-edit pipeline` | raw 動画 → 完成動画 + メタデータ (1 コマンド) |

## 4 階層編集判断フレーム

マニュアル §5.2 に基づく:

1. **必須カット (5 種)**: 撮り直し / 自己紹介取り直し / 自己編集指示 / つかえ / 無音+鼻すすり → 完全自動
2. **テンポ調整 (3 種)**: 「うんうん」相槌 / 沈黙短縮 / フィラー連続 → 半自動・要しぶレビュー
3. **触らない (3 種)**: 質問順序 / 笑い声・感情ピーク / 視聴者メッセージ (Q8) → ガード
4. **技術設定**: 1280×720 / 25fps / word boundary / 80-120ms padding / 30ms フェード → 完全自動

## 4 大セクション構造

ZaCijqXrK0k から抽出:

```
ハイライト          1:37  ( 4%)
コーチング 1日目    4:28  (12%)
コーチング 2日目    3:28  ( 9%)
コーチング 3日目    3:46  (10%)
ビフォーアフター    0:28  ( 1%)
インタビュー 8 問   23:37  (63%)
```

## インタビュー 8 問 (正規順序)

1. 自己紹介
2. なぜコーチングを購入しようと思ったの？
3. コーチングを受ける前の悩みは？
4. コーチングを受けての変化は？ ← **触らない**
5. オンラインコーチングに対する不安はあった？
6. コーチングの内容で良かったところは？ ← **触らない**
7. とくに頑張ったところは？
8. 視聴者さんへのメッセージ ← **触らない (セールス・ノーカット)**

## インストール

```bash
cd shibu-video-editor
pip install -e .

# 文字起こしまで使うなら
pip install -e '.[all]'

# 環境変数
export ANTHROPIC_API_KEY=sk-ant-...
export ELEVENLABS_API_KEY=...  # ElevenLabs Scribe を使う場合のみ
```

## 使用例

### 例 1: 一括パイプライン (raw → 公開準備完了)

```bash
shibu-edit pipeline path/to/raw.mp4 \
  --nickname みかん \
  --profile "33歳 実家暮らし" \
  --cohort 51 \
  --output-dir ./output \
  --target-min 1680 \
  --target-max 1920
```

出力:

```
output/
├── transcript.json       # word-level timestamp 起こし
├── plan.json             # 4 階層フレーム計画 (構造化)
├── plan.md               # 13:47 みかん計画書フォーマット (人間レビュー用)
├── みかん-cut.mp4         # 完成動画
├── みかん-cut.ffmpeg.sh   # ffmpeg スクリプト (再現可能)
├── chapters.txt          # description チャプター 14 行
└── tags.txt              # 公式タグ 11 種
```

### 例 2: 段階実行

```bash
# Step 1: 文字起こし
shibu-edit transcribe raw.mp4 -o transcript.json --backend whisper --model large-v3

# Step 2: 計画生成 (しぶレビュー前にここで止める)
shibu-edit plan transcript.json -o plan.json \
  --nickname みかん \
  --profile "33歳 実家暮らし" \
  --cohort 51 \
  --video raw.mp4 \
  --summary plan.md \
  --verbose

# (しぶがレビュー → 必要なら plan.json 手修正)

# Step 3: カット & レンダー (テンポ調整も適用)
shibu-edit cuts plan.json raw.mp4 -o final.mp4 --apply-tempo --csv keeps.csv

# Step 4: メタデータ生成
shibu-edit metadata plan.json -o ./meta \
  --nickname みかん \
  --age 33 \
  --layout 実家暮らし \
  --living "実家暮らし" \
  --transition-1 "5年片付けられなかった部屋が" \
  --transition-2 "3ヶ月で空になった"
```

## アーキテクチャ

```
shibu_editor/
├── config.py        # マニュアル §3.1 / §5.2 / §3.5 に基づく定数
├── prompts.py       # Claude API システムプロンプト (4 階層フレーム)
├── transcribe.py    # Whisper / ElevenLabs Scribe ラッパー
├── plan.py          # Claude API で 4 階層フレーム計画を生成
├── cuts.py          # 計画 → ffmpeg select / concat スクリプト
├── chapters.py      # description / title / tags 生成
└── cli.py           # Typer ベース CLI
```

## Claude API 使用について

- モデル: **claude-opus-4-7** (`high` effort)
- thinking: **adaptive** (フィラー判定や感情検出など複雑な判断のため)
- 出力: streaming + 大きい max_tokens (64K)
- caching: システムプロンプト (4 階層フレーム + 8 問テンプレ) を `cache_control: ephemeral`
  - 25 本範囲を順次処理する際にキャッシュヒットでコスト削減
- 出力フォーマット: 構造化 JSON (Pydantic 検証)

## 適用範囲

このプログラムは **受講生インタビュー型動画**（4 大セクション + 8 問構造、mono-herashi.studio.site/#plan 掲載のような形式）専用。
チャンネル一般の片付け密着動画・コラボ・解説など **構造の異なる動画** には適さない。

## 削除依頼対応

`metadata --redacted` フラグで匿名化フォーマット (`📣YouTubeに出なくても受講可能！` + ■ 4 項目)
の description を生成可能。受講生から削除依頼が出た場合、本編とチャプターを保持しつつ
タイトル・description だけ匿名化する運用 (ZaCijqXrK0k 事例) に対応。

## プライバシーに関する注記

- 本リポジトリは公開動画の **構造的特徴** （タイムスタンプ・チャプター順序・文字数配分など）のみを参考にしており、特定受講生の発話内容を含む transcript は公開していない
- `tests/fixtures/ZaCijqXrK0k_transcript.json` は `.gitignore` に登録済み（受講生プライバシー保護のため）
- ローカルで transcript を再生成する場合は、yt-dlp で動画字幕を取得してから `python tests/build_ground_truth.py` を実行
- 受講生本人から削除依頼が出ている動画 (タイトル「【削除依頼】」) のコンテンツは尊重し、本リポジトリでは構造情報のみを使用

## 開発・テスト

```bash
pip install -e '.[all]' pytest
pytest tests/
```

API キーなしで実行可能な検証は `tests/VALIDATION_REPORT.md` 参照。

## ライセンス

MIT License — 仲結花 ([wirelessml@gmail.com](mailto:wirelessml@gmail.com)) 著。詳細は [`LICENSE`](LICENSE) 参照。

## 改訂履歴

- **0.1.0 (2026-04-26)**: 初版。マニュアル v2.1 を仕様として全機能実装。ZaCijqXrK0k マスター構造リファレンスから description bit-for-bit 一致を実証。
