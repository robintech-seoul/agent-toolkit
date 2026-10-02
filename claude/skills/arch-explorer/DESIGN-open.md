# arch-explorer:open — 지도 옆에서 code-wiki로 질의응답

`/arch-explorer:open`은 아키텍처 지도를 브라우저에 띄우고, 오른쪽 대화창에서
code-wiki를 근거로 질문에 답한다. 답은 헤드리스 `claude` 또는 `codex`가 만든다.
open은 띄우기 전에 지도와 wiki가 최신인지 보고, 없거나 낡았으면 만들지·갱신할지
묻는다.

대상 버전: arch-explorer 0.2.0 → 0.3.0
범위 밖: `/arch-explorer:diff`로 만든 HTML. open은 build 지도만 연다.
(0.4.0에서 변경 지도도 열게 됐다. `DESIGN-diff-open.md` 참고.)

---

## 1. 현재 구조

### 1.1 arch-explorer

| 스킬 | 입력 | 산출물 | 비고 |
|---|---|---|---|
| `build` | scope, 출력 경로 | `docs/architecture/index.html` + `README.md` | 단일 HTML, `file://`로 열림, 외부 리소스 없음 |
| `diff` | head, base | `<head>-vs-<base>.html` | build의 1–4절을 재사용 |

플러그인에는 `SKILL.md`만 있고 `bin/`도 테스트도 없다. HTML은 매번 모델이 쓴다.
고정된 것은 SKILL.md에 적힌 계약뿐이다.

```
index.html
├── const MODEL = { <viewId>: { nodes, edges, ifaces } }   ← 구조 데이터
└── 렌더 코드 (SVG + vanilla JS)
      · 박스 클릭 → drill / 카드 필터
      · URL hash = 현재 뷰 (#worker)
      · 화살표 클릭 → 카드로 이동
```

**지도를 어느 커밋에서 만들었는지 기록이 없다.** 그래서 지금은 지도가 최신인지
판단할 수 없다.

### 1.2 code-wiki (별도 플러그인)

```
project/
├── wiki/                    ← 커밋됨
│   ├── config.yaml          # source_roots, ignore_patterns, wiki_language
│   ├── CLAUDE.md            # 문체 가이드
│   ├── <source-root>/index.md …
│   └── topics/*.md
└── .code-wiki/              ← gitignore, 머신마다 다름
    └── state.json           # last_ingested_sha, source_to_wiki, hashes
```

| 판단 | code-wiki가 하는 방식 |
|---|---|
| wiki가 있는가 | `wiki/config.yaml`이 있는지 |
| 최신인가 | `bin/scan-changes.py`: `last_ingested_sha..HEAD`의 diff를 페이지 단위로 매핑하고, `pages`·`deletions`·`dirty_topics`가 모두 비어 있으면 최신 |
| state가 없을 때 (clone 직후) | `bin/state-bootstrap.py`가 `git log -1 -- wiki/`에서 sha를 추론해 state.json을 **쓴다** |
| 질의응답 | `/code-wiki:query`: wiki를 먼저 읽고, wiki가 링크한 소스만 열고, 모든 주장에 출처를 붙임. 조건이 맞으면 topic 페이지를 **쓴다** |

`scan-changes.py`는 code-wiki 플러그인 안에 있다. 다른 플러그인에서는 설치
경로를 알 수 없어 직접 호출할 수 없다. code-wiki가 PyYAML에 의존한다는 점도 걸린다
(`requirements.txt`).

### 1.3 빠진 연결

| 필요한 것 | 현재 |
|---|---|
| 브라우저에서 로컬 CLI 실행 | 불가능 (`file://` 페이지는 프로세스를 띄울 수 없음) |
| 지도가 최신인지 판단 | 기록이 없어 불가능 |
| 대화창이 현재 보고 있는 뷰·박스를 아는 것 | hash만 있음. 박스를 선택해도 밖으로 알리지 않음 |
| 답변의 `file:line` → 카드로 이동 | 카드 DOM id에 대한 계약이 없음 |

---

## 2. 바꿀 것

핵심 결정은 네 가지다. 세부 사항은 각 결정 아래에 둔다.

### 2.1 [핵심] 채팅은 로컬 서버가 맡고, HTML은 바꾸지 않는다

