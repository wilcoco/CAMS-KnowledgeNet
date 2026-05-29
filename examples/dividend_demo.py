"""부가가치-게이트 배당 라우팅 데모 (설계 §5.2-5.3).

빈손 동의 노드는 배당 흐름이 **우회**하고, 부가가치 있는 조상만 받는다.
선행(더 오래된) 조상이 256 시간가중으로 더 큰 몫을 받는다.

실행:
    python examples/dividend_demo.py
"""

from nightwish.economy import Economy


def main() -> None:
    eco = Economy(dividend_rate=0.20)

    # 체인(가까운 것 먼저): 신규 스테이커 아래로 ↑ 루트까지
    #   newcomer -> [빈손 동의] -> [강한 기여(중간)] -> [루트 기여(가장 오래됨)]
    ancestors = [
        ("agree-node", "follower",  False),  # 빈손 동의 → 우회됨
        ("mid-node",   "improver",  True),   # 부가가치 → 자격 있음
        ("root-node",  "founder",   True),   # 가장 오래된 부가가치 → 가장 큰 몫
    ]

    fresh_stake = 100.0
    payouts = eco.distribute_dividend(
        fresh_stake, staker="newcomer", ancestors=ancestors
    )

    print("=" * 60)
    print("부가가치 게이트 배당 데모")
    print("=" * 60)
    print(f"신규 스테이킹: {fresh_stake:.0f}P, 배당률: {eco.dividend_rate:.0%}")
    print(f"배당 풀: {fresh_stake * eco.dividend_rate:.0f}P\n")

    print("조상 체인 (가까운 것 먼저):")
    for node_id, contributor, value_add in ancestors:
        gate = "통과" if value_add else "우회(빈손)"
        got = payouts.get(contributor, 0.0)
        print(f"  {node_id:11s} {contributor:9s} [{gate:9s}] -> {got:6.2f}P")

    print("\n결론:")
    print("  · 빈손 동의 노드(follower)는 0P  — 폰지 패스스루 차단")
    print("  · 더 오래된 기여(founder)가 더 큰 몫 — 선행 발견 보상(256 시간가중)")
    print("=" * 60)


if __name__ == "__main__":
    main()
