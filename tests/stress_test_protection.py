"""do_not_touch 強度検証: 偽の must_cut を Q8 内に注入してもスルーされるか."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from shibu_editor.cuts import compute_keep_segments  # noqa: E402
from shibu_editor.plan import EditingPlan, MustCut  # noqa: E402


def main() -> None:
    plan_path = REPO_ROOT / "tests" / "fixtures" / "ZaCijqXrK0k_ground_truth_plan.json"
    plan = EditingPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))

    # 偽の must_cut 3 種を Q4/Q6/Q8 内に注入 (Claude が誤判定したと仮定)
    plan.must_cuts.extend([
        MustCut(
            pattern_id="silence_with_breath",
            start_seconds=1300.0,  # Q4 内 (1245-1489)
            end_seconds=1310.0,
            trigger_text="(誤判定の無音)",
            reason="保護範囲を踏んでいるので無視されるべき",
        ),
        MustCut(
            pattern_id="stutter",
            start_seconds=1600.0,  # Q6 内 (1526-1781)
            end_seconds=1605.0,
            trigger_text="えっと、えっと",
            reason="保護範囲を踏んでいるので無視されるべき",
        ),
        MustCut(
            pattern_id="self_edit_directive",
            start_seconds=2000.0,  # Q8 内 (1962-2244)
            end_seconds=2020.0,
            trigger_text="(誤った検出)",
            reason="セールスパート、絶対にカット禁止",
        ),
    ])

    keeps = compute_keep_segments(plan, apply_tempo_adjustments=False)

    print(f"keep segments: {len(keeps)}")
    for s, e in keeps:
        print(f"  {s:7.1f} 〜 {e:7.1f}  ({e - s:6.1f}s)")

    # 保護範囲が完全に含まれているか検証
    protected_ranges = [
        ("Q4 (1245-1489)", 1245.0, 1489.0),
        ("Q6 (1526-1781)", 1526.0, 1781.0),
        ("Q8 (1962-2244) — セールス", 1962.0, 2244.0),
    ]
    print()
    print("保護範囲チェック:")
    all_ok = True
    for label, ps, pe in protected_ranges:
        # ps〜pe 全体が keeps のいずれかに含まれているか
        covered = any(s <= ps and e >= pe for s, e in keeps)
        status = "✅ 完全保護" if covered else "❌ 切られた"
        if not covered:
            all_ok = False
        print(f"  {label}: {status}")

    if all_ok:
        print("\n🎉 ストレステスト合格: 偽の must_cut 3 件は全て保護範囲を踏んでいたため無視された")
    else:
        print("\n💥 ストレステスト失敗: 保護範囲が侵害された")
        sys.exit(1)


if __name__ == "__main__":
    main()
