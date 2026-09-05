#!/usr/bin/env bash
set -uo pipefail
P="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
. "$P/bin/state.sh"
cur=$(st_get phase)
case "$cur" in
  spec_pending_approval)   st_set phase "design_running"; st_log "spec_approved"
                           exec "$P/bin/phase-design.sh" ;;
  design_pending_approval)
    if [ "$(st_mode)" = "design" ]; then
      # v2: design 모드의 종결 게이트 — 분해 산출물이 완전해야 designed 가 된다
      "$P/bin/decompose-check.sh" .mvp/decompose-check.json; dc=$?
      if [ "$dc" -ne 0 ]; then
        echo "  ✖ 하위 프로젝트 분해 게이트 미통과 — 승인할 수 없습니다." >&2
        echo "    /mvp-builder:reject <사유> 로 반려해 분해 절을 고치게 하세요." >&2
        exit 1
      fi
      st_set phase "designed"; st_log "design_mode_done"
      echo
      echo "  ✅ 하이레벨 설계 완료 — 종료 상태: designed"
      echo "     DESIGN.md 의 「하위 프로젝트 분해」 표가 다음 실행들의 입력이다."
      echo "     각 행의 idea 한 줄을 /mvp-builder:start (또는 v2) 에 넣어 하위 프로젝트를 진행하세요."
    else
      st_set phase "build_running"; st_log "design_approved"
      exec "$P/bin/phase-build.sh"
    fi ;;
  *) echo "지금 단계는 '$cur' 입니다. 승인할 것이 없습니다." >&2; exit 2 ;;
esac
