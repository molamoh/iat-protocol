# IAT Protocol

IAT Protocol est un prototype avancé d’infrastructure économique et
d’exécution pour agents autonomes. Il permet à un acheteur de découvrir un
service, créer une commande, payer en jetons IAT sur Solana, faire exécuter la
demande par un ou plusieurs agents, puis enregistrer la livraison, le
règlement, la réputation et les événements de gouvernance.

Le dépôt contient une API FastAPI, un SDK Python, un registre d’agents, un
moteur de consensus multi-agent, un Action Engine persistant, un runtime
vendeur, une couche de règlement et plusieurs intégrations de frameworks.

## Interface native pour les acheteurs IA

IAT expose désormais une couche publique séparée des routes administratives :

- `/.well-known/iat.json` pour la découverte automatique ;
- `/v1/capabilities` pour les capacités et invariants de sécurité ;
- `/openapi-public.json` pour le contrat OpenAPI stable ;
- `/llms.txt` pour l’orientation des modèles ;
- `/sandbox/v1/*` pour comparer et simuler un achat sans wallet ni fonds.

Le sandbox applique réellement les budgets, capacités requises, stratégies de
sélection et clés d’idempotence. Il ne contacte aucun fournisseur, ne déplace
aucun fonds et marque ses reçus comme impropres au règlement. Son apprentissage
de réputation est limité au sandbox, idempotent et borné ; il ne peut modifier
ni le code ni les politiques du protocole.

Le nouveau client typé fournit une entrée unique :

```python
from iat import IATClient

client = IATClient.from_env()
manifest = client.discover()

order = client.sandbox_buy(
    "web_research",
    goal="Comparer les protocoles de paiement entre agents",
    max_price="2.00",
    strategy="quality",
    required_capabilities=["source_verification"],
    idempotency_key="evaluation-iat-0001",
)

assert order["funds_moved"] is False
```

Voir [`AI_BUYER_GUIDE.md`](AI_BUYER_GUIDE.md) pour le parcours complet et les
frontières entre sandbox et production.

## Programme fournisseurs

Les fournisseurs humains ou IA peuvent évaluer IAT avant toute inscription :

- `/seller/v1/discovery` décrit le parcours et la politique commerciale ;
- `/seller/v1/readiness` produit un score, des blocages et les prochaines actions ;
- `/seller/v1/economics/estimate` simule commission, payout et marge ;
- `/seller/v1/integration-contract` expose le contrat runtime attendu.

Le SDK `IATSellerClient` couvre ensuite l’inscription des agents, le catalogue,
le dashboard, les analytics et les payouts. Les opérations authentifiées
utilisent le header `x-seller-api-key`. Les runtimes HTTP sont validés contre
les cibles privées, locales ou réservées et doivent utiliser HTTPS par défaut.

Voir [`SELLER_GUIDE.md`](SELLER_GUIDE.md) et
[`examples/sdk/ai_seller_quickstart.py`](examples/sdk/ai_seller_quickstart.py).

## État du projet

Le projet est un **prototype technique avancé**. Les composants principaux
fonctionnent localement et disposent d’une première suite de tests, mais le
protocole ne doit pas encore être considéré comme une infrastructure
financière auditée ou totalement décentralisée.

État vérifié du dépôt :

- Python 3.10 ou plus récent ;
- FastAPI ;
- SQLite par défaut, PostgreSQL via `DATABASE_URL` ;
- Solana et SPL Token ;
- suite locale couvrant API, sécurité, persistance et interface buyer IA ;
- vérification CI de la compilation, des erreurs statiques critiques et des
  tests ;
- ledger de settlement en partie double avec montants entiers à 8 décimales ;
- création atomique et idempotente du settlement et de son allocation ;
- réconciliation administrative et backfill contrôlé des anciens settlements ;
- schéma de base versionné à `2` ;
- authentification administrative fail-closed ;
- idempotence atomique des signatures de paiement.

## Architecture rapide

```text
SDK / Client
    |
    v
API FastAPI
    |
    +--> Buyer flow --> commande --> vérification Solana
    |                                  |
    |                                  v
    |                         Protocol Runtime
    |                                  |
    |                    +-------------+-------------+
    |                    |                           |
    |              exécution directe         consensus multi-agent
    |                    |                           |
    |                    +-------------+-------------+
    |                                  |
    |                         livraison + règlement
    |
    +--> Seller Runtime --> catalogue, agents, gouvernance
    +--> Action Engine  --> queue, workers, retries, supervision
    +--> Platform       --> état, explorer, graphe
```

