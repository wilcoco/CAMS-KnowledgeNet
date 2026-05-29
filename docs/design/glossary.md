# 핵심 용어 (Glossary)

| 용어 | 정의 | 코드 위치 |
|------|------|----------|
| **허브 지수 (Hubness)** | 평가자의 안목 — 좋은 것을 *먼저* 알아본 능력. 인기가 아니라 선행 발견력. | `scoring.ScoreEngine.hub` |
| **권위 지수 (Authority)** | 콘텐츠의 가치 — 좋은 허브들에게 인정받은 정도. | `scoring.ScoreEngine.authority` |
| **링크 순서 가중** | 수렴 반복연산을 시간 순서로 치환. 먼저 링크할수록, 이후 링크가 쌓일수록 허브 증가. 증분 갱신으로 실시간 산출. | `scoring.ScoreEngine.link` |
| **노드 (Node)** | 최소 단위 = 인간 질문 + AI 답변 쌍. 질문=안목(산 노동), 답=재료(죽은 노동). | `tree.Node` |
| **계승 (Follow)** | 동의/따라가기. 같은 가지를 길게 함. 소액·기여 불필요·부가가치 없음. | `tree.OntologyTree.follow` |
| **포크 (Fork)** | 같은 질문에 다른 답을 내는 분기. 단순 반대표가 아니라 **입증 책임을 진 주장**. | `tree.OntologyTree.fork` |
| **추가 기여 (Contribute)** | 맥락·반박·정보 링크·온톨로지 추가. 그 자체가 노드. | `tree.OntologyTree.contribute` |
| **잠복 (Dormant) 가지** | 후속이 안 붙어 멈춘 가지. **삭제되지 않고** 부활 대기 (갈릴레오 문제). | `tree.NodeStatus.DORMANT` / `revive` |
| **포인터 (Pointer)** | 답이 아니라 단서("X가 안다"). 처음부터 잠복. | `tree.Action.POINTER` |
| **부가가치 게이트** | 빈손 동의 노드는 배당 흐름이 **우회**. 폰지와 정당한 지대를 가르는 선. | `economy.Economy.distribute_dividend` |
| **스테이킹 (Staking)** | 받은 포인트를 기여와 함께 묶는 것 = "기여에 묶인 확신". | `economy.Ledger.stake` |
| **배당 (Dividend)** | 후입 포인트가 앞선 기여자에게 흐름. 256 시간가중 = 선행 발견 보상. | `economy.Economy.distribute_dividend` |
| **현상금 (Escrow)** | 표적 호출에 건 에스크로. 채택 시 지급, 미채택 시 반환. | `economy.Ledger.open_escrow` |
| **소각 싱크 (Burn)** | UBI 인플레 방어용 디플레 장치. | `economy.Ledger.burn` |
| **색인 재고 (Index inventory)** | 검색에 걸려 갖다 쓰이는, 흔하고 대체 가능한 콘텐츠. (네이버 모델의 본질) | — |
| **암묵지 (Tacit knowledge)** | 형식화되지 않은, 체화된 지식 (폴라니: "말할 수 있는 것보다 많이 안다"). | — |
| **외부 현실 닻 (Ground truth)** | "부가가치=동의"의 순환을 닫는 유일한 외부 검증 (제조: 수율·물성). | `docs/roadmap.md` §검증 닻 |
