"""검증 닻이 배당을 여는 첫 바퀴 (로드맵 P0 / critique §1.1, §2, §6).

설계의 핵심 자기진단: "부가가치=동의"의 순환은 외부 현실로만 닫힌다. 이 데모는
제조 도메인의 실제 과제 하나를 트리에 올리고, **물성 측정으로 검증되기 전에는
배당이 0**, 검증된 뒤에야 흐름이 열리는 것을 보여준다.

시나리오:
  #F-001  공장 과제: 웰드라인 불량률 8% (루트, Json 기여)
  #F-002  수정 제안: 게이트 위치 변경 + 금형온도 +15도 (User-D 기여)
  측정    불량률 8.0% -> 2.0% (75% 개선) -> 검증 통과
  #F-003  후속 스테이킹 (검증된 가지에 신규 투자 유입) -> 배당 활성화

실행:
    python examples/verified_wheel.py
"""

from nightwish.economy import Economy
from nightwish.verification import Direction, Measurement, VerificationRegistry


def main() -> None:
    eco = Economy(dividend_rate=0.20)
    reg = VerificationRegistry()

    # 조상 체인(가까운 것 먼저): 신규 투자 아래로 #F-002 -> #F-001(루트)
    ancestors = [
        ("#F-002", "User-D", True),   # 수정 제안 (부가가치)
        ("#F-001", "Json", True),     # 공장 과제 루트 (부가가치)
    ]
    fresh_stake = 100.0

    print("=" * 64)
    print("검증 닻이 여는 첫 바퀴 (P0)")
    print("=" * 64)

    # 1) 아직 측정 전 — 배당 게이트는 닫혀 있다
    before = eco.distribute_dividend(
        fresh_stake, staker="investor", ancestors=ancestors,
        is_verified=reg.is_verified,
    )
    print("\n[검증 전] 신규 스테이킹 100P 유입:")
    print(f"  배당 = {before or '없음 (검증 닻 없는 가지 -> 흐름 차단)'}")

    # 2) 외부 현실 측정 — 불량률 8% -> 2% (담합으로 못 바꾸는 물성)
    m = Measurement(
        metric="weldline_defect_rate", baseline=8.0, observed=2.0,
        direction=Direction.LOWER_BETTER, unit="%", min_rel_improvement=0.20,
    )
    passed = reg.record("#F-002", m)
    print("\n[측정] 웰드라인 불량률 8.0% -> 2.0%")
    print(f"  상대 개선 {m.relative_improvement:.0%}, 임계 {m.min_rel_improvement:.0%}"
          f" -> {'검증 통과' if passed else '실패'}")

    # 3) 검증된 뒤 동일 스테이킹 — 이제 배당이 열린다
    after = eco.distribute_dividend(
        fresh_stake, staker="investor", ancestors=ancestors,
        is_verified=reg.is_verified,
    )
    print("\n[검증 후] 동일 신규 스테이킹 100P 유입:")
    for who, amt in sorted(after.items()):
        print(f"  {who:7s} -> {amt:6.2f}P")

    print("\n결론:")
    print("  · 검증 전: 배당 0 — 외부 현실 닻 없는 가지는 폰지와 구별불가 -> 차단")
    print("  · 검증 후: 흐름 개통 — 수율/물성이 동의의 순환을 닫는 유일한 닻")
    print("  · #F-001(루트)이 #F-002보다 큰 몫 — 선행 발견 보상(256 시간가중)")
    print("=" * 64)


if __name__ == "__main__":
    main()
