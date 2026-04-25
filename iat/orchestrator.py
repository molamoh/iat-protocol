from iat import pay_and_get_service


def run_strategy(strategy_name, keypair_path):
    if strategy_name != "btc_trade_signal":
        return {
            "status": "failed",
            "reason": "unknown_strategy"
        }

    # 1) Buy risk report with IAT
    risk = pay_and_get_service("risk_report", keypair_path)

    if risk.get("status") != "success":
        return {
            "status": "failed",
            "step": "risk_report",
            "reason": risk
        }

    # 2) Buy liquidity map with IAT
    liquidity = pay_and_get_service("liquidity_map", keypair_path)

    if liquidity.get("status") != "success":
        return {
            "status": "failed",
            "step": "liquidity_map",
            "reason": liquidity
        }

    risk_data = risk["result"]["data"]
    liquidity_data = liquidity["result"]["data"]

    # 3) Combine paid services into a higher-value output
    risk_level = risk_data.get("risk_level")
    volatility = risk_data.get("volatility")
    mm_bias = liquidity_data.get("market_maker_bias")

    if risk_level == "medium" and volatility == "high" and mm_bias == "seek_nearest_liquidity":
        signal = "WAIT_FOR_LIQUIDITY_SWEEP"
        confidence = 0.81
    else:
        signal = "NO_TRADE"
        confidence = 0.55

    total_cost = risk["price"] + liquidity["price"]

    return {
        "status": "success",
        "strategy": strategy_name,
        "total_cost_iat": total_cost,
        "paid_steps": [
            {
                "service": "risk_report",
                "seller_id": risk["seller_id"],
                "price": risk["price"],
                "tx_signature": risk["tx_signature"]
            },
            {
                "service": "liquidity_map",
                "seller_id": liquidity["seller_id"],
                "price": liquidity["price"],
                "tx_signature": liquidity["tx_signature"]
            }
        ],
        "final_output": {
            "type": "trade_signal_pro",
            "asset": "BTC",
            "signal": signal,
            "confidence": confidence,
            "reasoning": {
                "risk_level": risk_level,
                "volatility": volatility,
                "market_maker_bias": mm_bias
            }
        }
    }
