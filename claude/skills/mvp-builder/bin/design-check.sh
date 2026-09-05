#!/usr/bin/env bash
# 설계 커버리지 검사 — SPEC.md 의 요구사항 ID 가 DESIGN.md 에 모두 나타나는지 센다.
# 판정은 grep 이 한다. LLM 이 아니다.
set -uo pipefail
OUT="${1:-.mvp/design-check.json}"
mkdir -p "$(dirname "$OUT")"

[ -f SPEC.md ]   || { printf '{"verdict":"undetermined","reason":"no_spec"}\n'   > "$OUT"; exit 3; }
[ -f DESIGN.md ] || { printf '{"verdict":"undetermined","reason":"no_design"}\n' > "$OUT"; exit 3; }

# 요구사항 ID: 표 첫 칸의 대문자+숫자 (A1, B12, R3 ...)
ids=$(grep -oE '^\| *\*{0,2}([A-Z][0-9]+)\*{0,2} *\|' SPEC.md \
      | grep -oE '[A-Z][0-9]+' | sort -u)
[ -n "$ids" ] || { printf '{"verdict":"undetermined","reason":"no_ids_in_spec"}\n' > "$OUT"; exit 3; }

total=0; missing=""
for id in $ids; do
  total=$((total+1))
  grep -qE "\b$id\b" DESIGN.md || missing="$missing $id"
done
n=$(echo $missing | wc -w | tr -d ' ')
covered=$((total-n))
pct=$(( total>0 ? covered*100/total : 0 ))

jq -n --argjson t "$total" --argjson c "$covered" --argjson m "$n" \
      --arg list "${missing# }" --argjson pct "$pct" \
  '{total:$t, covered:$c, missing:$m, missingIds:$list, coverage:$pct, pass:($m==0)}' > "$OUT"

printf '  스펙 항목 %d개 중 %d개 반영 (%d%%)' "$total" "$covered" "$pct"
[ "$n" -eq 0 ] && echo "  ✅" || echo "  🔴 미반영: ${missing# }"
[ "$n" -eq 0 ] && exit 0 || exit 1
