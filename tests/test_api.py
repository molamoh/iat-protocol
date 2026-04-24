import requests

BASE = "https://iat-protocol.onrender.com"

def test_create_order():
    r = requests.post(f"{BASE}/create-order", json={"service":"risk_report"})
    assert r.status_code == 200
    data = r.json()
    assert "order_id" in data
    assert "price" in data

def test_services():
    r = requests.get(f"{BASE}/services")
    assert r.status_code == 200
    data = r.json()
    assert "services" in data
    assert "risk_report" in data["services"]
