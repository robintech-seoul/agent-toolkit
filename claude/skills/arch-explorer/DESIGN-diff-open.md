# arch-explorer:diff --open — 브랜치 변경 지도 옆에서 질의응답

`/arch-explorer:diff --open`은 브랜치의 변경 지도를 **헤드리스 Claude 세션**에서
만들고, 그 지도를 대화창과 함께 브라우저에 띄운다. 대화창의 답은 두 출처에서 온다.

- 이 브랜치가 **바꾼 부분**: 지도를 만든 세션의 분석 맥락. 대화마다 그 세션을 fork해서 이어받는다.
- **기존 코드**: 지금의 open과 같이 code-wiki.

`--open`이 없으면 지금처럼 HTML만 만든다. 이미 만든 변경 지도는
`/arch-explorer:open <html>`로 다시 연다.

대상 버전: arch-explorer 0.3.1 → 0.4.0
범위 밖:
- Codex로 빌드 세션을 이어받는 것. `codex exec resume`에는 fork가 없다.
- 대화창에서 지도를 다시 빌드하는 것.

---

## 1. 현재 구조

### 1.1 diff: 대화형 세션 안에서 모델이 전부 한다

```
/arch-explorer:diff [head [base]] [--save-to[=<path>]] [--include-uncommitted]
  §1 범위 확정   head·base 결정, 물어볼 경우 판정, mb = merge-base, <after> 결정
                 (--include-uncommitted면 임시 index로 작업 트리 스냅샷)
  §2 변경 수집   git log mb..head, git diff --name-status/--numstat mb <after>
                 head가 현재 브랜치가 아니면 임시 worktree에서 읽음
  §3 head 지도   build §1–2 재사용, 변경이 있는 박스만 깊이 drill
  §4 블럭 설명   블럭당 서브에이전트(최대 6개) → JSON → 세션이 MODEL에 병합
  §5–6 렌더·쓰기 MODEL + CHANGES → <head>-vs-<base>.html
  §7 검증·보고
```

| 항목 | 현재 |
|---|---|
| 실행 위치 | 사용자의 대화형 세션. 권한은 사용자가 승인 |
| 범위 확정 | 모델이 SKILL.md의 git 명령을 따라 함 |
| 산출물 | HTML 하나. 사이드카도 README도 없음 |
| 분석 맥락 | 블럭별 JSON과 세션이 읽은 코드. 세션이 끝나면 HTML에 남은 `CHANGES`만 남음 |

### 1.2 open: 대화창의 질문 하나가 헤드리스 CLI 실행 하나다

```
브라우저 ─POST /api/ask {conversation, question, context}─▶ chat_server.py
  prompt = [map context] + [wikis]/[wiki status] + 질문
  claude -p --tools Read,Grep,Glob --strict-mcp-config
            --append-system-prompt <answer-rules.md> [--resume <conv.session>]
  └─ stream-json → NDJSON(delta/tool/final/error) → 브라우저
```

| 항목 | 현재 |
|---|---|
| 대화 ↔ 세션 | 서버 메모리의 `convs[conversation].session`. 첫 질문은 새 세션 |
| 규칙 | `assets/answer-rules.md` 하나. wiki가 1차 출처 |
| 최신 판정 | `status.py`: build 지도는 `arch-explorer.json` 사이드카의 `sha..HEAD`, wiki는 `last_ingested_sha..HEAD` |
| 지도 종류 | build 지도만 연다 (`DESIGN-open.md` 범위 밖에 diff 지도가 명시됨) |
| 패널 맥락 | `MODEL`의 현재 뷰, 선택한 박스(`id, title, lines`), 뷰의 `ifaces` |

### 1.3 빠진 연결

| 필요한 것 | 현재 |
|---|---|
| 지도를 만든 분석 맥락을 대화에서 쓰기 | diff는 대화형 세션에서 돌기 때문에 서버가 이어받을 세션이 없음 |
| 변경 지도를 open으로 열기 | open이 diff 지도를 모름. 사이드카가 없어 범위·최신 여부를 알 수 없음 |
| 대화에서 merge-base 시점 코드와 diff 보기 | 대화 도구는 Read/Grep/Glob뿐이라 작업 트리만 읽음 |
| 변경 지도에 맞는 wiki 판정 | wiki를 HEAD와 비교하므로 브랜치의 변경까지 "wiki가 낡음"으로 셈 |
| 패널이 박스의 변경 상태를 아는 것 | `contextPayload`가 `change`와 `CHANGES`를 보내지 않음 |

