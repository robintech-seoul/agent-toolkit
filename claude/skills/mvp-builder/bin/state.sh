#!/usr/bin/env bash
# 파이프라인 상태 기계. 상태는 대상 프로젝트의 .mvp/state.json 에 있다.
#   경로가 선언돼 있고, 각 단계는 앞 단계의 상태에서만 진입한다.
set -uo pipefail
S=".mvp/state.json"

_need() { command -v jq >/dev/null 2>&1 || { echo "jq 가 필요합니다" >&2; exit 3; }; }

st_init() {  # $1=idea
  _need; mkdir -p .mvp
  jq -n --arg idea "$1" '{phase:"spec_running", idea:$idea, rounds:{}, history:[]}' > "$S"
}
st_get()  { _need; jq -r ".${1}" "$S" 2>/dev/null; }
st_set()  { _need; local t; t=$(mktemp)
            jq --arg k "$1" --arg v "$2" 'setpath($k|split("."); $v)' "$S" > "$t" && mv "$t" "$S"; }
st_setn() { _need; local t; t=$(mktemp)
            jq --arg k "$1" --argjson v "$2" 'setpath($k|split("."); $v)' "$S" > "$t" && mv "$t" "$S"; }
st_log()  { _need; local t; t=$(mktemp)
            jq --arg e "$1" '.history += [$e]' "$S" > "$t" && mv "$t" "$S"; }

# 진입 가드 — 기대하는 상태가 아니면 진행하지 않는다
st_require() {
  local want="$1" cur
  [ -f "$S" ] || { echo "파이프라인이 시작되지 않았습니다. /mvp-builder:start 로 시작하세요." >&2; exit 2; }
  cur=$(st_get phase)
  [ "$cur" = "$want" ] || {
    echo "지금 단계는 '$cur' 입니다. 이 명령은 '$want' 에서만 실행됩니다." >&2; exit 2; }
}

# ── 프로필 — 속도·비용 조절 ────────────────────────────────────
# 선택은 state 의 profile 필드, 값은 policy/profiles.tsv.
# 프로필에 없는 키는 budget.tsv 로 폴백한다. standard 는 아무것도 바꾸지 않는다.
st_profile() { local p; p=$(st_get profile 2>/dev/null)
               { [ -z "$p" ] || [ "$p" = "null" ]; } && p="standard"; echo "$p"; }
prof_get() {
  [ -f "$P/policy/profiles.tsv" ] || return 0
  awk -F'\t' -v p="$(st_profile)" -v k="$1" 'NR>1 && $1==p && $2==k{print $3}' "$P/policy/profiles.tsv"
}
budget() {
  local v; v=$(prof_get "$1")
  if [ -n "$v" ]; then echo "$v"
  else awk -F'\t' -v k="$1" 'NR>1 && $1==k{print $2}' "$P/policy/budget.tsv"; fi
}
model_args() {  # claude -p 에 덧붙일 인자. 비어 있으면 세션 기본 모델·노력을 쓴다
  local m e out=""; m=$(prof_get model); e=$(prof_get effort)
  [ -n "$m" ] && out="--model $m"
  [ -n "$e" ] && out="$out --effort $e"
  echo "$out"
}

# ── 스킬 모드 (v4) ─────────────────────────────────────────────
# full(기본): prompts/full/<단계>.md — agent-skills 를 플러그인 안에 내장한 것. 외부 설치 불필요.
# lite:       prompts/lite/<단계>.md — 단계별 기본 프롬프트. 양식 강제가 없어 짧고 싸다.
# 두 모드 모두 같은 게이트·루프·원장을 쓴다. 바뀌는 것은 모델에게 붙는 시스템 프롬프트뿐이다.
st_skills() { local s; s=$(st_get skills 2>/dev/null)
              { [ -z "$s" ] || [ "$s" = "null" ]; } && s="full"; echo "$s"; }
skill_prompt() {  # $1=단계(spec|design|design-highlevel|review|plan|build) → 시스템 프롬프트 본문
  local f="$P/prompts/$(st_skills)/$1.md"
  [ -f "$f" ] || { echo "스킬 프롬프트 없음: $f" >&2; return 3; }
  cat "$f"
}

# ── 실행 모드 (v2) ─────────────────────────────────────────────
# build(기본): 스펙→설계→구현 전체. design: 하이레벨 설계까지만 — 종료 상태 designed.
st_mode() { local m; m=$(st_get mode 2>/dev/null)
            { [ -z "$m" ] || [ "$m" = "null" ]; } && m="build"; echo "$m"; }