로컬 서버 `bin/chat_server.py`(표준 라이브러리만 사용)가 지도 HTML을 서빙한다.
서빙할 때 `</body>` 앞에 대화창 조각(`assets/chat-panel.html`)을 **주입**한다.
디스크의 `index.html`에는 대화창이 들어가지 않는다.

| | before | after |
|---|---|---|
| 지도 열기 | `file://…/index.html` | `/arch-explorer:open` → `http://127.0.0.1:<port>/` |
| 대화창 코드 위치 | — | 플러그인의 `assets/chat-panel.html` (서버가 주입) |
| `file://`로 열었을 때 | 지도 | 지도 (변화 없음, 대화창 없음) |
| 0.2.0으로 만든 기존 지도 | — | 다시 빌드하지 않아도 대화창이 붙음 |

**주입 방식을 고른 이유.** build에 대화창 코드를 넣으면 모델이 매번 그 코드를
옮겨 적어야 하고, 대화창을 고칠 때마다 모든 지도를 다시 빌드해야 한다. 주입하면
대화창 버전이 서버 버전을 따라가고, 기존 지도에도 그대로 붙는다.
(앞선 논의에서 나온 "`file://`로 열면 안내 문구 표시"는 여기서 뺀다. 이제 진입점은
open 하나다.)

#### 주입이 동작하는 방식

브라우저는 서버가 보낸 HTML만 받는다. 디스크의 파일이 어떻게 생겼는지는 모른다.
그래서 서버가 보내기 직전에 문자열을 끼워 넣으면, 브라우저 입장에서는 처음부터
대화창이 있던 페이지와 같다.

```
요청 GET /
  1. index.html을 디스크에서 읽는다 (요청마다 읽으므로 재빌드가 바로 반영된다)
  2. 마지막 </body> 앞에 chat-panel.html 내용을 끼워 넣는다
     (</body>가 없으면 문서 끝에 붙인다)
  3. 결과를 응답으로 보낸다. 디스크의 파일은 그대로다
```

대화창 조각은 `<div id="arch-chat-host">`와 `<script>` 하나다. 스크립트가 하는 일은
세 가지다.

| 하는 일 | 방법 | 이게 되는 이유 |
|---|---|---|
| 지도와 겹치지 않게 그리기 | host에 **Shadow DOM**을 붙이고 그 안에 대화창을 그린다 | Shadow DOM 안의 CSS와 바깥 CSS는 서로 영향을 주지 않는다. 지도 CSS는 모델이 매번 다르게 쓰므로, 격리해 두지 않으면 어느 쪽이 깨질지 예측할 수 없다 |
| 지도 상태 읽기 | `MODEL`을 읽고 `arch:view`·`arch:select` 이벤트를 듣는다 (2.5) | 같은 페이지의 스크립트끼리는 전역 변수와 이벤트를 공유한다 |
| 질문 보내기 | `fetch('/api/ask')` | 페이지를 서버가 보냈으므로 같은 출처(same-origin)다. `file://`로 열린 페이지에서는 이 요청이 막힌다 |

대화창이 차지할 자리는 `html`에 오른쪽 padding을 주어 만든다(처음엔 `body` margin이었으나,
contiers 검증에서 `body { width: 100% }`인 지도가 줄어들지 않고 밀려나 바꿨다). 지도가 `100vw`나
`position: fixed; width: 100%`로 화면 전체를 쓰면 이 여백을 무시하고 대화창 밑으로
들어간다. 그래서 build의 렌더 계약에 레이아웃 규칙을 하나 추가한다(2.5).
0.2.0 지도가 이 규칙을 어기면 대화창은 지도 위에 겹쳐 뜬다. 접어 두면 지도를 가리지
않는다.

**서버는 플러그인 안에 두고, 프로젝트로 복사하지 않는다.** 프로젝트마다 복사하면
서버 버전이 제각각 흩어진다. 대신 사용자는 서버를 직접 실행하지 않고 항상
`/arch-explorer:open`으로 연다.

#### 서버 보안

서버가 하는 일은 결국 로컬 에이전트 실행이다. 다른 웹페이지가 이 서버를 부를
수 없어야 한다.

- `127.0.0.1`에만 bind한다.
- `Host` 헤더가 `127.0.0.1:<port>` 또는 `localhost:<port>`가 아니면 거부한다
  (DNS rebinding 방지).
- 기동할 때 무작위 토큰을 만든다. 브라우저는 `/?t=<token>`으로 들어오고, 서버는
  `HttpOnly; SameSite=Strict` 쿠키를 심은 뒤 `/`로 리다이렉트한다. 모든 `/api/*`는
  이 쿠키를 요구한다.