### 1.4 확인된 CLI 동작 (2026-10-02, Claude Code 2.1.286)

설계가 기대는 전제다. 임시 git 저장소에서 `claude -p --model haiku`로 확인했다.

| 전제 | 결과 |
|---|---|
| 쓰기 권한이 있던 세션을 `--resume <id> --fork-session --tools Read,Grep,Glob,Bash`로 이으면 맥락은 남고 쓰기는 막힘 | 빌드 때 알려 준 코드워드를 기억함. Write는 "disabled"로 실패. 새 session id가 나옴 |
| fork해도 원래 세션은 그대로 | 원래 세션 jsonl에 fork 이후 내용이 없음 |
| `--permission-mode dontAsk`에서 `--allowedTools 'Bash(git show *)'` 밖의 명령은 거부 | `git show HEAD:a.txt` 실행됨, `touch evil.txt` 거부됨 |
| `-p` 세션에서 플러그인 스킬이 보임 | init 이벤트의 `skills`에 `arch-explorer:diff` 있음 |
| `--allowedTools`는 인자를 여러 개 받음 | 뒤에 오는 프롬프트까지 가져감. 프롬프트는 stdin으로 넘긴다 (engines.py가 이미 그렇게 함) |
| 세션은 cwd 단위로 저장됨 | `~/.claude/projects/<cwd 인코딩>/<id>.jsonl`. 빌드와 대화를 같은 cwd(저장소 루트)에서 실행해야 함 |

구현 1단계에서 추가로 확인한 것:

| 전제 | 결과 |
|---|---|
| 헤드리스 빌드의 서브에이전트도 `dontAsk` 허용 목록을 따름 | 서브에이전트의 `touch`는 거부, 허용된 `git log`·Write는 실행 |
| 서브에이전트가 백그라운드로 돌면 `result` 이벤트가 두 번 나옴 | 첫 결과는 "기다리는 중", 둘째가 최종. 빌드는 **프로세스가 끝난 뒤 마지막 `result`**로 판정 |
| `--disallowedTools 'Bash(git *--output*)'`가 git의 파일 쓰기 옵션을 막음 | `--output=x`, `--output x` 모두 거부 |
| 허용 패턴에 맞지 않는 명령은 거부 | `git show … > f`(리다이렉트), `git -c … diff` 거부 |
| `--add-dir`로 준 경로만 저장소 밖에서 읽힘 | worktree 파일 읽기 성공, `/etc/hosts` 거부 |
| 없는 세션을 resume하면 | init 이벤트 없이 `result`(`is_error`, `num_turns: 0`, `errors: ["No conversation found …"]`)가 나오고 종료 코드 1. 대체 경로는 이 신호로 판단 |

---

## 2. 바꿀 것

핵심 결정은 네 가지다. 세부 사항은 각 결정 아래에 둔다.

### 2.1 [핵심] 명령: `diff --open`으로 만들고, `open <html>`로 다시 연다

```
/arch-explorer:diff [head [base]] [--save-to[=<path>]] [--include-uncommitted] [--open]
/arch-explorer:open <변경 지도 html> [--port=N]
```

| | `diff` (`--open` 없음) | `diff --open` | `open <변경 지도>` |
|---|---|---|---|
| 빌드하는 곳 | 대화형 세션 (지금과 같음) | 헤드리스 `claude -p` | 빌드하지 않음 |
| 산출물 | HTML + 사이드카 (`session: null`) | HTML + 사이드카 (`session: <id>`) | — |
| 그다음 | 경로 보고 | wiki·엔진 확인 → 서버 → 브라우저 | 최신 확인 → wiki → 서버 → 브라우저 |
| 대화의 바뀐 부분 출처 | — | 빌드 세션 fork | 세션이 있으면 fork, 없으면 대체 경로(2.3) |

