#!/usr/bin/env bash
# 설계 루프 — 라운드 수가 정책에 고정돼 있다(기본 2회).
#   매 라운드: 설계를 쓰거나 고친다 → SPEC 항목 반영 여부를 grep 으로 검사
# 수렴을 기다리지 않는다. 정해진 횟수를 돌고 결과를 그대로 보고한다.
set -uo pipefail
P="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
. "$P/bin/state.sh"
for d in jq claude; do command -v $d >/dev/null 2>&1 || { echo "의존성 없음: $d" >&2; exit 3; }; done

N=$(budget design_rounds)
MARGS=$(model_args)
IDEA=$(st_get idea)

for r in $(seq 1 "$N"); do
  echo "  ── 설계 라운드 $r/$N ──"
  if [ "$r" -eq 1 ]; then
    if [ "$(st_mode)" = "design" ]; then
      TASK="SPEC.md 를 읽고 하이레벨 시스템 설계 문서 DESIGN.md 를 새로 작성해라.
구성: 아키텍처 개요 · 모듈 상세 설계(책임·내부 구조 방향) · 모듈 간 인터페이스와 계약 ·
      데이터 흐름 · 운영·오류 처리 방침 · 스펙 요구사항 대응표 · ★하위 프로젝트 분해★.
★ 스펙 요구사항 대응표: SPEC 의 모든 ID(M·F 등)를 표로 옮기고 어느 설계 절이 다루는지 적어라.
★ 마지막 절 제목은 정확히 「## 하위 프로젝트 분해」 로 하고, 각 하위 프로젝트를
   mvp-builder 개별 실행 한 번의 입력이 되도록 표로 적어라 —
   행마다: 하위 프로젝트 이름 · 담당 모듈/기능 ID 목록 · 의존하는 하위 프로젝트 ·
   그리고 「idea 한 줄」(그대로 /mvp-builder:start 에 넣을 수 있는 완결된 한국어 문장).
   SPEC 의 모든 ID 가 정확히 하나 이상의 하위 프로젝트에 배정돼야 한다."
    else
      TASK="SPEC.md 를 읽고 DESIGN.md 를 새로 작성해라.
구성: 아키텍처 개요 · 모듈 분해와 책임 · 모듈 간 인터페이스 · 데이터 모델 ·
      오류 처리와 종료 코드 · 테스트 전략 · 스펙 요구사항 대응표.
★ 마지막 절에 SPEC 의 모든 요구사항 ID 를 표로 옮기고 각 ID 를 어느 모듈이 담당하는지 적어라."
    fi
  else
    MISS=$(jq -r '.missingIds // ""' .mvp/design-check.json 2>/dev/null)
    TASK="DESIGN.md 가 SPEC.md 의 다음 요구사항을 다루지 않는다: ${MISS:-(검사 결과 없음)}
DESIGN.md 를 고쳐 이 항목들을 반영해라. 이미 반영된 부분은 건드리지 마라.
요구사항 대응표에도 추가해라."
  fi

  DSK="design"; [ "$(st_mode)" = "design" ] && DSK="design-highlevel"
  claude -p $MARGS --output-format json \
    --append-system-prompt "$(skill_prompt "$DSK")" \
    --settings '{"permissions":{"deny":["Write(./src/**)","Edit(./src/**)","Write(./SPEC.md)","Edit(./SPEC.md)"]}}' \
    "만들려는 것: $IDEA

$TASK

규칙: SPEC.md 는 계약이며 수정할 수 없다. src/ 도 아직 만들지 않는다. DESIGN.md 만 쓴다." \
    </dev/null > ".mvp/design-r$r.json" 2>&1 || true

  "$P/bin/design-check.sh" .mvp/design-check.json || true
  cp .mvp/design-check.json ".mvp/design-check-r$r.json"
  st_setn "rounds.design_r$r" "$(jq -c . .mvp/design-check.json)"
done

cov=$(jq -r .coverage .mvp/design-check.json 2>/dev/null || echo 0)
st_log "design_loop_done rounds=$N coverage=$cov"
echo "  설계 루프 종료 — $N 라운드 고정, 최종 반영률 ${cov}%"