- `POST /api/*`는 `Origin`이 자기 자신일 때만 받는다.
- 모델 답변은 HTML escape한 뒤 제한된 마크다운(링크, 인라인 코드, 코드 블록,
  목록)만 렌더링한다. 저장소 내용에 prompt injection이 들어 있어도 페이지에서
  스크립트가 실행되지 않아야 한다.

#### 엔드포인트

| 경로 | 역할 |
|---|---|
| `GET /` | 지도 HTML + 대화창 주입 |
| `GET /api/status` | 지도·wiki가 최신인지 (대화창 상단 배너용) |
| `POST /api/ask` | `{conversation, question, context: {view, node}}` → NDJSON 스트림 |
| `POST /api/reset` | 대화 초기화 |
| `GET /health` | 재사용 판정용 (토큰 필요) |

#### 기동과 재사용

- 런타임 파일 `$TMPDIR/arch-explorer/<sha1(root+map)>.json`에 `{pid, port, token}`를
  기록한다.
- open은 이 파일의 pid가 살아 있고 `/health`가 응답하면 서버를 새로 띄우지 않고
  브라우저만 연다.
- 포트는 기본값 0(OS가 할당)이고, `--port`로 고정할 수 있다.
- `--stop`으로 종료한다. 서버는 `nohup`으로 띄워 Claude Code 세션이 끝나도 살아
  있다. 로그는 런타임 파일 옆에 남긴다.

### 2.2 [핵심] 답변 엔진: 헤드리스 CLI를 읽기 전용으로

```
POST /api/ask
  └─ EngineAdapter.run(question, context, session_id?)
       ├─ ClaudeAdapter
       │    claude -p --output-format stream-json --verbose
       │           --tools Read,Grep,Glob
       │           --append-system-prompt <규칙>
       │           [--resume <session_id>]
       │    cwd = project root, 질문은 stdin
       └─ CodexAdapter
            첫 질문: codex exec --json --sandbox read-only -C <root> -
            이어서: codex exec resume <session_id> --json
                      -c sandbox_mode="read-only" -
            (codex는 시스템 프롬프트 옵션이 없어 규칙을 첫 메시지 앞에 붙인다)
```

| 항목 | 결정 |
|---|---|
| 엔진 선택 | 아래 "엔진 선택과 기본값 저장" |
| 대화 이어가기 | 서버가 메모리에 `conversation → engine session id`를 유지한다. 서버를 재시작하면 새 대화가 된다 |
| 동시성 | 대화 하나에 질문 하나씩 처리한다. 진행 중에 또 보내면 409 |
| 타임아웃 | 질문당 300초. 넘거나 브라우저 연결이 끊기면 프로세스를 종료한다 |
| 실패 표시 | CLI 종료 코드, stderr 요약, 타임아웃을 대화창에 **그대로** 보여 준다. 빈 답을 성공처럼 표시하지 않는다 |

#### 엔진 선택과 기본값 저장

엔진을 고르는 건 open 스킬이다(서버는 고른 엔진을 인자로 받는다). 사용자에게 묻는 것도
open 스킬이 하고, 답은 사용자 단위 설정 파일에 저장한다.

```
~/.config/arch-explorer/config.json      ($XDG_CONFIG_HOME이 있으면 그 아래)
{ "version": 1, "default_engine": "codex" }
```

| 상황 | 동작 | 저장 |
|---|---|---|
| `--engine=X`를 줌 | X를 쓴다 | 하지 않음 (이번만) |
| 저장된 기본값이 있고 설치돼 있음 | 그 엔진을 쓴다 | — |
| 저장된 기본값이 있지만 설치돼 있지 않음 | 다른 엔진이 있으면 그걸 쓰고 그렇다고 알린다 | 하지 않음 (기본값 유지) |
| 기본값 없음, 둘 다 설치됨 | "어떤 엔진을 기본으로 쓸까요?" | 답을 저장 |
| 기본값 없음, 하나만 설치됨 | 그 엔진을 쓴다 | 하지 않음 (고른 게 아니므로) |
| 둘 다 없음 | 대화창 없이 연다 | — |
| `--reset-engine` | 저장된 기본값을 지우고 위 규칙대로 다시 고른다 | 다시 물으면 저장 |