**`--open`은 빌드할 곳을 정하는 플래그다.** 빌드가 끝난 뒤의 동작만 바꾸는 게 아니다.
대화창이 이어받을 세션을 만들려면 처음부터 헤드리스로 빌드해야 한다. 그래서 open이
`--diff`를 받는 형태가 아니라 diff의 플래그로 둔다. 출발점도 "브랜치 변경을 본다"는
diff다.

**`--open` 없는 diff도 사이드카를 쓴다.** 동작 변화는 이것 하나다. 사이드카가 있어야
나중에 open이 이 파일을 변경 지도로 알아보고 범위와 최신 여부를 판단할 수 있다.
`CHANGES.range`를 HTML에서 파싱하는 방법도 있지만, 모델이 매번 쓰는 JS에서 값을
꺼내는 것은 깨지기 쉽다.

**질문은 빌드 전에 모두 끝낸다.** `--open`일 때 범위 확인 질문, wiki sync 여부, 엔진
확인을 빌드 전에 마친다. 그러면 몇 분 걸리는 빌드가 사람을 기다리지 않고 끝까지 돈다.

#### 흐름

```
/arch-explorer:diff … --open
  1. 범위     diff_session.py resolve → ask면 사용자에게 묻고 다시 resolve
  2. wiki     open §2와 같음. 판정 기준은 mb (2.4)
  3. 엔진     claude가 없으면 "--open은 지금 Claude만 지원합니다" → --open 없이 진행할지 묻기
              저장된 기본값이 codex여도 빌드·대화는 claude로 한다고 알린다 (기본값은 그대로)
              wiki가 없거나 만들기를 거절해도 대화창은 켠다. 바뀐 부분은 빌드 맥락으로
              답할 수 있기 때문이다. 기존 코드에 대한 답이 빈약하다고 알린다
  4. 빌드     diff_session.py build (백그라운드) → 끝나면 결과 JSON
  5. 열기     chat_server.py launch --map <html> --engine claude
  6. 보고     diff §7 보고 + open §5 보고

/arch-explorer:open <html>
  1. 지도     옆에 kind=diff 사이드카가 있으면 diff_session.py status
              stale → "브랜치가 그 뒤로 진행됐습니다. 다시 만들기(diff --open) / 그대로 열기"
  2. wiki     기준은 사이드카의 mb
  3. 엔진     session이 있으면 claude. 없으면 지금 규칙대로 (대체 경로는 엔진과 무관)
  4–5.        지금과 같음
```

### 2.2 [핵심] 범위 확정과 헤드리스 빌드는 프로그램이 한다: `bin/diff_session.py`

| 명령 | 하는 일 | 출력 |
|---|---|---|
| `resolve [head [base]] [--include-uncommitted]` | diff §1을 그대로 구현: head·base 결정, 물어볼 경우 판정, `mb`, `<after>`(임시 index 스냅샷), 메모(로컬/origin 불일치, 커밋 안 된 변경) | `{head, head_sha, base, mb, after, uncommitted, commits, notes}` 또는 `{ask, reason, choices}` |
| `build --range-file <file>` | 헤드리스 빌드, 작업 트리 확인, 사이드카 기록 | `{out, sidecar, session, log, report, reused}` 또는 `{error, log}` |
| `record --range-file <file>` | 대화형 diff가 끝날 때 사이드카만 기록 (`session: null`) | 사이드카 |

`resolve`는 범위를 런타임 디렉터리의 파일(`range_file`)에도 저장한다. `build`와
`record`는 그 파일을 받는다. 커밋 제목처럼 따옴표가 섞인 값을 셸 인자로 넘기지
않기 위해서다.

**변경 지도의 최신 판정은 `status.py check`에 둔다.** 처음 설계는
`diff_session.py status`였지만, open 스킬이 build 지도와 변경 지도를 같은 명령
하나로 확인하도록 바꿨다. `check`는 HTML 옆에 `<stem>.arch-explorer.json`이
있으면 `kind: "diff"`를 내고, 브랜치 진행(`advanced`, 커밋 수), 재작성
(`rewritten`), 작업 트리 변화(`worktree`, `--include-uncommitted` 지도만)를
판정한다. 지도가 아직 없을 때(diff --open의 빌드 전 확인)는 `--against <mb>`로
wiki를 merge-base 기준으로 판정한다.

