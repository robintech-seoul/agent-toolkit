#!/usr/bin/env bash
# 발견 원장 — 추가 전용 jsonl. 상태 변화는 편집이 아니라 이벤트 추가다.
# 쓰는 주체는 코드뿐이다. 모델(리뷰어·수정자)은 델타를 보고할 뿐, append 는 여기서만 한다.
#   이벤트: found(등록) claimed(수정자 조치 주장) resolved(리뷰어 해소 확정)
#           reopened(미해소·재발) accepted(운영자가 안 고치기로)
#   현재 상태 = 그 id 의 마지막 이벤트.  resolved→해소, accepted→수용, 나머지→열림
LG="${LEDGER_FILE:-.mvp/ledger.jsonl}"

lg_next_id() {
  local n=0
  [ -f "$LG" ] && n=$(jq -s '[.[]|select(.ev=="found")]|length' "$LG" 2>/dev/null || echo 0)
  printf 'L-%03d' $((n+1))
}

# $1 = 이벤트 JSON 한 줄. 검증 위반 → return 3 (호출자가 exit 3 로 올린다)
lg_append() {
  local e="$1" ev id sev by
  echo "$e" | jq -e . >/dev/null 2>&1 || { echo "원장: JSON 이 아니다" >&2; return 3; }
  ev=$(echo "$e" | jq -r '.ev // ""'); id=$(echo "$e" | jq -r '.id // ""')
  [ -n "$id" ] || { echo "원장: id 없음" >&2; return 3; }
  case "$ev" in
    found)
      sev=$(echo "$e" | jq -r '.sev // ""')
      case "$sev" in must|should|nit) ;; *)
        echo "원장: 알 수 없는 심각도 '$sev' (id=$id)" >&2; return 3 ;; esac ;;
    claimed|resolved|reopened|accepted)
      grep -q "\"id\":\"$id\"" "$LG" 2>/dev/null || {
        echo "원장: 존재하지 않는 id '$id' 참조 (ev=$ev)" >&2; return 3; } ;;
    *) echo "원장: 알 수 없는 이벤트 '$ev'" >&2; return 3 ;;
  esac
  by=$(echo "$e" | jq -r '.by // ""')
  if [ "$ev" = "resolved" ] && [ "$by" != "reviewer" ]; then
    echo "원장: resolved 는 reviewer 만 만들 수 있다 (by=$by)" >&2; return 3; fi
  if [ "$ev" = "accepted" ] && [ "$by" != "operator" ]; then
    echo "원장: accepted 는 operator 만 만들 수 있다 (by=$by)" >&2; return 3; fi
  mkdir -p "$(dirname "$LG")"
  echo "$e" | jq -c . >> "$LG"
}

# 전체 발견의 현재 상태 → JSON 배열 [{id,sev,where,title,why,fix,state}]
lg_state() {
  [ -f "$LG" ] || { echo '[]'; return; }
  jq -s 'group_by(.id) | map(
    (map(select(.ev=="found"))[0]) as $f |
    { id: .[0].id, sev: ($f.sev // "?"), where: ($f.where // ""),
      title: ($f.title // ""), why: ($f.why // ""), fix: ($f.fix // ""),
      state: (last | if .ev=="resolved" then "resolved"
                     elif .ev=="accepted" then "accepted" else "open" end) })' "$LG"
}

lg_open_must_ids() {  # 공백 구분·정렬 — 교착 진단용 ID 집합
  lg_state | jq -r '[.[] | select(.state=="open" and .sev=="must") | .id] | sort | join(" ")'
}

lg_open_musts() {     # 수정자 입력용 상세
  lg_state | jq -r '.[] | select(.state=="open" and .sev=="must")
    | "- \(.id) \(.where) — \(.title)\n    왜: \(.why)\n    조치: \(.fix)"'
}

lg_counts() {
  lg_state | jq -r '"열린 must \([.[]|select(.state=="open" and .sev=="must")]|length)   해소 \([.[]|select(.state=="resolved")]|length)   열린 should \([.[]|select(.state=="open" and .sev=="should")]|length)   열린 nit \([.[]|select(.state=="open" and .sev=="nit")]|length)"'
}

lg_brief() {          # 델타 라운드 리뷰어의 요약 뷰
  echo "[열린 must — 각각 해소됐는지 판정해라]"
  lg_open_musts
  echo
  echo "[알려진 발견 — new 로 다시 보고하지 마라. 상세는 $LG 를 읽어라]"
  lg_state | jq -r '.[] | select((.state=="open" and .sev=="must") | not)
    | "\(.id) [\(.sev)/\(.state)] \(.title)"'
}

lg_triage() {         # 마무리 — 남은 should/nit 를 사람 앞에
  echo "# 남은 발견 선별 목록 (열린 should·nit)"
  echo "# 고칠 가치가 있는 것을 골라 수정하거나, accepted 이벤트로 승계를 기록하라."
  lg_state | jq -r '.[] | select(.sev!="must" and .state=="open")
    | "- \(.id) [\(.sev)] \(.where) — \(.title)"'
}