프로젝트가 아니라 사용자 단위로 저장하는 이유: 어느 CLI를 쓰는지는 사람의 선호다.
저장소마다 다시 물으면 번거롭고, 저장소에 넣으면 팀원에게 강요하게 된다.

#### 시스템 프롬프트

`assets/answer-rules.md`
- `/code-wiki:query`의 2–4단계 규칙을 따른다. wiki가 먼저이고, 소스는 wiki가
  링크한 파일만 열고, 모든 주장에 출처를 붙이고, 모르는 것은 모른다고 한다.
- 답은 **질문한 언어로** 한다. query는 `wiki_language`로 답하지만, 대화창에서는
  한국어로 물었는데 영어로 답하면 어색하다(contiers 검증에서 확인). 코드 이름과 인용
  경로는 원문 그대로 둔다.
- query의 5–6단계(topic 페이지 생성)는 **뺀다**. 채팅은 아무것도 쓰지 않는다.
- 질문마다 컨텍스트를 붙인다. 현재 뷰의 제목, 선택한 박스, 그 뷰의 `ifaces`
  요약이다. "이 박스는 뭐 해?"처럼 대상을 생략한 질문이 여기서 풀린다.
- wiki가 낡았으면 "wiki가 `<sha>` 이후 반영되지 않았다"는 한 줄을 붙여, 답변에서
  그 한계를 밝히게 한다.

### 2.3 [핵심] "최신" 판정: 지도와 wiki를 따로

판정 스크립트 `bin/status.py` 하나를 open 스킬과 서버(`/api/status`)가 같이 쓴다.
출력은 JSON이고, **아무것도 쓰지 않는다**.

#### 지도: build가 사이드카를 남긴다

build가 `index.html` 옆에 `arch-explorer.json`을 쓴다.

```json
{
  "version": 1,
  "sha": "<빌드 시점 HEAD>",
  "scope": ["services/api"],
  "dirty": false,
  "built_at": "2026-09-30T12:00:00Z"
}
```

| 상태 | 조건 | open의 질문 |
|---|---|---|
| `missing` | `index.html`이 없음 | "지도가 없습니다. build 할까요?" |
| `unknown` | 사이드카가 없거나(0.2.0 지도) `dirty: true` | "언제 만든 지도인지 모릅니다. 다시 build / 그대로 열기" |
| `stale` | `git diff --name-only <sha>..HEAD -- <scope>`에서 출력 디렉터리와 `wiki/`를 뺀 결과가 있음 | "지도 이후 N개 파일이 바뀌었습니다. 다시 build / 그대로 열기" |
| `fresh` | 그 외 | 묻지 않음 |

지도를 다시 빌드하는 비용은 크고, 파일이 바뀌었다고 구조가 바뀐 것도 아니다. 그래서
stale일 때 기본값은 **그대로 열기**다. 바뀐 파일 몇 개를 같이 보여 주고 판단은
사용자에게 맡긴다.

#### wiki: code-wiki의 디스크 계약만 읽는다

arch-explorer는 code-wiki 코드를 import하거나 호출하지 않는다. code-wiki가 쓴 파일
(`wiki/config.yaml`, `.code-wiki/state.json` 스키마 v1)을 **읽기만** 한다.

| 상태 | 조건 | open의 질문 |
|---|---|---|
| `no-plugin` | code-wiki 스킬이 설치돼 있지 않음 (open 스킬이 판정) | 설치 명령 안내 → 대화창 없이 열기 |
| `missing` | `wiki/config.yaml`이 없음 | "code-wiki가 없습니다. 만들까요?" → 거절하면 대화창 없이 열기 |
| `unknown` | state 스키마 버전이 다르거나, state가 없고 `wiki/`를 건드린 커밋도 없음 | "wiki 상태를 알 수 없습니다. sync 할까요?" |
| `stale` | 기준 sha 이후 source root 아래 파일이 바뀜 | "wiki 이후 N개 파일이 바뀌었습니다. sync 할까요?" → 거절하면 배너 표시 |
| `fresh` | 그 외 | 묻지 않음 |

- **기준 sha**: `state.json`의 `last_ingested_sha`를 쓴다. state가 없으면 bootstrap과
  같은 방식으로 `git log -1 --format=%H -- wiki/`에서 추론하되, state.json은 쓰지
  않는다.
