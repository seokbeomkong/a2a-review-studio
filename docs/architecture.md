# 구조와 프로토콜 범위

## 호출 흐름

브라우저는 `POST /api/runs`로 검토를 시작하고 `GET /api/runs/{id}`로 상태를 확인한다. Orchestrator는 세 전문가에게 초안 작성 요청을 동시에 보낸다. 다음 단계에서는 각 전문가에게 수정 요청을 보낸다. 수정 중 전문가는 나머지 두 전문가에게 초안에 대한 피드백을 요청한다. 피드백 단계는 다른 전문가를 다시 호출하지 않으므로 순환 요청이 생기지 않는다.

피드백을 받은 전문가는 초안을 수정하고, Orchestrator는 결과를 종합한다. 초기 단계는 세 전문가, 피드백 단계는 여섯 개의 방향을 가진 메시지로 구성된다. 이는 제한된 한 차례의 Full Mesh 피드백이며 무한 합의 알고리즘은 아니다.

## A2A 경계

| 엔드포인트 | 역할 |
|---|---|
| `/agents/technical/.well-known/agent-card.json` | 기술 전문가 카드 |
| `/agents/business/.well-known/agent-card.json` | 비용 전문가 카드 |
| `/agents/user/.well-known/agent-card.json` | 사용자 전문가 카드 |
| `/agents/{name}/` | A2A 1.0 JSON-RPC `SendMessage` |

사용 SDK: `a2a-sdk==1.1.5`. Agent Card에서 `protocolVersion=1.0`, `protocolBinding=JSONRPC`를 선언한다. 클라이언트가 카드의 주소를 허용된 루프백 주소와 비교한 뒤 SDK 클라이언트를 생성한다. UI에서 보이는 메시지 ID는 실제 SDK가 보낸 Message의 ID다. 요청·응답 기록은 HTTP 전후의 메시지 객체를 직렬화한 것이며 원시 TCP 패킷 캡처가 아니다.

### 지원 범위

- Agent Card 조회, 인증된 `SendMessage`, 비스트리밍 Message 응답.
- 텍스트 파트에 `AgentJob` JSON 전달. 결과는 `{ok, content, feedback}` 또는 `{ok:false, error}`의 앱 계약.
- 작업 실패는 앱 결과의 `ok:false`로 표현한다. 장기 실행 A2A Task 상태 변경으로 표현하지 않는다.
- SDK의 InMemoryTaskStore는 핸들러 구성에 사용하지만 앱 자체는 장기 Task를 생성하지 않는다.
- A2A 스트리밍·Task 취소·push notification·외부 Agent 자동 검색·다중 프로세스 배포는 미지원.
- A2A 카드와 버전을 따른다는 의미이지 전 명세의 독립 적합성 인증을 받았다는 의미는 아니다.

인증 헤더는 `x-studio-agent-token`이며 서버 시작 시 무작위로 생성한다. 카드에 API key 보안 요구를 선언한다. 토큰은 브라우저용 API에서 제공하지 않는다. 인증이 필요한 실제 SDK 호출은 `tests/test_workflow.py`의 로컬 통합 테스트에서 실행할 수 있다. 이 프로젝트는 외부 서비스가 가입하는 공개 Agent 플랫폼이 아니다.

## 실행 상태와 오류

- `running`: draft → feedback → synthesize.
- `completed`: 세 전문가의 검토와 피드백, 종합까지 성공.
- `partial`: 일부 호출 실패, 또는 시간 초과 전에 유효한 검토가 확보된 상태. 종합 결과가 없을 수도 있다.
- `failed`: 유효한 검토 결과 없이 실패.

시간 초과 후 추가 종합을 시작하지 않는다. 전문가 요청에도 남은 실행 기한을 적용한다. 모델 API 요청에는 35초 타임아웃이 있다. SDK 클라이언트 타임아웃은 중첩 피드백을 고려해 110초이며, 전체 실행은 180초로 제한한다.

결과는 run ID별로 분리한다. 별도 DB와 영구 기억은 없으며 사용자 자료를 디스크에 자동 저장하지 않는다. 다운로드는 사용자가 선택한 파일로 저장한다. 1시간이 지난 완료 결과는 다음 조회/생성 시 정리되며, 새 실행 시 최대 50개를 초과하면 오래된 완료 결과를 제거한다.

## UI와 데이터 처리

프런트엔드는 프레임워크 없는 HTML/CSS/JS이다. 폴링으로 실행 상태를 갱신하고, 모든 입력·모델 결과·메시지 기록을 textContent로 렌더링한다. 코드 실행이나 모델 제공 HTML 삽입 기능은 없다. sessionStorage는 실행 ID만 저장해 새로고침 때 진행 중 결과를 복원한다. 일시적 연결 오류에서는 ID를 보존하며 확인된 404에만 삭제한다.

## 구현 선택

공식 A2A SDK와 Claude Messages API 연결을 사용했다. 이번 목적은 표준 통신 경계와 피드백 흐름을 작고 읽기 쉬운 코드로 설명하는 것이므로 별도 Agent 프레임워크, 벡터 DB, 도구 실행 계층은 추가하지 않았다.
