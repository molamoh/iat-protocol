from iat import create_wallet, get_network_stats

# Agent B
agent_b = create_wallet("agent_b")
agent_b.certify()
print(f"🤖 Agent B certified")

# Agent A
agent_a = create_wallet("agent_a")
agent_a.certify()
agent_a.receive(1000.0, "SYSTEM")
print(f"🤖 Agent A certified - Balance: {agent_a.get_balance()} IAT")

# Payment
tx = agent_a.pay(to_agent="agent_b", amount=10.0)
if tx["success"]:
    print(f"✅ Payment confirmed!")
    print(f"📤 Amount: {tx['amount']} IAT")
    print(f"🔗 TX: {tx['tx_id']}")
    print(f"⚡ Speed: {tx['confirmation_ms']}ms")
print(f"📊 Stats: {get_network_stats()}")
