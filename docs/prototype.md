# 프로토타입 매핑 (설계 ↔ 코드)

MVP는 **메커니즘 증명용**이다. 영속성·동시성·실제 LLM은 없다(로드맵 P3). 대신
설계의 *불변식*을 코드와 테스트로 못박는다. 아래는 설계 개념 → 코드 1:1 대응.

---

## 모듈 지도

```
src/nightwish/
├── scoring.py       특허 256 증분 허브/권위 엔진 (링크 순서 가중)
├── tree.py          살아있는 온톨로지 트리 (노드·계승·포크·기여·잠복/부활)
├── economy.py       닫힌 포인트 경제 (UBI·스테이킹·배당 게이트·시간붕괴·잠복회수·에스크로·소각)
├── verification.py  외부 현실 닻 (제조 수율/물성 측정 → 검증된 가지에서만 배당)  [P0]
├── governance.py    거버넌스 사전공약 (참여자 N명 시 규칙변경권 자동 분권)        [P1]
├── pipeline.py      3단계 질의 흐름 (검색→AI→사람)
└── simulation.py    §7 "첫 바퀴" 재현 + §7.2 병목 시연
```

---

## 개념 대응표

| 설계 개념 (§) | 코드 | 핵심 불변식 / 테스트 |
|--------------|------|---------------------|
| 링크 순서 가중, 수렴 없는 증분 (§3.2) | `ScoreEngine.link` | 먼저 링크한 자가 허브 더 큼; 밴드왜건 늦은 가담은 ≈0 → `test_scoring.py` |
| 안목(허브) vs 콘텐츠 가치(권위) (§3.2) | `ScoreEngine.hub` / `.authority` | 고-허브의 추천이 더 큰 권위 부여 → `test_authority_accumulates...` |
| 노드 = 인간Q + AI답 (§4.1) | `tree.Node(question, answer)` | `question`=안목, `answer`=재료 |
| 계승(소액·기여불필요) (§4.2) | `OntologyTree.follow` | `value_add=False` → `test_follow_is_not_value_add` |
| 포크(입증책임·죽이지 않음) (§4.3) | `OntologyTree.fork` | 부모 ACTIVE 유지, 새 가지 → `test_fork_creates_competing_branch...` |
| 추가 기여 (§4.2) | `OntologyTree.contribute` | 그 자체가 노드 |
| **포인트 크기 = 기여 크기** (§4.4) | `OntologyTree._check_stake_rule` | 큰 스테이킹+기여없음 → 거부 → `test_large_stake_without_contribution_is_rejected` |
| 죽지 않는 가지 / 잠복·부활 (§4.5) | `NodeStatus.DORMANT`, `sweep_dormant`, `revive` | 잠복은 삭제 아님; 후대가 부활 → `test_sweep_and_revive_dormant_branch` |
| 포인터(답 아님) (§7) | `Action.POINTER`, `add_pointer` | `is_answer=False`, 처음부터 DORMANT |
| 신규자 벤처 메뉴 (§4.6) | (토대) `Action.POINTER`/dormant 노출 | 로드맵 거버넌스에서 라우팅 쿼터로 확장 |
| UBI 발행 (§5.1) | `Economy.issue_ubi` | 평면 분배 → `test_ubi_issuance_is_flat` |
| 스테이킹(기여에 묶인 확신) (§5.1) | `Ledger.stake` | 가용→잠금 이동 → `test_staking_moves_available_to_locked` |
| 배당 시간가중(선행 보상) (§5.2) | `Economy.distribute_dividend` | 더 오래된 조상이 더 큰 몫 → `test_dividend_time_weight...` |
| **부가가치 게이트(빈손 우회)** (§5.2-3) | `distribute_dividend` (value_add 필터) | 빈손 노드는 배당 못 받음 → `test_dividend_bypasses_empty_agree_node` |
| 현상금 에스크로(미채택 반환) (§7) | `Ledger.open_escrow`/`return_escrow`/`release_escrow` | 미채택 시 반환 → `test_escrow_returned_when_not_adopted` |
| 소각 싱크(인플레 방어) (§5.5) | `Ledger.burn`, `Economy.burn_rate` | 공급 감소 → `test_burn_reduces_supply` |
| 3단계 질의(검색→AI→사람) (§6) | `QueryPipeline.ask` | 단계 전이 → `test_simulation.py` |
| 암묵지 병목(③ 미해결) (§7.2) | `Stage.UNRESOLVED` | 깊은 암묵지 질의 → UNRESOLVED → `test_bottleneck_deep_tacit_query_is_unresolved` |
| 첫 바퀴 원장 (§7) | `simulation.build_first_wheel` | Json 900/100, B 10, C 50 일치 → `test_first_wheel_final_ledger_matches...` |

---

## 2차 이터레이션 — 비평이 지목한 균열을 코드로 닫음

| 설계 개념 (출처) | 코드 | 핵심 불변식 / 테스트 |
|------------------|------|---------------------|
| **외부 현실 닻** — 검증된 가지에서만 배당 (P0 / 비평 §1.1, §2) | `verification.*`, `Economy.distribute_dividend(is_verified=...)` | 검증 전 0, 검증 후 개통(가지 단위) → `test_verification.py`, `examples/verified_wheel.py` |
| **배당 시간붕괴** — 갱신 안 된 지분 수익률 0 수렴 (비평 §1.3) | `distribute_dividend(ages=, half_life=)` | 오래된 지분 가중 붕괴 → `test_economy_v2.py::...time_decay` |
| **잠복 포인트 회수 ↔ 가지 보존 분리** (비평 §1.2) | `Economy.reclaim_dormant` / `restore_on_revival` | 소각 아닌 유동성 풀 환원, 부활 시 복원+발견보너스 → `test_economy_v2.py` |
| **거버넌스 자동 분권 사전공약** (비평 §3) | `governance.Governance` | 참여자 N명 → 규칙권 합의체로 자동 이전 → `test_governance.py` |

---

## 아직 코드에 없는 것 (의도적 — 로드맵으로)

| 설계 개념 | 왜 미구현 | 어디서 |
|----------|----------|--------|
| 실제 검색(임베딩)·실제 LLM | stub로 주입 (`pipeline`의 `*_fn`) | 로드맵 P3 |
| 영속성(DB)·동시성 원자성 | 인메모리 MVP | 로드맵 P3 |
| 시빌/담합 저항 (정체성 계층) | 동의 담합 = 시빌의 경제 버전 | 로드맵 P3 |
| 포인트 외부 환전 정책 | 정책 결정(거버넌스) 선행 필요 | 로드맵 P1 / AskUser |

---

## 실행

```bash
pip install -e .
python -m nightwish.simulation      # §7 첫 바퀴 리포트
python examples/dividend_demo.py    # 부가가치 게이트 배당 라우팅
python examples/verified_wheel.py   # [P0] 검증 닻이 배당을 여는 첫 바퀴
python -m pytest -q                 # 47개 테스트
```

> 설계의 약점은 숨기지 않았다. 코드가 증명하는 것은 *메커니즘이 의도대로
> 작동한다*는 것이고, [`critique.md`](critique.md)가 말하는 것은 *그 메커니즘조차
> 외부 현실 닻 없이는 부족하다*는 것이다. 둘 다 사실이다.
