# Codex support

Codex용 도구는 기존 `claude/`와 나란히 관리한다. 범용 스킬 묶음은 `skills/`, 제품 전용 도구는 추가될 때 `plugins/`에 둔다.

현재 제공 대상은 [MVP-Builder](skills/mvp-builder/README.md)다. arch-explorer, code-wiki, robin-cloud-onboarding의 Codex판은 이 변경에 포함되지 않는다.

로컬 체크아웃에서:

```bash
codex plugin marketplace add /absolute/path/to/agent-toolkit
codex plugin add mvp-builder@robintech-codex
```

카탈로그는 루트 `.agents/plugins/marketplace.json`, 플러그인 선언은 `codex/skills/mvp-builder/.codex-plugin/plugin.json`이다. 플랫폼별 메타데이터를 혼용하지 않는다. 현재 설치 명령은 로컬 체크아웃에서 검증했다. 게시 전 원격 main에 Codex판이 있다고 가정하지 않는다.

플러그인을 업데이트·재설치한 뒤 새 Codex 작업에서 스킬 목록을 확인한다. 직접 Python 실행도 지원한다.