- **source root**: PyYAML이 있으면 `config.yaml`에서 읽는다. 없으면 `wiki/`를
  제외한 전체를 본다(보수적).
- **판정은 보수적이다**: `ignore_patterns`는 적용하지 않는다. 그래서 무시 대상
  파일만 바뀌었는데 stale로 판정할 수 있다. 이 경우 sync가 "up to date"를 보고하고
  끝나므로 비용은 질문 한 번이다. 반대 방향(낡았는데 최신으로 판정)은 나오지 않는다.
- **커밋되지 않은 변경은 보지 않는다.** code-wiki가 커밋 단위로 동작하기 때문이다.
- **wiki 위치 (0.3.1)**: 기본은 저장소 루트다. 모노레포처럼 하위 프로젝트마다 wiki가
  있으면 `--wiki <dir>`(반복 가능)로 그 디렉터리들을 준다. code-wiki의 경로
  (`source_roots`, 추론용 `wiki/`)는 wiki를 담은 디렉터리 기준이라, git에 묻기 전에
  루트 기준으로 옮긴다. 여러 wiki의 합산 상태는 가장 나쁜 것
  (missing > unknown > stale > fresh)이고 `wikis`에 wiki별 상태가 따로 있다. 루트에
  wiki가 없고 `--wiki`도 없으면 커밋된 `*/wiki/config.yaml`을 `candidates`로 알려
  루트에 새 wiki를 만드는 대신 그것을 쓰자고 묻는다. 엔진에는 `[wikis]` 줄로 위치를
  알린다. 루트 wiki 하나일 때 프롬프트는 이전과 같다.

### 2.4 [핵심] 스킬 흐름: open과 build가 서로를 부른다

```
/arch-explorer:open [map] [--engine=claude|codex] [--reset-engine] [--port=N]
  1. 지도  missing ─ "build?" ─ 예 → build(from=open) → 3번으로 (다시 묻지 않음)
                               └ 아니오 → 종료
           unknown/stale ─ "다시 build / 그대로 열기"
  2. wiki  no-plugin/missing(거절) → chat=off
           missing ─ "만들까요?" ─ 예 → /code-wiki:init → /code-wiki:build
           unknown/stale ─ "sync?" ─ 예 → /code-wiki:sync
  3. 엔진  --engine > 저장된 기본값 > (둘 다 있으면) 묻고 저장. 없으면 chat=off
  4. 서버  재사용 가능하면 재사용, 아니면 기동 → 브라우저 열기
           chat=off면 서버 없이 file://로 연다
  5. 보고  URL, 엔진, 지도·wiki 상태, 종료 방법

/arch-explorer:build
  0. 사이드카가 fresh면 "이미 최신입니다(<sha>). 열기 / 그래도 다시 빌드"
     (from=open이면 건너뜀)
  … 기존 1–4절 …
  5. 사이드카 기록
  6. "열까요?" → open(from=build: 1번 건너뜀)   (from=open이면 묻지 않고 복귀)
```

- **서로 무한히 부르지 않게 한다**: 부른 쪽을 `from=`으로 넘기고, 넘겨받은 쪽은
  확인 질문을 건너뛴다.
- **build는 wiki를 보지 않는다.** wiki는 채팅에만 필요하고, 그건 open이 챙긴다.
- **open은 build SKILL.md를 읽고 따른다.** diff가 이미 이렇게 한다. 스킬 간 호출은
  같은 플러그인 안에서만 한다.
- **code-wiki 호출**은 Skill 도구로 `/code-wiki:init`·`build`·`sync`를 부르는
  것으로 끝낸다. 플러그인 경로에 의존하지 않는다.

### 2.5 [부수] build의 렌더 계약 추가

대화창이 지도와 상호작용하려면 필요한 계약이다. build SKILL.md의 "Interaction
contract"에 추가한다.

| 추가 | 용도 |
|---|---|
| 뷰가 바뀌면 `window.dispatchEvent(new CustomEvent('arch:view', {detail:{view}}))` | 대화창 컨텍스트 |
| 박스를 선택하면 `CustomEvent('arch:select', {detail:{view, node}})` | 대화창 컨텍스트 |
| 카드 요소 id = `card-<viewId>-<ifaceId>` | 답변의 `file:line` → 카드로 이동 |
| `MODEL`은 top-level `const` 유지 (이미 그렇다) | 대화창이 `ifaces[].items[].ref`와 대조 |
| `html`·`body`에는 폭을 주지 않고, 안쪽은 부모 기준(`100%`)으로 잡는다. `100vw` 금지 | 대화창 자리를 내줄 수 있게 (2.1 주입 방식) |
| hash는 viewId 그대로, `MODEL`은 classic script의 top-level `const`, `ref`는 `path:line` 하나 | 대화창이 뷰·모델·인용을 읽을 수 있게 |