**범위 확정을 프로그램으로 옮기는 이유.**
- 헤드리스 세션은 사용자에게 물을 수 없다. 물어야 하는 경우는 빌드 전에 대화형 스킬이 처리해야 한다.
- 임시 index 스냅샷(`GIT_INDEX_FILE=… git add -A`)은 환경변수가 앞에 붙은 명령이다. 헤드리스의 `Bash(git *)` 허용 규칙에 맞지 않는다.
- 두 모드가 같은 구현을 쓰므로 diff SKILL.md §1은 이 프로그램을 부르는 것으로 바뀐다. 결과는 지금과 같다.

#### 사이드카: `<stem>.arch-explorer.json` (HTML 옆)

```json
{
  "version": 1,
  "kind": "diff",
  "head": "feature/login", "head_sha": "<sha>",
  "base": "main", "mb": "<sha>",
  "after": "<head sha 또는 tree sha>", "uncommitted": false,
  "engine": "claude", "session": "<id> | null",
  "built_at": "2026-10-02T12:00:00Z"
}
```

build 지도의 사이드카(`arch-explorer.json`)는 디렉터리에 하나다. 변경 지도는 한
디렉터리(`docs/architecture/changes/`)에 여럿 쌓이므로 파일별로 둔다. 기록은
프로그램이 한다. 세션 id는 `claude -p` 출력의 init/result 이벤트에서 받는다.

#### 헤드리스 빌드

```
cwd = <root>
claude -p --output-format stream-json --verbose --strict-mcp-config
       --permission-mode dontAsk
       --tools Read,Grep,Glob,Bash,Write,Edit,Agent
       --allowedTools Read Grep Glob Agent Write Edit
                      'Bash(git show)' 'Bash(git show *)' …   (읽기 전용 git 13종)
                      'Bash(python3 *)' 'Bash(ls *)' 'Bash(wc *)' 'Bash(head *)' 'Bash(tail *)'
       --disallowedTools 'Bash(git *--output*)'
       [--add-dir <worktree>]
stdin: 빌드 지시문
```

빌드 지시문의 내용:
- `<plugin>/skills/diff/SKILL.md`를 읽는다.
- 이미 확정된 범위(JSON)를 받았으니 §1을 건너뛰고 §2–§7을 따른다.
- 결과는 `<out>`에만 쓴다.
- 물어야 할 상황이면 묻지 말고 `CANNOT: <이유>`로 끝낸다.

슬래시 명령 `/arch-explorer:diff` 대신 경로를 주는 이유는 두 가지다. §0–§1(인자 해석,
범위 확정)을 건너뛰어야 하고, 부른 스킬과 같은 플러그인 사본을 쓰게 하기 위해서다.

| 세부 | 결정 |
|---|---|
| 권한 | `dontAsk` + 허용 목록. 목록 밖 호출은 거부된다 (1.4). 서브에이전트도 같은 제약을 받는다. git은 `git *`가 아니라 읽기 명령만 연다(show, diff, log, status, rev-parse, ls-files, ls-tree, cat-file, merge-base, grep, blame, rev-list, name-rev). worktree는 프로그램이 만들므로 빌드는 checkout·reset·stash가 필요 없다 |
| 다른 파일을 건드렸는지 | 빌드 전후로 작업 트리를 임시 index로 스냅샷(`status.snapshot_tree`)해 tree를 비교한다. `git status`보다 정확하다(이미 수정된 파일의 내용 변화도 잡는다). 지도와 사이드카는 빼고 비교한다. 바뀐 것이 있으면 실패로 처리하고 사이드카를 쓰지 않는다. 되돌리지는 않는다. Write·`python3`는 경로를 제한할 수 없어서 이 사후 확인으로 막는다 |
| 스냅샷에서 빼는 것 | 지도 HTML과 사이드카. 빼지 않으면 `--include-uncommitted`에서 지도 자신이 "브랜치의 변경"으로 잡히고, 다시 열 때마다 작업 트리가 바뀐 것으로 판정된다 |
| head가 현재 브랜치가 아닐 때 | 프로그램이 `git worktree add --detach <scratch> <head>`를 만들고 `--add-dir`로 넘긴다. 끝나면 지운다. 헤드리스가 저장소 밖 경로를 읽으려면 `--add-dir`가 필요하다 |
| 진행 표시 | stream-json의 tool·text 이벤트를 로그 파일(`resolve`가 알려 주는 `build_log`)에 한 줄씩 남긴다. 서브에이전트 것은 `(subagent)`로 구분한다. 스킬은 백그라운드로 실행하고, 사용자가 물으면 로그를 읽어 알린다 |
| 시간 제한 | 기본 30분. 넘으면 프로세스 그룹을 종료하고 실패로 처리한다 |
| 재사용 | 같은 `<out>`의 사이드카가 있고 `head_sha`, `mb`, `after`가 같고 세션이 있으면 빌드하지 않는다. 결과에 `reused: true` |
| 환경 | `engines.child_env()`로 `CLAUDECODE` 등을 뺀다 |

