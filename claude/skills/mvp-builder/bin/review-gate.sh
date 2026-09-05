#!/usr/bin/env bash
# 설계 리뷰 게이트 v3 — 원장 기반.
#   라운드 1  전체 리뷰: 문서 전체 → 발견 전부 → 코드가 ID 발급해 원장 기록
#   라운드 2+ 델타 리뷰: 원장 요약 + 수정 diff → 해소 판정·신규만 보고
# 판정 숫자(열린 must)는 원장에서 코드가 센다. 모델은 원장을 직접 쓰지 못한다.
# 종료 코드: 0 열린 must 없음 / 1 있음 / 3 판정 불가(산출물 없음·비JSON·검증 위반)
set -uo pipefail
P="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
. "$P/bin/state.sh"
. "$P/bin/ledger.sh"
OUT="${1:-.mvp/review.json}"; ROUND="${2:-1}"
mkdir -p "$(dirname "$OUT")"
for d in jq claude; do command -v $d >/dev/null 2>&1 || { echo "의존성 없음: $d" >&2; exit 3; }; done

SEV=$(awk -F'\t' 'NR>1{printf "  %s — %s\n", $1, $2}' "$P/policy/severity.tsv")
MARGS=$(model_args)
DENY='{"permissions":{"deny":["Write(./DESIGN.md)","Edit(./DESIGN.md)","Write(./SPEC.md)","Edit(./SPEC.md)","Write(./src/**)","Edit(./src/**)","Write(./.mvp/**)","Edit(./.mvp/**)","Bash"]}}'
rm -f REVIEW.json
RAW=".mvp/review-raw-r$ROUND.json"   # 라운드별 보존 — 덮어쓰지 않는다 (v2 L6 수정)

# v4.2: 모드는 라운드 번호가 아니라 원장으로 정한다. 원장에 발견이 이미 있으면(설계 반려 후 재진입)
#   첫 라운드라도 델타 — 열린 must 를 재판정하고 바뀐 부분만 본다. 전체 리뷰를 다시 하면
#   기존 must 는 영원히 열린 채 새 발견만 쌓인다(step1 실물).
MODE="full"
if [ -f "$LG" ] && [ "$(jq -s '[.[]|select(.ev=="found")]|length' "$LG" 2>/dev/null || echo 0)" -gt 0 ]; then MODE="delta"; fi
[ -f .mvp/design-diff-latest.txt ] || MODE="full"   # 델타는 diff 가 있어야 한다
echo "  리뷰 모드: $MODE"

if [ "$MODE" = "full" ]; then
  # ── 전체 리뷰 (v2 와 동일 스키마) ──────────────────────────
  claude -p $MARGS --output-format json --settings "$DENY" \
    --append-system-prompt "$(skill_prompt review)" \
    "DESIGN.md 를 리뷰해라. SPEC.md 가 계약이다. 아직 코드는 없다. 설계만 본다.

발견마다 심각도를 다음 기준으로 정확히 하나 붙여라.
$SEV