0.2.0 지도에는 이벤트가 없다. 이때 대화창은 hash만으로 뷰를 알고, 선택한 박스는
모른다. 동작은 하지만 기능이 줄어든다.

### 2.6 [부수] 대화창 UI

- 오른쪽 패널(380px)이고 접을 수 있다. Shadow DOM 안에 그린다(2.1). 좁은 화면에서는
  지도 위에 겹친다.
- 입력창 위에 현재 컨텍스트 칩("worker › Scheduler")을 보여 준다. 칩을 눌러
  컨텍스트를 뺄 수 있다.
- 상단 배너는 `/api/status` 결과로 채운다. wiki가 낡았다, 지도가 낡았다, 엔진 이름.
- 답변의 `path:line`이 `MODEL`의 ref와 맞으면 카드로 이동하는 링크가 된다. 맞지
  않으면 코드 텍스트로 둔다. (파일 내용을 보는 기능은 이번 범위에서 뺀다.)
- "새 대화" 버튼이 `/api/reset`을 부른다.

---

## 3. 구현 순서와 검증

변경 파일 요약:

```
claude/skills/arch-explorer/
├── skills/build/SKILL.md     수정: 0·5·6절, 렌더 계약 (2.4, 2.5)
├── skills/open/SKILL.md      신규 (2.4)
├── bin/status.py             신규 (2.3)
├── bin/chat_server.py        신규 (2.1, 2.2)
├── assets/chat-panel.html    신규 (2.6)
├── assets/answer-rules.md    신규 (2.2)
├── tests/                    신규 (unittest, 표준 라이브러리)
├── README.md                 수정: open 절, 보안 주의
└── .claude-plugin/plugin.json  0.3.0
.claude-plugin/marketplace.json  설명 갱신
```

| # | 단계 | 검증 |
|---|---|---|
| 1 | `bin/status.py` + 엔진 기본값 설정 파일 읽기/쓰기 | 임시 git 저장소 fixture로 지도 4상태 × wiki 5상태. PyYAML이 있을 때·없을 때. **판정 후 작업 트리와 `.code-wiki/`가 그대로인지** 확인 |
| 2 | build SKILL.md 개정 | 실제 저장소 하나로 build → 사이드카 생성, 이벤트 발생, 카드 id 확인. 다시 build하면 "이미 최신" 질문이 나오는지 |
| 3 | `chat_server.py` 서빙·보안 | 가짜 엔진으로 테스트: 토큰 없음·잘못된 Origin·잘못된 Host → 거부. 주입 위치(`</body>` 있음/없음/여러 개), 주입 후에도 디스크의 파일이 그대로인지. `/health`로 재사용 |
| 4 | 엔진 어댑터 | PATH에 **가짜 `claude`/`codex` 스크립트**를 두고 스트림 파싱·resume 인자·타임아웃 kill·비정상 종료 표시를 테스트한다. 이어서 **실제 CLI로 한 번씩** 질문 두 개(두 번째는 resume)를 돌리고, 파일을 쓰라는 질문이 거부되는지 확인한다. 가짜 CLI 테스트 통과를 실제 실행 검증으로 치지 않는다 |
| 5 | `chat-panel.html` | 새 지도와 0.2.0 지도에서 각각 컨텍스트 칩, 카드 링크, 배너, 서버가 끊겼을 때 표시 |
| 6 | open SKILL.md | 시나리오별로 직접 실행: 지도 없음 → build → 열림(추가 질문 없음) / wiki 없음 → 거절 → 대화창 없이 열림 / wiki stale → sync / 이미 떠 있는 서버 재사용 / 엔진 없음 / 엔진 둘 다 있고 기본값 없음 → 묻고 저장 → 다음 실행에서는 묻지 않음 / `--reset-engine` |
| 7 | 문서·버전 | README에 흐름, `--stop`, 보안 모델. plugin 0.3.0 |

1과 3은 서로 독립이라 먼저 병렬로 진행할 수 있다. 2가 끝나야 5의 새 지도 검증이
가능하다.
