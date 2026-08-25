# Orchestrateur acheteur hébergé

Ce document précise la transition du prototype `iat.buyer_agent_worker` vers
le service temps réel multi-tenant prévu par la phase 1 de la feuille de route.

## Constat vérifié

Le worker actuel est un worker mono-agent :

- un seul `runner.wallet` est construit depuis l’environnement du processus ;
- l’état des jobs est dans un fichier SQLite local ;
- les tokens du runtime sont des variables du processus ;
- le service n’est pas inclus dans l’API Render principale.

Il ne peut donc pas servir plusieurs millions d’acheteurs.

## Contrat de production

Le service hébergé doit utiliser la base partagée et ne jamais stocker de clé
privée d’acheteur :

1. `buyer_agent_id` identifie durablement l’agent acheteur.
2. `buyer_wallet` est son identité publique et reste vérifiable par signature.
3. `runtime_connector_id` référence son runtime hébergé ou son connecteur,
   sans contenir de secret.
4. La politique d’achat (actif, plafond par ordre, plafond quotidien,
   services autorisés) est stockée séparément avec une version optimiste pour
   refuser les changements concurrents obsolètes.
5. Les jobs d’intention sont persistés dans PostgreSQL avec un lease, un
   compteur de tentatives et une chaîne d’événements hashée vérifiable. Le
   raccordement de cette chaîne au journal de preuves métier reste requis
   avant l’activation production.
6. Un pool de workers réclame les jobs par lease et exécute au plus une
   transition bornée par cycle.
7. La signature reste déléguée au runtime/connecteur de l’agent ; IAT ne
   reçoit jamais sa clé privée.

## Ordre d’implémentation

1. Registre partagé des agents acheteurs et de leurs connecteurs.
2. File PostgreSQL `hosted_buyer_jobs` idempotente et récupérable.
3. Adaptateur du scheduler existant vers ce registre, sans recopier le
   moteur de découverte, de paiement ou de preuve.
4. Worker Render séparé, supervisable et activé seulement après canari.
5. Observabilité : état, lease, dernière erreur et prochaine action, sans
   token, clé ou résultat privé.

La première livraison de cette transition ne doit exécuter aucun paiement :
elle doit seulement inscrire un agent, réclamer un job et prouver la reprise
après expiration de lease.

## État vérifié au 25 août 2026

Les trois premiers éléments sont implémentés et testés :

- `iat.hosted_buyer_registry` fournit le registre public multi-tenant ;
- `iat.hosted_buyer_jobs` fournit la file idempotente et ses leases ;
- `iat.hosted_buyer_worker` exécute au plus une transition par job, en
  réutilisant les actions et erreurs du scheduler existant.
- `iat.hosted_buyer_connector` gère la rotation et l’authentification des
  clés de connecteur ; seule leur empreinte est persistée.
- `verify_hosted_buyer_job_events` vérifie l’intégrité de la chaîne de
  transitions de la file.

Le worker reçoit un `HostedBuyerRuntimeResolver` injecté. Cette frontière est
intentionnelle : tant que le connecteur acheteur authentifié n’est pas raccordé,
aucune route ne doit accepter un `buyer_agent_id` et un wallet au seul moyen
de champs JSON. Le déploiement Render de cette étape reste donc désactivé pour
les paiements réels ; le prochain travail est l’authentification du connecteur
et son canari de signature.
