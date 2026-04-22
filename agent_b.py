from iat import create_wallet
print("🤖 Agent B starting...")
agent_b = create_wallet("agent_b_service_provider")
result = agent_b.certify()
print(f"✅ Certified: {result['certificate']}")
print(f"💰 Balance: {agent_b.get_balance()} IAT")
