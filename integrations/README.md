# Intégrations

Les adaptateurs présents permettent à différents frameworks d’appeler
`pay_and_get_service`.

Intégrations suivies dans le dépôt :

- AgentVerse ;
- AutoGPT ;
- CrewAI ;
- framework générique ;
- LangChain ;
- MetaGPT ;
- SuperAGI.

Le niveau d’intégration est variable : certains modules sont des wrappers
minimaux et ne sont pas testés contre toutes les versions des frameworks.

Configuration commune :

```bash
export IAT_API_URL="http://127.0.0.1:8000"
export IAT_ADMIN_API_KEY="..."
export IAT_KEYPAIR_PATH="/run/secrets/buyer-keypair.json"
```

Le SDK utilise `/buyer/verify-payment` par défaut. Une intégration ne doit
surcharger `IAT_VERIFY_PAYMENT_PATH` que pour communiquer temporairement avec
un déploiement historique.

Avant un paiement réel :

- vérifier le service et le prix ;
- utiliser un wallet à faible exposition ;
- ne jamais injecter le contenu du keypair dans un prompt ;
- traiter `foundation_review_required` comme un état en attente ;
- ne pas relancer un paiement déjà réclamé.
