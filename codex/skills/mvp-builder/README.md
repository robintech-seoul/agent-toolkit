# MVP-Builder for Codex

아이디어를 **스펙 → 승인 → 설계·리뷰 루프 → 승인 → 구현·검증**으로 실행하는 Codex 플러그인이다. Claude MVP-Builder **0.4.2**의 기능을 이식했다. Codex판 버전은 **0.1.0**이다.

Python 프로그램이 상태, 승인, 반복 예산, 발견 원장, 산출물 저장과 최종 판정을 관리한다. 각 AI 노드는 실제 `codex exec` 프로세스로 실행한다. 대화 중인 부모 에이전트가 노드를 대신 수행하지 않는다.

## 설치

Python **3.10 이상**, Codex CLI와 로그인이 필요하다. macOS/Linux를 대상으로 하며 Windows는 WSL을 사용한다. 구현된 프로젝트에 따라 Node/npm 또는 Python/pytest가 추가로 필요하다.

저장소의 이 변경이 포함된 로컬 체크아웃으로 설치한다:

```bash
codex plugin marketplace add /absolute/path/to/agent-toolkit
codex plugin add mvp-builder@robintech-codex
```

게시 후에는 저장소 주소를 마켓플레이스 소스로 사용할 수 있다. Claude의 `robintech` 카탈로그와 Codex의 `robintech-codex` 카탈로그는 같은 저장소에 공존한다. 재설치 후 새 Codex 작업에서 플러그인의 `start`, `approve`, `reject`, `status` 스킬을 선택한다. 네 스킬은 명시적 호출용이다.

## 직접 실행

설치하지 않고 체크아웃에서도 실행할 수 있다. `pipeline.py`는 대상 프로젝트와 다른 위치에 둔다.

```bash
# 실제 경로로 지정
mvp_program=/absolute/path/to/agent-toolkit/codex/skills/mvp-builder/bin/pipeline.py
mvp_project=/absolute/path/to/new-project
mkdir -p "$mvp_project"

python3 "$mvp_program" --project "$mvp_project" start --lite '팀 회고를 모으는 웹앱'
python3 "$mvp_program" --project "$mvp_project" status
# 생성된 SPEC.md를 읽고 승인
python3 "$mvp_program" --project "$mvp_project" approve
# 생성된 DESIGN.md와 리뷰 결과를 읽고 승인
python3 "$mvp_program" --project "$mvp_project" approve
```

반려는 현재 단계로 돌아간다:

```bash
python3 "$mvp_program" --project "$mvp_project" reject '로그인 없는 사용자의 접근 범위를 명확히 해줘'
```

여러 줄 입력이나 셸 특수문자는 UTF-8 파일로 전달한다. `start --idea-file idea.txt`, `reject --reason-file feedback.txt`를 지원한다. 입력을 실행할 셸 명령에 직접 보간하지 않는다.

## 옵션

| 옵션 | 동작 |
|---|---|
| `--full` / `--lite` / `--skills full\|lite` | 내장 상세 프롬프트 / 짧은 프롬프트. 기본 full |
| `--mode build\|design` (`--design`) | 구현까지 / 하이레벨 설계와 하위 프로젝트 분해까지만. 기본 build |
| `--fast` / `--profile NAME` | `policy/profiles.tsv`의 노력 수준·반복 예산. 기본 standard |
| `--model MODEL` / `--effort LEVEL` | 명시적 Codex 모델·추론 노력 설정. 기본 사용자 Codex 설정 |
| `--auto-approve` | 기계 게이트를 통과한 스펙·설계를 자동 승인. 기본은 사람 승인 |
| `--timeout SECONDS` | AI 호출 및 테스트 명령별 시간 상한. 기본 900초 |

standard: 설계 최대 2회, 리뷰 최대 5회, 동일 must ID 집합 정체 2회, 구현 최대 3회.
fast: 설계 최대 1회, 리뷰 최대 1회, 정체 1회, 구현 최대 2회, 노력 low. **모델은 강제로 바꾸지 않는다.** 정책의 `model` 키나 `--model`로 명시할 수 있다.

자동 승인은 단순 무조건 승인이 아니다. 스펙은 수용 기준 ID가 있어야 하고, 설계는 모든 ID 반영과 리뷰 must 0이 필요하다. design 모드는 하위 프로젝트 분해도 통과해야 한다. 판정 불가·미달은 승인 대기로 남는다. 사람은 남은 must가 있는 설계를 검토 후 명시적으로 승인할 수 있지만, 판정 불가나 누락된 ID는 반려·수정해야 한다.

## 프로그램과 AI의 역할

| 작업 | 실행 주체 |
|---|---|
| 단계 선택·승인 대기·상태와 원장 기록 | Python 프로그램 |
| 스펙·설계·계획 작성 | 읽기 전용 Codex 호출 → 문서 JSON 반환 → 프로그램 저장 |
| 전체/델타 리뷰 | 읽기 전용 Codex 호출 → JSON 스키마 및 원장 참조 검증 |
| 설계 수정 | Codex가 전체 수정 문서 반환 → 프로그램 저장 및 diff 생성 |
| 구현 | 별도 프로젝트 복사본에서 workspace-write Codex 실행 |
| 구현 반영 | 프로그램이 계약·상태·심볼릭 링크 검사 후 변경 파일 반영 |
| 완료 게이트 | 프로그램이 구현 복사본을 유지해 테스트 실행, 소스·테스트·ID·계약 검사 |

