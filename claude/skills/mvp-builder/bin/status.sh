#!/usr/bin/env bash
set -uo pipefail
P="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
. "$P/bin/state.sh"
[ -f .mvp/state.json ] || { echo "파이프라인이 시작되지 않았습니다."; exit 0; }
echo "만들려는 것 : $(st_get idea)"
echo "현재 단계   : $(st_get phase)"
echo "프로필      : $(st_profile)"
echo "모드        : $(st_mode)"
echo "스킬        : $(st_skills)"
echo
echo "경로:"
if [ "$(st_mode)" = "design" ]; then
  PATH_STATES="spec_running spec_pending_approval design_running design_pending_approval designed"
else
  PATH_STATES="spec_running spec_pending_approval design_running design_pending_approval build_running built"
fi
for p in $PATH_STATES; do
  cur=$(st_get phase); [ "$p" = "$cur" ] && echo "  ▶ $p  ← 지금" || echo "    $p"
done
echo
echo "라운드 기록:"; jq -r '.rounds | to_entries[] | "  \(.key)  \(.value|tostring)"' .mvp/state.json 2>/dev/null
echo
echo "이력:"; jq -r '.history[]? | "  \(.)"' .mvp/state.json 2>/dev/null
