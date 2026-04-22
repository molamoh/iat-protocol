from iat import create_wallet, get_network_stats
print("🤖 Agent A starting...")
agent_a = create_wallet("agent_a_payment_sender")
agent_a.certify()
agent_a.receive(1000.0, "SYSTEM")
tx = agent_a.pay(to_agent="agent_b_service_provider", amount=10.0)
if tx["success"]:
    print(f"✅ Payment confirmed!")
    print(f"📤 Amount: {tx['amount']} IAT")
    print(f"🔗 TX: {tx['tx_id']}")
print(f"📊 Stats: {get_network_stats()}")
