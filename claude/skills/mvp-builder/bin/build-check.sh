#!/usr/bin/env bash
# 구현 완료 게이트 — "구현했다"는 주장이 아니라 산출물을 본다.
#   ① 소스 파일이 실제로 생겼는가
#   ② 테스트가 실제로 도는가
#   ③ 수용 기준 ID 가 테스트에 옮겨졌는가
#   ④ 계약(SPEC·DESIGN)이 변경되지 않았는가
set -uo pipefail
OUT="${1:-.mvp/build-check.json}"; mkdir -p "$(dirname "$OUT")"

src=$(find . -type f \( -name '*.py' -o -name '*.ts' -o -name '*.js' \) \
      -not -path './.git/*' -not -path './.mvp/*' -not -path './node_modules/*' \
      -not -path './tasks/*' | wc -l | tr -d ' ')

# 테스트 러너 자동 판별
runner=""; rc=99
if   [ -f pyproject.toml ] || ls test_*.py tests/ >/dev/null 2>&1; then
  runner="python -m pytest -q"; python -m pytest -q >/tmp/bc.txt 2>&1; rc=$?
elif [ -f package.json ]; then
  runner="npm test"; npm test >/tmp/bc.txt 2>&1; rc=$?
fi

ids=$(grep -oE '^\| *\*{0,2}([A-Z][0-9]+)\*{0,2} *\|' SPEC.md 2>/dev/null | grep -oE '[A-Z][0-9]+' | sort -u)
tot=0; miss=""
for id in $ids; do
  tot=$((tot+1))
  grep -rqE "\b$id\b" --include='*test*' . 2>/dev/null || miss="$miss $id"
done
nmiss=$(echo $miss | wc -w | tr -d ' ')

contract="ok"
git diff --quiet -- SPEC.md DESIGN.md 2>/dev/null || contract="modified"

jq -n --argjson s "$src" --arg r "${runner:-none}" --argjson rc "$rc" \
      --argjson t "$tot" --argjson m "$nmiss" --arg ml "${miss# }" --arg c "$contract" \
  '{sourceFiles:$s, runner:$r, testExit:$rc, specIds:$t, missingInTests:$m,
    missingIds:$ml, contract:$c,
    pass: ($s>0 and $rc==0 and $m==0 and $c=="ok")}' > "$OUT"

jq -r '"  소스 파일 \(.sourceFiles)개   테스트 \(.runner) exit=\(.testExit)   수용기준 \(.specIds-.missingInTests)/\(.specIds) 테스트화   계약 \(.contract)"' "$OUT"
[ "$(jq -r .pass "$OUT")" = "true" ] && exit 0
[ "$src" -eq 0 ] && exit 3 || exit 1
