#!/usr/bin/env bash
# 설계 리뷰 루프 v3 — 원장 기반 델타 수렴.
#   1라운드 전체 리뷰 → 원장. 2라운드부터 원장 요약 + 수정 diff 만으로 델타 리뷰.
#   종료  열린 must 0 → 성공 (+ 남은 should/nit 선별 목록 덤프)
#   교착  같은 must ID 집합이 그대로 반복 → "계약을 의심하라" (run1 형 진동)
#   상한  라운드 예산 소진 — 새 발견 스트림 → 선별 목록과 함께 운영자 승계 (run3·4 형)
set -uo pipefail
P="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
. "$P/bin/state.sh"
. "$P/bin/ledger.sh"
for d in jq claude; do command -v $d >/dev/null 2>&1 || { echo "의존성 없음: $d" >&2; exit 3; }; done

MAXA=$(budget review_max_attempts); MAXS=$(budget review_max_stall)
MARGS=$(model_args)

a=0; stall=0; prev_ids="__none__"
while :; do
  a=$((a+1)); echo "  ── 리뷰 라운드 $a ──"
  "$P/bin/review-gate.sh" ".mvp/review-r$a.json" "$a"; rc=$?
  if [ "$rc" -eq 3 ]; then
    st_log "review_undetermined attempt=$a"; echo "  판정 불가 — 게이트를 확인하세요"; exit 3
  fi
  open=$(lg_open_must_ids)
  st_setn "rounds.review_r$a" "$(jq -c '{openMust,resolved,openShould,openNit}' ".mvp/review-r$a.json")"

  # 1) 목표 달성 — 열린 must 없음
  if [ -z "$open" ]; then
    lg_triage > .mvp/triage.md
    st_log "review_loop_success attempt=$a"
    echo "  ✅ 열린 must 0 — 리뷰 루프 종료"
    echo "  남은 should·nit 선별 목록: .mvp/triage.md ($(lg_state | jq '[.[]|select(.sev!="must" and .state=="open")]|length')건) — 고칠 가치를 사람이 고른다"
    exit 0
  fi
  # 2) 교착 — 같은 must ID 집합이 그대로 (개수가 아니라 신원으로 판정)
  if [ "$open" = "$prev_ids" ]; then stall=$((stall+1)); else stall=0; fi
  prev_ids="$open"
  if [ "$stall" -ge "$MAXS" ]; then
    st_log "review_deadlock attempt=$a ids=$open"
    echo "  ⏹ 교착 — 같은 must 가 ${MAXS}라운드째 그대로 남아 있다: $open"
    echo "     수정자가 풀 수 없는 종류일 수 있다 — 계약(SPEC)이 만족 불가능을 요구하는지 의심하라"
    exit 1
  fi
  # 3) 상한 — 라운드 예산 소진 (새 발견이 계속 유입되는 스트림 포함)
  if [ "$a" -ge "$MAXA" ]; then
    lg_triage > .mvp/triage.md
    st_log "review_exhausted attempts open=$open"
    echo "  ⏹ 라운드 상한 — 열린 must: $open"
    echo "     새 발견 스트림일 수 있다. 원장(.mvp/ledger.jsonl)과 선별 목록(.mvp/triage.md)을 보고 운영자가 승계를 결정하라"
    exit 1
  fi

  # ── 수정 — 열린 must 만. 수정 전 스냅샷 → 수정 후 diff (다음 라운드 델타 입력) ──
  detail=$(lg_open_musts)
  cp DESIGN.md ".mvp/design-before-r$a"
  claude -p $MARGS --output-format json \
    --settings '{"permissions":{"deny":["Write(./SPEC.md)","Edit(./SPEC.md)","Write(./src/**)","Edit(./src/**)","Write(./.mvp/**)","Edit(./.mvp/**)"]}}' \
    "설계 리뷰에서 아래 must 가 열려 있다. DESIGN.md 에서 이것만 고쳐라.

$detail

규칙: 위 must 만 고친다. should·nit 는 건드리지 않는다. SPEC.md 는 계약이라 수정할 수 없다.
요구사항 대응표와 「하위 프로젝트 분해」 절을 깨뜨리지 마라." \
    </dev/null > ".mvp/review-fix-r$a.json" 2>&1 || true

  for id in $open; do
    lg_append "{\"ev\":\"claimed\",\"id\":\"$id\",\"r\":$a,\"by\":\"fixer\"}" || true
  done
  diff -u ".mvp/design-before-r$a" DESIGN.md > ".mvp/design-diff-r$a.txt" || true
  cp ".mvp/design-diff-r$a.txt" .mvp/design-diff-latest.txt
  cost=$(jq -r '.total_cost_usd // "?"' ".mvp/review-fix-r$a.json" 2>/dev/null)
  echo "  수정 라운드 종료 (비용 \$${cost})"
done
