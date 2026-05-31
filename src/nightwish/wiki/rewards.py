"""인증 투자 보상 계산 (순수 함수, 부수효과 없음).

검증된 페이지에 후속 투자가 들어오면, 보상 풀이 *먼저 투자한* 사람들에게
먼저일수록 더 크게 분배된다 (특허 256 시간가중의 미니 버전).
"""

from __future__ import annotations


def early_investor_rewards(prior_user_ids: list[str], pool: float) -> dict[str, float]:
    """선행 투자자(순서대로)에게 풀을 시간가중 분배한다.

    ``prior_user_ids`` 는 최초 투자 순서대로의 사용자 id (먼저 = 앞). 가중치는
    먼저일수록 크다(n, n-1, ..., 1). 반환은 {user_id: payout}.
    """
    n = len(prior_user_ids)
    if n == 0 or pool <= 0:
        return {}
    weights = {uid: (n - i) for i, uid in enumerate(prior_user_ids)}
    total = sum(weights.values())
    return {uid: pool * w / total for uid, w in weights.items()}