### 2.3 [핵심] 대화는 빌드 세션을 fork해서 이어받는다: `engines.py`, `chat_server.py`

```
대화의 첫 질문  claude -p --resume <build session> --fork-session  …(아래 도구)
                → init 이벤트의 새 session id를 convs[conv].session에 저장
다음 질문       claude -p --resume <convs[conv].session> …
"새 대화"       convs[conv] 삭제 → 다음 질문이 빌드 세션에서 다시 fork
```

| | build 지도 (지금) | 변경 지도 |
|---|---|---|
| 첫 질문 | 새 세션 | 빌드 세션 fork |
| 도구 | `--tools Read,Grep,Glob` | `--tools Read,Grep,Glob,Bash --permission-mode dontAsk --allowedTools 'Bash(git show *)' 'Bash(git diff *)' 'Bash(git log *)'` |
| 규칙 | `answer-rules.md` | `answer-rules.md` + `answer-rules-diff.md` (2.4) |
| 질문 머리 | `[map context]`, `[wiki status]` | 여기에 `[change range] head=… base=… merge-base=… after=…` 추가 |

- **fork를 쓰는 이유.** 대화 여러 개가 빌드 세션 하나에 이어 붙으면 서로의 질문이 섞이고, "새 대화"를 해도 빌드 직후 상태로 돌아갈 수 없다. fork하면 빌드 세션은 그대로 남는다(1.4).
- **git을 여는 이유.** 이어받은 대화에는 Write가 없다(1.4). 하지만 merge-base 시점 코드(`git show <mb>:path`)와 hunk(`git diff <mb> <after> -- path`)는 Read로 볼 수 없다. 그래서 읽기 전용 git 세 가지만 연다.
- **git의 쓰기 옵션은 막는다.** `git diff --output=<file>`처럼 파일을 쓰는 옵션이 있다. `--disallowedTools 'Bash(git * --output*)'`로 막고, 구현 1단계에서 거부되는지 확인한다.
- **대체 경로.** 사이드카의 `session`이 null이거나, 빌드 세션 resume이 실패하는 경우다(세션 파일 정리, 다른 머신). 이때는 fork 없이 새 세션으로 같은 질문을 다시 실행하고, 규칙에 "빌드 맥락 없음"을 붙인다. 답은 `CHANGES`(패널 맥락) + git diff + wiki에서 나온다. 패널에 `{"type":"note"}`로 한 번 알린다. 대체 경로는 어느 엔진이든 된다.
- **서버 인자는 늘리지 않는다.** `launch --map <html>`로 띄우면 서버가 HTML 옆 사이드카를 읽고 변경 지도인지 판단한다. 런타임 파일 키(root+map)는 그대로다.
- **사이드카는 질문과 상태 조회 때마다 다시 읽는다.** 서버가 떠 있는 동안 `diff --open`으로 같은 지도를 다시 빌드하면 `launch`는 그 서버를 재사용한다. 다시 읽지 않으면 새 대화가 옛 빌드 세션을 fork한다. 세션 id가 바뀌면 resume 실패 표시도 초기화한다.

### 2.4 [핵심] 답변 규칙: 바뀐 것은 빌드 맥락으로, 기존 것은 wiki로

`assets/answer-rules-diff.md` (변경 지도일 때 `answer-rules.md` 뒤에 붙인다)

