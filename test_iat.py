# IAT Protocol — Unit Tests
# © molamoh 2026 — All rights reserved

import sys
sys.path.insert(0, '..')

from iat import create_wallet, get_network_stats
from iat.verifai import VerifAI

def test_wallet_creation():
    """Test wallet creation."""
    wallet = create_wallet("test_agent_001")
    assert wallet.agent_id == "test_agent_001"
    assert wallet.balance == 0.0
    assert wallet.certified == False
    print("✅ Wallet creation — PASSED")

def test_verifai_certification():
    """Test VerifAI certification."""
    wallet = create_wallet("test_agent_002")
    result = wallet.certify()
    assert result["success"] == True
    assert wallet.certified == True
    print("✅ VerifAI certification — PASSED")

def test_payment():
    """Test IAT payment between two agents."""
    agent_a = create_wallet("agent_a")
    agent_b = create_wallet("agent_b")
    
    agent_a.certify()
    agent_b.certify()
    
    agent_a.receive(100.0, "SYSTEM")
    
    result = agent_a.pay(to_agent="agent_b", amount=10.0)
    assert result["success"] == True
    assert agent_a.balance == 90.0
    print("✅ IAT Payment — PASSED")

def test_network_stats():
    """Test network statistics."""
    stats = get_network_stats()
    assert "total_transactions" in stats
    print("✅ Network stats — PASSED")

if __name__ == "__main__":
    print("\n🤖 IAT Protocol SDK — Running tests...\n")
    test_wallet_creation()
    test_verifai_certification()
    test_payment()
    test_network_stats()
    print("\n✅ All tests passed! IAT SDK is ready. 🚀\n")
