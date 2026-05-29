"""거버넌스 사전공약 (constitutional pre-commitment) — critique §3.

급소: 발행 규칙·"기여" 정의·AI 분류기를 쥔 자가 새 지배계급이 된다. 부트스트랩
단계에서는 불가피하게 한 사람(Json)이 모든 규칙을 쥔다 — 권력이 가장 집중된
시점이 통제 장치가 가장 없는 시점이다. "나중에 분권하겠다"는 모든 중앙집권의
약속이었다(트로츠키의 관료화 경고).

해법은 신뢰가 아니라 **메커니즘**: 분권을 *나중*이 아니라 *발행 규칙에 미리
박아둔다.* 참여자가 임계 N명에 도달하면, 규칙 변경권이 단일 관리자에서
합의체(council)로 **자동 이전**된다. 코드가 헌법이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Phase(str, Enum):
    BOOTSTRAP = "bootstrap"      # 단일 관리자가 규칙을 정함 (불가피)
    DECENTRALIZED = "decentralized"  # 합의체가 규칙을 정함 (자동 이전됨)


class GovernanceError(Exception):
    pass


@dataclass
class Governance:
    """규칙 파라미터 + 변경 권한의 단계적 이전.

    부트스트랩 동안 ``admin`` 이 단독으로 규칙을 바꿀 수 있으나, ``participants``
    가 ``decentralize_at`` 에 도달하는 순간 :class:`Phase` 가 자동으로
    ``DECENTRALIZED`` 로 넘어가고, 이후 변경은 합의체 과반 승인을 요구한다.
    """

    admin: str
    decentralize_at: int = 100
    council_quorum: float = 0.5  # 합의체 과반
    rules: dict[str, float] = field(default_factory=dict)
    participants: set[str] = field(default_factory=set)
    council: set[str] = field(default_factory=set)
    log: list[str] = field(default_factory=list)

    @property
    def phase(self) -> Phase:
        return (
            Phase.DECENTRALIZED
            if len(self.participants) >= self.decentralize_at
            else Phase.BOOTSTRAP
        )

    def register(self, participant: str) -> Phase:
        """참여자를 등록한다. 임계 도달 시 자동 분권을 기록한다."""
        was = self.phase
        self.participants.add(participant)
        now = self.phase
        if was is Phase.BOOTSTRAP and now is Phase.DECENTRALIZED:
            self.log.append(
                f"AUTO-DECENTRALIZE: {len(self.participants)} participants reached "
                f"{self.decentralize_at}; rule-change power -> council"
            )
        return now

    def seat_council(self, members: set[str]) -> None:
        """합의체 구성원을 지정한다 (전원 참여자여야 함)."""
        unknown = members - self.participants
        if unknown:
            raise GovernanceError(f"council members not registered: {unknown}")
        self.council = set(members)

    def set_rule(self, key: str, value: float, *, by: str) -> None:
        """부트스트랩 단계: 관리자만 단독 변경 가능."""
        if self.phase is not Phase.BOOTSTRAP:
            raise GovernanceError(
                "decentralized: use propose_rule()/vote(); admin cannot set unilaterally"
            )
        if by != self.admin:
            raise GovernanceError(f"only admin {self.admin!r} may set rules in bootstrap")
        self.rules[key] = value
        self.log.append(f"[bootstrap] {by} set {key}={value}")

    def change_rule_by_consensus(
        self, key: str, value: float, approvals: set[str]
    ) -> None:
        """분권 단계: 합의체 과반 승인이 있어야 변경."""
        if self.phase is not Phase.DECENTRALIZED:
            raise GovernanceError("still bootstrap: use set_rule()")
        if not self.council:
            raise GovernanceError("no council seated")
        valid = approvals & self.council
        if len(valid) < self.council_quorum * len(self.council):
            raise GovernanceError(
                f"quorum not met: {len(valid)}/{len(self.council)} "
                f"(need > {self.council_quorum:.0%})"
            )
        self.rules[key] = value
        self.log.append(
            f"[council] {key}={value} via {len(valid)}/{len(self.council)} approvals"
        )

    def get_rule(self, key: str, default: float = 0.0) -> float:
        return self.rules.get(key, default)
