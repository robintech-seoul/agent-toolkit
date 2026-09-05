#!/usr/bin/env bash
# 반려 — 같은 단계를 사유와 함께 다시 돌린다. 앞으로 나아가지 않는다.
set -uo pipefail
P="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
. "$P/bin/state.sh"
MARGS=$(model_args)
REASON="$*"
[ -n "$REASON" ] || { echo "반려 사유를 적어주세요." >&2; exit 2; }
cur=$(st_get phase)
case "$cur" in
  spec_pending_approval)
    st_log "spec_rejected: $REASON"
    claude -p $MARGS --output-format json "SPEC.md 를 다음 지적에 따라 고쳐라. 수용 기준의 ID 체계는 유지해라.

$REASON" </dev/null > .mvp/spec-revise.json 2>&1 || true
    echo "  SPEC.md 를 수정했습니다. 다시 확인 후 /mvp-builder:approve" ;;
  design_pending_approval)
    st_log "design_rejected: $REASON"
    st_set phase "design_running"
    cp DESIGN.md .mvp/design-before-reject   # v4.2: 수정 전 스냅샷 → diff 가 델타 리뷰의 입력
    claude -p $MARGS --output-format json "DESIGN.md 를 다음 지적에 따라 고쳐라. SPEC.md 는 수정하지 마라.

$REASON" </dev/null > .mvp/design-revise.json 2>&1 || true
    diff -u .mvp/design-before-reject DESIGN.md > .mvp/design-diff-latest.txt || true
    exec "$P/bin/phase-design.sh" ;;
  *) echo "지금 단계는 '$cur' 입니다. 반려할 것이 없습니다." >&2; exit 2 ;;
esac
