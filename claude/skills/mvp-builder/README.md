# mvp-builder — 아이디어 한 줄에서 MVP까지 (v4 · 스킬 모드: 내장 agent-skills / lite)

> **이 판은 v4 다.** 강의 저장소의 `mvp_building/graph/mvp-builder-4` 를 `mvp-builder` 라는 이름으로 마켓플레이스에 올린 것이다. 이전 판(v1~v3)은 강의 저장소에만 있다.
>
> **왜 v4 인가.** v3 의 갤러그 런(2026-09-04)은 게임 한 판을 위해 코드 이전에 문서 약 1,500줄
> (SPEC 447 · DESIGN 621 · todo 398)을 먼저 썼고, 36분 · $12.8 을 쓴 뒤 구현 1라운드에서 운영자가 멈췄다.
> 루프는 약속대로 돌았다(설계 반영률 100%, 리뷰 1라운드 must 0). **비싼 것은 루프가 아니라 스킬이었다.**
>
> 단계마다 백지 `claude -p` 가 `/agent-skills:spec` · `review` · `plan` · `build` 를 호출했고,
> 이 스킬들은 1,200~3,500단어짜리 양식이다. 프로젝트가 작아도 큰 것과 같은 의식을 치른다.
> 게다가 슬래시 커맨드는 **사용자가 agent-skills 플러그인을 설치했을 때만** 해석된다 —
> 없으면 `/agent-skills:spec` 이 그냥 문자열로 들어가 조용히 퇴화한다.

## 1. 바뀐 것 두 가지

| | v3 | v4 |
|---|---|---|
| 스킬 출처 | 외부 플러그인 `/agent-skills:*` (설치 필요) | **플러그인 안에 내장** `prompts/full/*.md` (MIT, 출처 표기) |
| 주입 방식 | 사용자 프롬프트 첫 줄의 슬래시 커맨드 | `claude -p --append-system-prompt "$(cat prompts/<mode>/<단계>.md)"` |
| 스킬 모드 | 없음 (항상 agent-skills) | `full`(기본) / **`--lite`** — 단계별 기본 프롬프트 |

**lite 는 무엇이 다른가.** 같은 게이트·같은 루프·같은 원장을 쓴다. 바뀌는 것은 모델에게 붙는 시스템
프롬프트 하나뿐이다. lite 프롬프트는 각 100~230단어이고, 역할 · 산출물 구성 · 길이 상한 ·
**게이트가 세는 규칙**(ID 는 수용 기준 표에만, 수동 기준은 `test/manual-tests.md`, 러너는 npm test/pytest)을
직접 말해 준다. v3 갤러그 런에서 게이트와 스펙 형식이 어긋났던 지점(가정 표 S1~S11 이 수용 기준으로 집계)이
lite 프롬프트의 규칙이 됐다.

```
prompts/
├── full/                        내장 agent-skills (addyosmani/agent-skills 1.0.0, MIT)
│   ├── spec.md                  ← spec-driven-development
│   ├── design.md                ← api-and-interface-design        (v3 는 설계에 스킬이 없었다)
│   ├── review.md                ← code-review-and-quality
│   ├── plan.md                  ← planning-and-task-breakdown
│   ├── build.md                 ← incremental-implementation + test-driven-development
│   └── LICENSE
└── lite/                        단계별 기본 프롬프트 (각 100~230단어)
    ├── spec.md · design.md · design-highlevel.md · review.md · plan.md · build.md
```

## 2. 사용

```
/mvp-builder:start [--lite | --full] [--fast | --profile 이름] [--mode design] [--auto-approve] <아이디어>
```

- `--lite` — 가볍게. 작은 프로젝트(단일 파일 앱, CLI, 게임 한 판)는 이걸 쓴다
- `--full` — 기본값. 내장 agent-skills 로 v3 와 같은 양식을 강제한다. 큰 시스템 설계(`--mode design`)에 권한다
- `--fast` 는 별개 축이다(모델·노력·라운드 예산). `--lite --fast` 가 가장 싸고, `--full` 만 주면 v3 와 동일하게 돈다
- `--auto-approve` (v4.1) — **자동 게이트**. 기계 게이트를 통과한 단계만 스스로 승인한다: 스펙은 수용 기준 ID 1건 이상,
  설계는 반영률 pass + 리뷰 루프 exit 0(must 0). 미통과·판정 불가·실행 실패는 기본(human)과 똑같이 멈춘다.
  `.mvp/state.json` 의 `gate` 필드(`human`|`auto`), 이력에 `*_auto_gate_pass` / `*_auto_gate_hold` 가 남는다.
  무인 실행·스크립트용이다. 사람이 보고 결정하는 장면이 필요하면 붙이지 않는다
- (v4.2) 설계 반려 후 재진입: `design-loop.sh` 1라운드가 기존 DESIGN.md 를 새로 쓰지 않고 빠진 항목만 보완한다(반려 수정본 보존,
  빠진 것이 없으면 모델 호출 생략). 커맨드의 `$ARGUMENTS` 를 인용해 아이디어·사유 속 `[a|b]`·괄호·`<x>` 가 셸에서 풀리지 않는다
- 스킬 모드는 `.mvp/state.json` 의 `skills` 필드에 기록되고 `/mvp-builder:status` 에 보인다

## 3. v3 에서 바뀐 파일

| 파일 | 변경 |
|---|---|
| `prompts/` | **신규** — full(내장 스킬 5개 + LICENSE) · lite(기본 프롬프트 6개) |
| `bin/state.sh` | `st_skills`(기본 full) · `skill_prompt <단계>`(파일 없으면 exit 3) 추가 |
| `bin/phase-spec.sh` | `--lite/--full/--skills` 파싱 → state 기록. `/agent-skills:spec` 제거, `--append-system-prompt` |
| `bin/design-loop.sh` | `--append-system-prompt`(build 모드 design.md · design 모드 design-highlevel.md). 본문 지시는 v3 그대로 |
| `bin/review-gate.sh` | 라운드 1 전체 리뷰만 `/agent-skills:review` → 주입. 델타 라운드는 v3 그대로 스킬 없음 |
| `bin/phase-build.sh` | `/agent-skills:plan` · `build` → 주입 |
| `bin/status.sh` | 스킬 모드 표시 |
| `approve.sh` · `reject.sh` · `phase-design.sh` | 안내 문구의 `/mvp-builder:` → `/mvp-builder:` 만. 로직 무변경 |
| 나머지 | **무변경** — ledger · review-loop · 게이트 3종 · 정책 전부 v3 그대로 |

## 4. 주의

- agent-skills 플러그인이 **설치돼 있으면** 그쪽 SessionStart 훅이 모든 `claude -p` 에 메타 스킬(약 1,000단어)을
  자동 주입한다. `--lite` 를 줘도 이 훅은 막을 수 없다. 완전히 가볍게 돌리려면 플러그인을 비활성화하라
- full 프롬프트 첫 줄에 "배치 실행: 질문하지 말고 저장해라" 주석을 붙였다. 원본 스킬은 대화형 전제라
  "confirm with the user" 같은 지시가 있고, `-p` 에서는 그 지점에서 멈추기 때문이다
- full 의 design.md 는 v3 에 없던 추가다. v3 와 완전히 같은 조건이 필요하면 `prompts/full/design.md` 를 빈 파일로 두면 된다