전체 리뷰 후 발견에는 `L-001` 등의 ID를 프로그램이 발급한다. 수정자의 `claimed`는 해결이 아니다. 다음 리뷰어가 열린 must 각각을 판정한 뒤에만 `resolved`가 된다. 같은 ID 집합이 남는 교착과 라운드 예산 소진을 구분한다. 반려 후 기존 설계 수정본과 원장·리뷰 라운드가 유지된다.

## 산출물

```text
대상 프로젝트/
├── SPEC.md
├── DESIGN.md
├── tasks/todo.md
├── ... 실제 구현과 테스트
└── .mvp/
    ├── state.json             # 현재 단계·옵션·라운드·이력
    ├── lock                   # 중복 실행 방지
    ├── approved/              # 승인 계약 스냅샷
    ├── ledger.jsonl           # 코드가 기록한 리뷰 원장
    ├── design-check*.json
    ├── design-diff-latest.txt
    ├── review-r*.json
    ├── triage.md
    ├── decompose-check.json   # design 모드
    ├── build-check.json
    ├── test.log
    └── calls/<시간>-<단계>/
        ├── request.json       # 실제 명령 인자와 프롬프트
        ├── events.jsonl       # Codex 원시 이벤트
        ├── response.json      # 최종 구조화 응답
        ├── stderr.log
        ├── execution.json
        └── changes.json       # 구현 반영 목록
```

`.mvp`에는 작업 프롬프트와 코드 관련 로그가 있으므로 공유 전에 검토한다. API 인증 정보를 여기에 넣지 않는다. 완료 상태는 `built` 또는 설계 전용 `designed`다. 승인 대기나 `build_incomplete`를 완료로 표현하지 않는다.

## Claude판과의 차이 및 제한

- `commands/*.md` 대신 Codex 스킬을 제공한다. 실행기 내부는 표준 라이브러리 Python으로 통합했다. 기존 Claude 실행 코드는 그대로 유지한다.
- Claude `--append-system-prompt`를 흉내내지 않는다. 단계 지시와 작업 입력을 stdin으로 조립하며 Codex의 지시 우선순위를 따른다.
- Claude `permissions.deny`와 같은 파일별 권한을 주장하지 않는다. 문서/리뷰는 read-only, 구현은 복사본+검증 후 반영이다. Codex의 sandbox/승인 정책을 우회하지 않는다.
- `.git`, `.mvp`, 에이전트 설정, `.env*`, 가상환경·node_modules는 구현 복사본에서 제외한다. 외부 디렉터리·추가 서비스가 필요한 프로젝트는 환경 준비가 필요하다. 심볼릭 링크 프로젝트는 현재 지원하지 않는다.
- 테스트 명령은 구현에 사용한 복사본에서 로컬 실행한다. 구현 노드가 설치한 의존성은 검사까지 유지하며, 검사가 끝나면 복사본과 함께 정리한다. 산출물 프로젝트에서 다시 실행하려면 그 프로젝트의 의존성을 설치한다. **복사본은 적대적인 테스트 코드에 대한 OS 보안 샌드박스가 아니다.** 신뢰하지 않는 생성 코드를 실행할 때는 별도 컨테이너/VM에서 전체 프로그램을 실행한다.
- 자동 테스트 선택: package.json → npm test, pyproject.toml/pytest.ini → pytest, 그 밖의 Python 테스트 → unittest discover. 현재 완료 게이트는 Python/JS/TS 계열을 대상으로 한다. 이외 스택은 게이트 확장이 필요하다.
- ID 등장 검사는 추적 누락 검사이며 의미적 정확성의 증명이 아니다. 소스·테스트 파일과 실제 테스트 성공을 추가로 검사하지만 테스트 품질을 완전히 증명하지는 않는다.
- 프로세스가 비정상 종료된 뒤 임의 지점에서 재개하는 기능은 없다. `status`와 로그로 진단한다. 기존 상태가 있으면 `start`는 덮어쓰지 않는다. 새 실행은 새 프로젝트 디렉터리를 사용한다.
- Claude의 `.mvp`와 Codex의 `.mvp`를 같은 실행 디렉터리에서 섞지 않는다. 이력 형식은 Codex판 고유이며 기존 Claude 실행의 중간 이식은 지원하지 않는다.
- 모델·인증·제품별 CLI 설정은 사용자 환경을 따른다. `full`과 `lite`도 동일한 생성 결과를 보장하지 않는다. 토큰은 원시 이벤트를 보존하고, 제공되지 않는 실제 달러 비용은 만들지 않는다.

## 개발·검증

```bash
python3 -m unittest discover -s codex/skills/mvp-builder/tests -v
```

테스트의 CLI 대역(`tests/fake_codex.py`)은 모델 호출 없이 상태·실패·계약 보호를 검사한다. 실제 Codex 검증과 구분한다. `MVP_CODEX_BIN`은 테스트 또는 래퍼용 실행 파일 경로이며 기본은 PATH의 codex다.

검증 결과와 실제 실행 범위는 [VALIDATION.md](VALIDATION.md)에 기록한다.

## 원본과 라이선스

원본: [Claude MVP-Builder 0.4.2](../../../claude/skills/mvp-builder), 기준 커밋 `e8204973658f396052f8ec7d43cabc4a509063e7`.
`prompts/full/`의 agent-skills 원문과 MIT LICENSE를 보존했다. Codex용 지시 전달 방식, 누락된 하이레벨 설계 프롬프트와 테스트 러너 안내를 보완했다. 저장소 전체의 별도 라이선스를 임의로 추가하지 않는다.