| 질문 대상 | 출처 | 인용 |
|---|---|---|
| 이 브랜치가 바꾼 것 (`change`가 붙은 박스·화살표·인터페이스, 블럭 카드) | 이 세션의 빌드 분석이 먼저. 부족하면 `git diff <mb> <after> -- <file>`, `git show <mb>:<path>` | 추가·수정은 after 쪽 `path:line`, 삭제는 `<mb>` 쪽 줄과 "(삭제됨)" |
| 바뀌지 않은 기존 코드, 바뀐 코드가 기대는 주변 구조 | 지금 규칙 그대로 (wiki 우선, 링크된 소스만). **빌드 때 읽은 기억으로 대신하지 않는다** (아래) | 이 대화에서 읽은 wiki 페이지, 또는 wiki가 침묵해서 이 대화에서 연 소스 줄 |
| 둘에 걸치는 질문 | 기존 동작은 wiki, 바뀐 점은 빌드 분석. 문장마다 어느 쪽 근거인지 구분 | 둘 다 |

- **바뀌지 않은 코드는 빌드 맥락이 있어도 wiki를 거친다.** 실제 실행에서 모델은 빌드 때 읽은 파일을 기억으로 답했다(소스를 새로 읽지는 않았다). 작은 데모에서는 맞았지만, 빌드는 바뀌지 않은 코드를 변경 설명에 필요한 만큼만 본다. hunk나 몇 줄, 서브에이전트 요약, 박스 제목 정도이고, 자동 요약으로 더 흐려질 수 있다. 그래서 바뀌지 않은 코드에 대한 주장은 이 대화에서 읽은 wiki 페이지나, wiki가 침묵해서 이 대화에서 연 소스 줄로만 인용한다. 빌드 맥락은 "바뀐 코드와의 관계"를 덧붙일 때만 쓴다.
- **소스를 넓게 읽지 않는 원칙은 바뀐 부분에도 적용한다.** 빌드 분석이 이미 있으므로 새로 읽는 것은 질문이 요구하는 hunk와 파일뿐이다.
- **wiki는 merge-base 시점 코드로 본다.** `status.wiki_status(..., against=<mb>)`를 추가한다.
  - wiki의 기준 커밋이 `mb`의 조상이면 `base..mb`만 낡은 정도로 센다. `mb..head`는 브랜치가 한 일이라 세지 않는다.
  - 기준 커밋이 브랜치 위에 있으면(브랜치에서 sync한 경우) 지금처럼 HEAD와 비교하고 `includes_branch: true`를 붙인다. 이때 규칙은 "wiki에 이 브랜치의 변경이 일부 들어 있을 수 있다"고 알린다.

### 2.5 [부수] 대화창: 변경 상태를 맥락에 싣는다

| 변경 | 내용 |
|---|---|
| `contextPayload` | 선택한 박스의 `change`, 뷰 안에서 `change`가 붙은 요소 목록, 해당 블럭의 `CHANGES.blocks[].summary`와 기능 제목 |
| `format_context` | 위 내용을 `[map context]`에 넣는다. `MAX_CONTEXT`는 그대로 |
| 배너 | "변경 지도: `<head>` vs `<base>` (merge-base `<sha7>`)", 빌드 맥락 사용 여부, 지도가 stale이면 브랜치 진행 커밋 수 |
| `GET /api/status` | `diff: {head, base, mb, session: bool, state}` 추가 |
| 빈 화면 문구 | 변경 지도면 "바뀐 부분은 지도를 만든 분석으로, 기존 코드는 wiki로 답합니다" |

카드 링크(`refIndex`)는 지금처럼 `ifaces[].items[].ref`로 만든다. diff의 블럭 카드
`refs`는 링크하지 않는다. diff §5의 계약이 텍스트로만 보여 주기 때문이다.

### 2.6 [부수] 비용과 수명

- **질문마다 빌드 세션 맥락 전체를 다시 불러온다.** 첫 응답이 느리고, 질문 간격이 캐시 수명보다 길면 비용도 다시 든다. 맥락이 커서 자동 요약이 일어나면 세부 분석이 흐려질 수 있다. 이때도 대체 경로의 자료(`CHANGES`, git)는 남는다.
- **세션 파일은 Claude Code의 정리 주기를 따른다.** 오래된 변경 지도는 대체 경로로 동작한다.
- **`--include-uncommitted`의 `after` tree는 어떤 ref도 가리키지 않는다.** `git gc`가 오래된 객체를 정리하면 사라질 수 있다. 그 경우 `status`는 `unknown`을 내고 다시 만들기를 권한다.