Le point d’entrée serveur est
[`iat.api.agent_b_api:app`](iat/api/agent_b_api.py). Le SDK utilise par défaut
le flux canonique :

```text
POST /create-order
POST /buyer/verify-payment
```

L’ancien flux `/verify-payment-multicall` reste disponible pour compatibilité,
mais il n’est plus le chemin par défaut du SDK.

## Installation

```bash
python3 -m venv iat_env
source iat_env/bin/activate
python -m pip install -e ".[dev]"
```

Pour une installation d’exécution uniquement :

```bash
python -m pip install -r requirements.txt
```

## Configuration minimale

```bash
export IAT_ADMIN_API_KEY="change-me"
export GROQ_API_KEY="gsk_..."
# Modèle recommandé par Groq. Facultatif : c'est aussi la valeur par défaut.
export GROQ_MODEL="openai/gpt-oss-20b"
# low, medium ou high (low limite la latence des tâches JSON courantes).
export GROQ_REASONING_EFFORT="low"

# Autonomous acquisition engine (safe rollout defaults)
export IAT_ENABLE_AUTONOMOUS_GROWTH="false"
export IAT_GROWTH_DISCOVERY_ENABLED="false"
export IAT_GROWTH_OUTBOUND_ENABLED="false"
export IAT_GROWTH_INTERVAL_SECONDS="900"
export IAT_GROWTH_RESPONSE_SECRET="replace-with-a-long-random-secret"
export IAT_DB_PATH="/var/lib/iat/iat_protocol.db"
export IAT_SOLANA_RPC_URL="https://api.mainnet-beta.solana.com"
```

Le moteur d’acquisition machine-to-machine est documenté dans
[`GROWTH_ENGINE.md`](GROWTH_ENGINE.md). Il qualifie les prospects et prépare des
campagnes en continu, avec consentement explicite, quotas, approbation,
idempotence, protection SSRF et audit complet.

Pour un règlement par escrow :

```bash
export IAT_ESCROW_WALLET="..."
export IAT_ESCROW_KEYPAIR_PATH="/run/secrets/iat-escrow.json"
export IAT_PROTOCOL_TREASURY_WALLET="..."
```

Ne placez jamais une clé privée, un keypair, un fichier `.env` ou une base
locale dans une image ou un commit. Le `.dockerignore` du dépôt exclut ces
éléments du contexte Docker.

## Lancer l’API

```bash
export IAT_ADMIN_API_KEY="development-only-key"
export IAT_DB_PATH="/tmp/iat-development.sqlite"
export IAT_ENABLE_RUNTIME_GOVERNANCE_LOOP="false"

uvicorn iat.api.agent_b_api:app --host 127.0.0.1 --port 8000
```

La documentation OpenAPI interne est désactivée par défaut. Pour un
environnement local uniquement :

```bash
export IAT_ENABLE_INTERNAL_DOCS="true"
```

Puis ouvrir `http://127.0.0.1:8000/docs`.

## Utiliser le SDK

```python
from iat import create_order, list_services, verify_order

services = list_services()
order = create_order(
    "risk_report",
    query="Analyse le risque BTC à 7 jours",
)

# Le transfert IAT doit être effectué avant la vérification.
result = verify_order(order["order_id"], "SOLANA_TRANSACTION_SIGNATURE")
```

Le helper complet est également disponible :

```python
from iat import pay_and_get_service

result = pay_and_get_service(
    service="risk_report",
    keypair_path="/run/secrets/buyer-keypair.json",
    query="Analyse le risque BTC à 7 jours",
)
```

## Tests et qualité

```bash
python -m compileall -q \
  iat integrations nodes local_agents malicious_agent examples tests
python -m ruff check \
  iat integrations nodes local_agents malicious_agent examples tests
python -m pytest
```

Les tests n’appellent pas le service public et ne créent pas de commande en
production. Ils utilisent des mocks HTTP et des bases SQLite temporaires.

## Documentation

La documentation technique détaillée est conservée localement par les
mainteneurs. Le README public expose uniquement les informations nécessaires à
l’installation et à l’utilisation générale du SDK.

## Avertissement

Le code manipule des paiements, des clés Solana et des décisions de règlement.
Utilisez des wallets de test et un RPC adapté tant que le déploiement n’a pas
fait l’objet d’un audit indépendant. Le mode de règlement on-chain reste
désactivé par défaut.

Le ledger version 1 garantit l’équilibre de l’allocation comptable d’un
settlement, mais ne constitue pas à lui seul une preuve de transfert on-chain.
Voir [`FINANCIAL_RELIABILITY.md`](FINANCIAL_RELIABILITY.md) pour les invariants,
la migration et le runbook d’incident.
