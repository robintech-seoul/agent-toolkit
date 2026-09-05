---
description: 지금 대기 중인 단계를 승인하고 다음 단계를 실행한다
allowed-tools: Bash(bash:*)
---

현재 대기 중인 승인 게이트를 통과시킨다.

!`bash "${CLAUDE_PLUGIN_ROOT}/bin/approve.sh"`

위 결과를 정리해 전달해라. 루프가 돌았다면 **라운드별 숫자**(설계 반영률, must 추이)를
표로 보여주고, 다음 승인 게이트가 있으면 무엇을 확인해야 하는지 알려라.