---

## 3. 구현 순서와 검증

변경 파일 요약:

```
claude/skills/arch-explorer/
├── bin/diff_session.py         신규: resolve, build, record, status (2.2)
├── bin/engines.py              수정: fork 인자, 변경 지도용 도구·권한 (2.3)
├── bin/chat_server.py          수정: 사이드카 감지, 규칙 결합, [change range], 대체 경로 (2.3)
├── bin/status.py               수정: wiki_status(against=mb) (2.4)
├── assets/answer-rules-diff.md 신규 (2.4)
├── assets/chat-panel.html      수정: CHANGES 맥락, 배너 (2.5)
├── skills/diff/SKILL.md        수정: §0 --open, §1 → resolve, §6 사이드카, --open 흐름 (2.1)
├── skills/open/SKILL.md        수정: 변경 지도 열기 (2.1)
├── tests/                      test_diff_session.py 신규, engines·server·status 테스트 추가
├── README.md, DESIGN-open.md   수정: 범위 밖 문구 정리, diff --open 절
└── .claude-plugin/plugin.json  0.4.0
.claude-plugin/marketplace.json  설명 갱신
```

| # | 단계 | 검증 |
|---|---|---|
| 1 | 남은 CLI 전제 확인 | 실제 `claude -p`로: 헤드리스 빌드의 서브에이전트가 `dontAsk` 허용 목록 안에서 동작하는가 / `git diff --output=x`가 `--disallowedTools`로 거부되는가 / `--add-dir` 경로를 읽을 수 있는가. 하나라도 안 되면 해당 절을 고친 뒤 진행 |
| 2 | `diff_session.py resolve·record·status` | 임시 git 저장소 fixture: main/master/origin 조합, 물어볼 경우 전부, merge-base 기준, `--include-uncommitted` 스냅샷이 **사용자 index를 건드리지 않는지**, 브랜치 진행 시 stale, tree gc 시 unknown |
| 3 | `diff_session.py build` | PATH의 **가짜 `claude`**: argv(권한·도구·`--add-dir`), stream에서 session id 기록, `CANNOT:` 처리, `<out>` 외 파일 변경 시 실패·사이드카 없음, worktree 생성·정리, 시간 초과 kill, 재사용. 이어서 **실제 브랜치 하나로 실제 빌드**. 가짜 CLI 통과를 실제 실행으로 치지 않는다 |
| 4 | `engines.py`·`chat_server.py` 변경 지도 모드 | 가짜 CLI: 첫 질문 `--resume <build> --fork-session`, 다음 질문 fork id로 resume, 새 대화 후 다시 fork, resume 실패 시 대체 경로와 note, 규칙 결합과 `[change range]`. 실제 CLI: 질문 두 개, 빌드 세션 파일 불변, 파일 쓰기 거부, `git diff --output` 거부 |
| 5 | `status.py` wiki 판정, 패널 | wiki 기준이 mb 이전 / mb와 같음 / 브랜치 위. 패널: 선택 박스의 change와 블럭 요약이 맥락에 들어가는지, 배너 |
| 6 | 스킬 문서 | diff SKILL.md, open SKILL.md 개정 |
| 7 | 처음부터 끝까지 | ① `diff` → HTML + 사이드카(`session: null`) → `open <html>` → 대체 경로 배너 ② `diff --open` → 바뀐 부분 질문은 빌드 맥락으로 답하고 tool 이벤트에 넓은 소스 읽기가 없는지, 기존 코드 질문은 wiki로 답하는지 ③ 다시 `open <html>` → 같은 빌드 세션에서 fork ④ 브랜치에 커밋 추가 → stale 질문 ⑤ head ≠ 현재 브랜치 → worktree 경로 ⑥ `--include-uncommitted` |
| 8 | 문서·버전 | README, `DESIGN-open.md`의 범위 밖 문구, plugin 0.4.0, marketplace 설명 |

1이 먼저다. 그 결과에 따라 2.2·2.3의 권한 설계가 바뀔 수 있다. 2와 4의 가짜 CLI
부분은 서로 독립이라 병렬로 진행할 수 있다. 실제 실행 검증(3의 후반, 4의 후반, 7)은
2·3이 끝난 뒤에 한다.