결과를 프로젝트 루트 REVIEW.json 에 이 형식으로 저장해라. 승인을 묻지 말고 바로 저장해라.
{\"findings\":[{\"severity\":\"must|should|nit\",\"where\":\"DESIGN.md 의 절\",
  \"summary\":\"한 문장\",\"why\":\"왜 그 등급인지\",\"fix\":\"무엇을 바꿔야 하는지\"}]}

- DESIGN.md·SPEC.md 는 권한으로 쓰기가 차단돼 있다. 읽고 판정만 한다.
- 근거 없이 must 를 붙이지 마라." \
    </dev/null > "$RAW" 2>&1 || true
else
  # ── 델타 리뷰 — 전체 재독 없음. 원장 요약 + diff 만 ────────
  BRIEF=$(lg_brief)
  claude -p $MARGS --output-format json --settings "$DENY" \
    "설계 리뷰의 델타 라운드다. 전체 재리뷰를 하지 마라.

$BRIEF

직전 수정이 바꾼 부분: .mvp/design-diff-latest.txt 를 읽어라.
맥락이 더 필요할 때만 DESIGN.md 의 해당 절이나 $LG 를 읽어라.

판정할 것은 두 가지뿐이다.
1. 위의 열린 must 각각이 이번 수정으로 해소됐는가
2. 이번 수정이 새로 만든 문제, 또는 바뀐 부분에서만 보이는 신규 발견 (심각도 기준: 아래)
$SEV

결과를 프로젝트 루트 REVIEW.json 에 이 형식으로 저장해라. 다른 출력은 하지 마라.
{\"resolved\":[\"L-001\"],
 \"unresolved\":[{\"id\":\"L-002\",\"note\":\"왜 아직 해소가 아닌가\"}],
 \"new\":[{\"severity\":\"must|should|nit\",\"where\":\"DESIGN.md 의 절\",
   \"summary\":\"한 문장\",\"why\":\"왜 그 등급인지\",\"fix\":\"무엇을 바꿔야 하는지\"}]}

- 알려진 발견을 new 로 다시 보고하지 마라.
- DESIGN.md·SPEC.md·.mvp/ 는 권한으로 쓰기가 차단돼 있다. 읽고 판정만 한다." \
    </dev/null > "$RAW" 2>&1 || true
fi

# ── 산출물 검증 ──────────────────────────────────────────────
[ -f REVIEW.json ] || { echo "리뷰 결과 파일이 없다" >&2
  printf '{"verdict":"undetermined","reason":"no_review_file"}\n' > "$OUT"; exit 3; }
jq -e . REVIEW.json >/dev/null 2>&1 || { echo "리뷰 결과가 JSON 이 아니다" >&2
  printf '{"verdict":"undetermined","reason":"unparsable"}\n' > "$OUT"; exit 3; }

# ── 원장 반영 — append 는 코드만, 검증 위반은 판정 불가(3) ────
fail3() { printf '{"verdict":"undetermined","reason":"%s"}\n' "$1" > "$OUT"; exit 3; }

if [ "$MODE" = "full" ] || ! jq -e 'has("resolved")' REVIEW.json >/dev/null 2>&1; then
  # 전체 모드: findings 전부 등록
  jq -e '.findings|type=="array"' REVIEW.json >/dev/null 2>&1 || fail3 "no_findings_array"
  while IFS= read -r f; do
    id=$(lg_next_id)
    ev=$(echo "$f" | jq -c --arg id "$id" --argjson r "$ROUND" \
      '{ev:"found", id:$id, r:$r, by:"reviewer",
        sev:.severity, where:(.where//""), title:(.summary//""),
        why:(.why//""), fix:(.fix//"")}')
    lg_append "$ev" || fail3 "ledger_reject_found"
  done < <(jq -c '.findings[]' REVIEW.json)
else
  # 델타 모드: resolved / unresolved / new
  while IFS= read -r id; do
    lg_append "{\"ev\":\"resolved\",\"id\":\"$id\",\"r\":$ROUND,\"by\":\"reviewer\"}" \
      || fail3 "ledger_reject_resolved"
  done < <(jq -r '.resolved[]? // empty' REVIEW.json)
  while IFS= read -r u; do
    id=$(echo "$u" | jq -r .id); note=$(echo "$u" | jq -c '.note // ""')
    lg_append "{\"ev\":\"reopened\",\"id\":\"$id\",\"r\":$ROUND,\"by\":\"reviewer\",\"note\":$note}" \
      || fail3 "ledger_reject_unresolved"
  done < <(jq -c '.unresolved[]? // empty' REVIEW.json)
  while IFS= read -r f; do
    id=$(lg_next_id)
    ev=$(echo "$f" | jq -c --arg id "$id" --argjson r "$ROUND" \
      '{ev:"found", id:$id, r:$r, by:"reviewer",
        sev:.severity, where:(.where//""), title:(.summary//""),
        why:(.why//""), fix:(.fix//"")}')
    lg_append "$ev" || fail3 "ledger_reject_new"
  done < <(jq -c '.new[]? // empty' REVIEW.json)
fi
mv REVIEW.json ".mvp/review-r$ROUND-findings.json"

# ── 판정 — 원장에서 코드가 센다 ─────────────────────────────
open=$(lg_open_must_ids)
lg_state | jq --arg open "$open" --argjson r "$ROUND" \
  '{round:$r, openMustIds:$open,
    openMust:[.[]|select(.state=="open" and .sev=="must")]|length,
    resolved:[.[]|select(.state=="resolved")]|length,
    openShould:[.[]|select(.state=="open" and .sev=="should")]|length,
    openNit:[.[]|select(.state=="open" and .sev=="nit")]|length}' > "$OUT"
echo "  $(lg_counts)"
[ -z "$open" ] && exit 0 || exit 1
