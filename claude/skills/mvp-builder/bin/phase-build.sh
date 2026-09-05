#!/usr/bin/env bash
# 3단계 — 승인된 설계로 구현한다.
set -uo pipefail
P="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
. "$P/bin/state.sh"
st_require "build_running"
MARGS=$(model_args)

echo "▶ 3단계 — 작업 분해"
# ★ plan 과 build 를 나눈다. plan 스킬은 "읽기 전용, 사람 검토 후 정지"를 지시하므로
#   한 프롬프트에 build 를 같이 넣으면 계획에서 멈춘다.
# v4: 스킬은 prompts/<full|lite>/ 에서 --append-system-prompt 로 붙는다 (외부 플러그인 불필요).
NOWRITE='{"permissions":{"deny":["Write(./SPEC.md)","Edit(./SPEC.md)","Write(./DESIGN.md)","Edit(./DESIGN.md)"]}}'

if [ ! -f tasks/todo.md ]; then
  claude -p $MARGS --output-format json --settings "$NOWRITE" \
    --append-system-prompt "$(skill_prompt plan)" \
    "SPEC.md 와 DESIGN.md 가 승인됐다. DESIGN.md 의 모듈 분해를 따라 tasks/todo.md 를 만들어라.
계층이 아니라 기능 단위로 세로로 자른다. SPEC 의 수용 기준 ID 를 각 작업에 배정해라." \
    </dev/null > .mvp/plan.json 2>&1 || true
fi
[ -f tasks/todo.md ] || { st_set phase "build_failed"; echo "작업 목록이 생성되지 않았습니다." >&2; exit 3; }

echo "▶ 3단계 — 구현"
for round in $(seq 1 "$(budget build_rounds)"); do
  claude -p $MARGS --output-format json --settings "$NOWRITE" \
    --append-system-prompt "$(skill_prompt build)" \
    "tasks/todo.md 의 남은 작업을 위에서부터 실제로 구현해라. 계획만 세우지 말고 파일을 만들어라.
작업마다 실패하는 테스트를 먼저 쓰고(RED) 통과시킨다(GREEN).
SPEC 의 수용 기준 ID 를 테스트 이름이나 주석에 남겨라 — 완료 게이트가 이것을 센다.
끝나면 테스트가 전부 통과하는 상태로 둔다.
SPEC.md 와 DESIGN.md 는 권한으로 쓰기가 차단돼 있다. 계약이다." \
    </dev/null > ".mvp/build-r$round.json" 2>&1 || true

  "$P/bin/build-check.sh" .mvp/build-check.json; bc=$?
  st_setn "rounds.build_r$round" "$(jq -c '{sourceFiles,testExit,missingInTests,contract}' .mvp/build-check.json)"
  [ "$bc" -eq 0 ] && break
  echo "  ── 완료 게이트 미통과 — 라운드 $round 재시도 ──"
done

if [ "${bc:-1}" -eq 0 ]; then
  st_set phase "built"; st_log "build_done"
  echo; echo "  ✅ 구현 완료 — 완료 게이트 통과"
else
  st_set phase "build_incomplete"; st_log "build_incomplete"
  echo; echo "  ⚠ 완료 게이트를 통과하지 못했습니다. 아래를 확인하세요."
  jq -r '"     소스 \(.sourceFiles)개 · 테스트 exit \(.testExit) · 미테스트 ID: \(.missingIds)"' .mvp/build-check.json
fi
echo "  상태:  /mvp-builder:status"
