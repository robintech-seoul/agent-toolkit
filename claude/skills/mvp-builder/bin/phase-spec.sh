#!/usr/bin/env bash
# 1단계 — 아이디어에서 SPEC.md 를 만들고 승인 대기 상태로 멈춘다.
set -uo pipefail
P="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
. "$P/bin/state.sh"

# 속도 프로필(--fast/--profile)과 실행 모드(--mode build|design)를 아이디어 앞에 붙인다
PROFILE="standard"; MODE="build"; SKILLS="full"; GATE="human"
# v4.2: 커맨드가 인자 전체를 따옴표 하나로 넘긴다("$ARGUMENTS") — 글롭·괄호·꺾쇠가 셸에서 풀리지 않게.
#   플래그를 가려내기 위해 공백으로만 다시 나눈다(set -f 로 글롭 확장 금지).
if [ $# -eq 1 ]; then set -f; set -- $1; set +f; fi
while [ $# -gt 0 ]; do
  case "$1" in
    --lite)    SKILLS="lite"; shift ;;
    --full)    SKILLS="full"; shift ;;
    --skills)  SKILLS="${2:-full}"; shift 2 ;;
    --fast)    PROFILE="fast"; shift ;;
    --profile) PROFILE="${2:-}"; shift 2 ;;
    --mode)    MODE="${2:-build}"; shift 2 ;;
    --design)  MODE="design"; shift ;;
    --auto-approve) GATE="auto"; shift ;;
    *) break ;;
  esac
done
case "$MODE" in build|design) ;; *) echo "알 수 없는 모드 '$MODE'. 사용 가능: build design" >&2; exit 2 ;; esac
case "$SKILLS" in full|lite) ;; *) echo "알 수 없는 스킬 모드 '$SKILLS'. 사용 가능: full lite" >&2; exit 2 ;; esac
IDEA="$*"
[ -n "$IDEA" ] || { echo "만들려는 것을 알려주세요. 예: /mvp-builder:start 팀 회고를 모으는 웹앱" >&2; exit 2; }
if [ "$PROFILE" != "standard" ] && \
   ! awk -F'\t' -v p="$PROFILE" 'NR>1 && $1==p{f=1} END{exit !f}' "$P/policy/profiles.tsv" 2>/dev/null; then
  echo "알 수 없는 프로필 '$PROFILE'. 사용 가능: standard $(awk -F'\t' 'NR>1{print $1}' "$P/policy/profiles.tsv" 2>/dev/null | sort -u | tr '\n' ' ')" >&2
  exit 2
fi

st_init "$IDEA"
st_set profile "$PROFILE"
st_set mode "$MODE"
st_set skills "$SKILLS"
st_set gate "$GATE"
MARGS=$(model_args)
echo "  스킬: $SKILLS — $([ "$SKILLS" = "lite" ] && echo '단계별 기본 프롬프트 (가벼움)' || echo '내장 agent-skills (양식 강제)')"
[ "$MODE" = "design" ] && echo "  모드: design — 하이레벨 설계까지만 진행하고 하위 프로젝트로 분해한다"
[ "$GATE" = "auto" ] && echo "  게이트: auto — 기계 게이트를 통과한 단계는 스스로 승인한다 (미통과는 사람 대기)"

[ "$PROFILE" = "standard" ] || echo "  프로필: $PROFILE (claude ${MARGS:-기본} · 설계 $(budget design_rounds)라운드 · 리뷰 상한 $(budget review_max_attempts)회)"
echo "▶ 1단계 스펙 작성"
# 모드에 따라 스펙의 고도가 다르다.
#   build  — 수용 기준(테스트 가능한 행동) 표. 구현·완료 게이트가 이 ID 를 센다.
#   design — 모듈·기능 정의 표. 설계 반영률과 하위 프로젝트 분해 게이트가 이 ID 를 센다.
if [ "$MODE" = "design" ]; then
  SPEC_TASK="이것은 큰 시스템의 **하이레벨 설계 전 단계 스펙**이다. 구현 수준 수용 기준을 쓰지 마라.

다음 구성으로 SPEC.md 를 프로젝트 루트에 저장해라.
1. 목표와 성공의 모습 — 시스템이 무엇을 입력받아 무엇을 내놓는가
2. 범위 / 범위 밖
3. ★ 모듈 정의 표 — 각 행의 첫 칸에 M1, M2 같은 **ID**. 모듈명 · 책임 한 문장 · 입력 · 출력
4. ★ 핵심 기능 정의 표 — 각 행의 첫 칸에 F1, F2 같은 **ID**. 기능 · 담당 모듈(M-ID) · 완료를 관측하는 방법
5. 모듈 간 계약 — 모듈 경계를 넘는 데이터·호출의 형태
6. 품질 속성과 제약 — 보안·비용·운영상 제약

★ 모든 표의 ID 는 뒤 단계에서 설계 반영 여부와 하위 프로젝트 분해를 세는 기준이 된다."
else
  SPEC_TASK="요구사항을 확정한 뒤 SPEC.md 를 프로젝트 루트에 저장해라.
★ 수용 기준은 반드시 표로 쓰고 각 행의 첫 칸에 A1, A2, B1 같은 **ID** 를 붙여라.
   이 ID 가 뒤 단계에서 설계 반영 여부를 세는 기준이 된다."
fi
claude -p $MARGS --output-format json \
  --append-system-prompt "$(skill_prompt spec)" \
  --settings '{"permissions":{"deny":["Write(./src/**)","Edit(./src/**)"]}}' \
  "만들려는 것: $IDEA

$SPEC_TASK
승인을 묻지 말고 SPEC.md 를 저장해라. 코드는 아직 만들지 않는다." \
  </dev/null > .mvp/spec.json 2>&1 || true

[ -f SPEC.md ] || { st_set phase "spec_failed"; echo "SPEC.md 가 생성되지 않았습니다." >&2; exit 3; }
n=$(grep -oE '^\| *\*{0,2}[A-Z][0-9]+' SPEC.md | wc -l | tr -d ' ')
st_setn "rounds.spec_ids" "$n"
st_set phase "spec_pending_approval"
st_log "spec_written ids=$n"

echo
echo "  SPEC.md 작성 완료 — 수용 기준 ${n}건"
echo
# v4.1 자동 게이트 — 수용 기준이 1건 이상이면 스스로 승인하고 설계로 넘어간다
if [ "$(st_gate)" = "auto" ]; then
  if [ "$n" -ge 1 ]; then
    echo "  ▣ 자동 승인 (gate=auto) — 기계 게이트 통과: 수용 기준 ${n}건"
    st_log "spec_auto_gate_pass ids=$n"
    exec "$P/bin/approve.sh"
  fi
  echo "  ⚠ 자동 승인 보류 — 수용 기준 ID 가 0건. 사람 승인 대기로 전환."
  st_log "spec_auto_gate_hold ids=$n"
fi
echo "  ▣ 사람 승인 대기"
echo "     내용을 확인하세요:  SPEC.md"
echo "     승인:  /mvp-builder:approve"
echo "     반려:  /mvp-builder:reject <고칠 내용>"
