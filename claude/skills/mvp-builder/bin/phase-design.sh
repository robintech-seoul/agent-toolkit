#!/usr/bin/env bash
# 2단계 — 설계 루프(고정 N회) → 리뷰 루프(must 0까지) → 승인 대기.
set -uo pipefail
P="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
. "$P/bin/state.sh"
st_require "design_running"

echo "▶ 2단계 설계"
"$P/bin/design-loop.sh"
echo
echo "▶ 2단계 리뷰"
"$P/bin/review-loop.sh"; rl=$?

cov=$(jq -r '.coverage // 0' .mvp/design-check.json 2>/dev/null)
# -findings.json 이 glob 에 섞여 마지막 파일이 잘못 잡히던 것을 고침
must=$(ls -1 .mvp/review-r[0-9]*.json 2>/dev/null | grep -vE 'findings' \
       | sort -V | tail -1 | xargs -r jq -r '.openMust // .must // "?"')   # v4.2: 게이트 산출물 키는 openMust
# v2: design 모드는 승인 전에 분해 게이트 결과를 미리 보여준다 (강제는 approve 가 한다)
if [ "$(st_mode)" = "design" ]; then
  echo
  "$P/bin/decompose-check.sh" .mvp/decompose-check.json || true
fi

st_set phase "design_pending_approval"
st_log "design_phase_done coverage=$cov must=${must:-?} review_exit=$rl"

echo
echo "  설계 반영률 ${cov}%   남은 must ${must:-?}"
# 종료 코드 삼분기(0 달성 / 1 미달 / 3 판정불가) 밖의 값은 실행 실패다. 미달로 뭉뚱그리지 않는다.
case "$rl" in
  0) ;;
  1) echo "  ⚠ 리뷰 루프가 must 0 에 도달하지 못하고 상한에서 멈췄습니다." ;;
  3) echo "  ⚠ 리뷰 판정 불가 — 게이트 산출물을 확인하세요." ;;
  *) echo "  ✖ 리뷰 루프 실행 실패 (exit $rl) — 루프가 돌지 않았습니다. 승인 전에 원인을 확인하세요." ;;
esac
echo
# v4.1 자동 게이트 — 반영률 pass 이고 리뷰 루프가 must 0 으로 끝났을 때만 스스로 승인한다.
# design 모드에서는 approve.sh 가 분해 게이트를 한 번 더 세우므로 여기서 따로 검사하지 않는다.
if [ "$(st_gate)" = "auto" ]; then
  covpass=$(jq -r '.pass // false' .mvp/design-check.json 2>/dev/null)
  if [ "$rl" -eq 0 ] && [ "$covpass" = "true" ]; then
    echo "  ▣ 자동 승인 (gate=auto) — 기계 게이트 통과: 반영률 ${cov}% · must 0 · 리뷰 exit 0"
    st_log "design_auto_gate_pass coverage=$cov"
    exec "$P/bin/approve.sh"
  fi
  echo "  ⚠ 자동 승인 보류 — 기계 게이트 미통과 (반영률 pass=$covpass · 리뷰 exit $rl). 사람 승인 대기로 전환."
  st_log "design_auto_gate_hold coverage=$cov review_exit=$rl"
  echo
fi
echo "  ▣ 사람 승인 대기"
echo "     내용을 확인하세요:  DESIGN.md"
echo "     승인:  /mvp-builder:approve   (구현 시작)"
echo "     반려:  /mvp-builder:reject <고칠 내용>"
