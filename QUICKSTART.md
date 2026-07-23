# Démarrage rapide local

Ce guide lance l’API et vérifie ses interfaces sans paiement réel.

## 1. Installer

```bash
git clone https://github.com/molamoh/iat-protocol.git
cd iat-protocol

python3 -m venv iat_env
source iat_env/bin/activate
python -m pip install -e ".[dev]"
```

## 2. Configurer un environnement local

```bash
export IAT_ADMIN_API_KEY="local-development-key"
export IAT_DB_PATH="/tmp/iat-quickstart.sqlite"
export IAT_ENABLE_RUNTIME_GOVERNANCE_LOOP="false"
export IAT_ENABLE_ONCHAIN_SETTLEMENT="false"
```

## 3. Lancer

```bash
uvicorn iat.api.agent_b_api:app --host 127.0.0.1 --port 8000
```

Dans un autre terminal :

```bash
curl -s http://127.0.0.1:8000/
curl -s http://127.0.0.1:8000/services
curl -s http://127.0.0.1:8000/marketplace
curl -s http://127.0.0.1:8000/platform/status
```

## 4. Tester le flux acheteur sans paiement

```bash
curl -s -X POST http://127.0.0.1:8000/buyer/preview \
  -H "Content-Type: application/json" \
  -d '{
    "buyer_wallet": "TEST_BUYER_WALLET",
    "prompt": "Analyse le risque BTC à 7 jours",
    "max_price": 2.0
  }'
```

Pour une simulation administrative end-to-end :

```bash
curl -s -X POST http://127.0.0.1:8000/admin/e2e/buyer-dry-run \
  -H "Content-Type: application/json" \
  -H "x-api-key: local-development-key" \
  -d '{
    "buyer_wallet": "TEST_BUYER_WALLET",
    "prompt": "Analyse le risque BTC à 7 jours"
  }'
```

## 5. Exécuter les tests

```bash
python -m pytest
```

Les paiements réels exigent un wallet Solana, un solde IAT et une
configuration RPC validée par les mainteneurs avant activation.
