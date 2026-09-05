#!/usr/bin/env bash
# 하위 프로젝트 분해 게이트 (v2 · design 모드 전용) — build-check 의 자리에 선다.
#   "설계했다"는 주장이 아니라 분해 산출물을 본다:
#   ① DESIGN.md 에 「하위 프로젝트 분해」 절이 실제로 있는가
#   ② SPEC 의 모든 ID 가 그 절 안에 나타나는가 (모든 모듈·기능이 어느 하위 프로젝트엔가 배정)
#   판정은 grep 이 한다. LLM 이 아니다.
set -uo pipefail
OUT="${1:-.mvp/decompose-check.json}"; mkdir -p "$(dirname "$OUT")"

[ -f SPEC.md ]   || { printf '{"verdict":"undetermined","reason":"no_spec"}\n'   > "$OUT"; exit 3; }
[ -f DESIGN.md ] || { printf '{"verdict":"undetermined","reason":"no_design"}\n' > "$OUT"; exit 3; }

# 분해 절만 잘라낸다 — 「하위 프로젝트 분해」 헤딩부터 다음 같은/상위 레벨 헤딩 전까지
SEC=$(awk '/^#{1,3} .*하위 프로젝트 분해/{f=1; next} f && /^#{1,3} /{exit} f{print}' DESIGN.md)
[ -n "$SEC" ] || { printf '{"verdict":"fail","reason":"no_decompose_section","pass":false}\n' > "$OUT"
                   echo "  🔴 DESIGN.md 에 「하위 프로젝트 분해」 절이 없다"; exit 1; }

ids=$(grep -oE '^\| *\*{0,2}([A-Z][0-9]+)\*{0,2} *\|' SPEC.md | grep -oE '[A-Z][0-9]+' | sort -u)
[ -n "$ids" ] || { printf '{"verdict":"undetermined","reason":"no_ids_in_spec"}\n' > "$OUT"; exit 3; }

total=0; missing=""
for id in $ids; do
  total=$((total+1))
  echo "$SEC" | grep -qE "\b$id\b" || missing="$missing $id"
done
n=$(echo $missing | wc -w | tr -d ' ')
subprojects=$(echo "$SEC" | grep -cE '^\| *[^|: -]' || true)

jq -n --argjson t "$total" --argjson m "$n" --arg ml "${missing# }" --argjson sp "$subprojects" \
  '{specIds:$t, unassigned:$m, unassignedIds:$ml, sectionRows:$sp, pass:($m==0)}' > "$OUT"

echo "  하위 프로젝트 분해 — 스펙 ID ${total}개 중 $((total-n))개 배정, 분해표 행 ${subprojects}행"
[ "$n" -eq 0 ] && { echo "  ✅ 모든 ID 가 하위 프로젝트에 배정됐다"; exit 0; } \
               || { echo "  🔴 미배정 ID: ${missing# }"; exit 1; }
