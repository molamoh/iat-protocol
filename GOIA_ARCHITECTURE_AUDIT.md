# Audit d'architecture IAT vers GOIA

Date de l'audit : 26 juillet 2026

Statut : audit en lecture seule du dépôt, sans modification du comportement
applicatif ni du déploiement.

Mise à jour du 26 juillet 2026 : la phase 1 a commencé après l'audit. Les
contrats GOIA v1, le manifeste machine, la politique d'impartialité et leurs
routes de validation sans effets externes ont été implémentés. À ce jalon, la
recherche, le crawling et la persistance GOIA étaient explicitement désactivés.

Mise à jour phase 2 : un index local pilote séparé, une ingestion administrative
de catalogues contrôlés et une recherche organique locale sont implémentés. La
recherche n'effectue aucun accès réseau, les résultats sponsorisés sont exclus
du classement organique et le crawling reste explicitement désactivé.

Mise à jour phase 3 : un worker de collecte séparé et désactivé par défaut est
implémenté pour les domaines explicitement autorisés. Il respecte `robots.txt`,
refuse les redirections, borne les documents, analyse les sitemaps et extrait
le JSON-LD commercial. Toute extraction reste en `review_required` et ne peut
pas publier automatiquement une offre.

Mise à jour revue gouvernée : chaque candidat collecté est désormais lié à un
marchand et conservé séparément de l'index. L'approbation administrative exige
une `OfferObservation` complète dont l'URL et le hash de preuve correspondent
exactement à la page collectée. Les approbations et rejets sont idempotents.

Mise à jour autonomie : la revue humaine n'est plus une dépendance du chemin
normal. La politique déterministe `goia_autonomous_review_v1` normalise,
vérifie et publie seule les candidats complets ; les cas incertains sont mis en
quarantaine. Les routes administratives sont conservées uniquement pour audit
et commande d'urgence.

Mise à jour auto-récupération : les jobs abandonnés utilisent désormais des
leases récupérables et un plafond d'essais. Les candidats en quarantaine sont
recollectés avec un backoff exponentiel borné, puis passent en
`quarantine_exhausted` après trois échecs sans bloquer les autres recherches.

Mise à jour découverte autonome : GOIA amorce désormais les sitemaps déclarés
par les marchands selon leur fenêtre de fraîcheur. Les sitemaps prioritaires
produisent un nombre borné de jobs enfants, idempotents et limités aux domaines
autorisés. Aucun moteur de recherche privé n'est utilisé.

Mise à jour catalogue natif : les marchands peuvent publier un catalogue
`goia_catalog_v1` borné et versionné. GOIA vérifie automatiquement fournisseur,
fraîcheur, prix, devise, disponibilité et domaine, puis lie chaque observation
au hash exact du catalogue avant publication autonome.

Mise à jour intelligence partenariats : les recherches locales alimentent des
signaux de demande agrégés sans requête brute ni identité acheteur. GOIA mesure
le ratio de demandes non satisfaites et la rareté des offres, puis maintient
des opportunités `monitoring` ou `qualified`. Cette étape ne déclenche aucun
outreach.

Mise à jour prospection structurée : GOIA extrait désormais les vendeurs
déclarés dans les `Offer` Schema.org des comparateurs autorisés. Il conserve
des preuves bornées, qualifie les domaines par score déterministe et les relie
aux lacunes de marché compatibles. Un domaine découvert n'est ni visité ni
contacté : il constitue une preuve, jamais une autorisation.

Mise à jour permission partenariats : le manifeste marchand possède un opt-in
explicite et fermé par défaut. GOIA rapproche automatiquement domaine,
manifeste et prospect, puis révoque l'état dès que l'opt-in disparaît. À ce
stade, la déclaration seule reste distincte d'une preuve d'auto-hébergement et
n'autorise donc aucun contact.

Mise à jour preuve d'auto-hébergement : le worker collecte périodiquement le
manifeste de partenariat déclaré via l'allowlist et robots.txt, puis exige une
égalité exacte du hash normalisé, du fournisseur, du domaine et de l'URL
source. La preuve expire automatiquement ; seul `verified_opt_in` autorise
l'endpoint déclaré, sans encore émettre de requête.

Mise à jour proposition autonome : lorsqu'une opportunité et un marchand
vérifié correspondent, GOIA produit un contrat
`goia_partnership_proposal_v1` déterministe dans une outbox isolée. Le contenu
utilise uniquement des agrégats anonymes, expire avec la permission et ne
déclenche aucune livraison réseau à ce stade.

Mise à jour cycle de livraison : l'outbox possède désormais leases, reprise
après crash, backoff borné, plafond de tentatives et événements ordonnés.
Chaque claim revalide la preuve et la permission. Le dispatcher est séparé du
collecteur, désactivé par défaut et aucun adaptateur réseau n'est encore
embarqué.

Mise à jour transport signé : un adaptateur HTTP optionnel signe le contenu
canonique en Ed25519, refuse redirections et cibles privées, contrôle l'IP
réellement connectée, borne la réponse et exige un accusé
`goia_partnership_ack_v1` lié à la proposition. Deux activations indépendantes
et une clé privée serveur sont nécessaires ; elles restent désactivées par
défaut.

Mise à jour retrait et exécution autonome : un accusé marchand `opt_out` ou
`do_not_contact` crée une suppression globale prioritaire sur tout signal
positif et annule les propositions restantes. Le dispatcher possède désormais
un conteneur et une boucle autonomes séparés du collecteur ; son démarrage
reste fail-closed sans activation complète et clé Ed25519 valide.

Mise à jour décision marchand : GOIA accepte désormais des réponses
asynchrones signées par la clé publique du manifeste auto-hébergé. Il vérifie
fraîcheur, fournisseur, proposition, domaine des conditions et idempotence.
Une acceptation reste `accepted_pending_activation`, sans commission et sans
effet sur le classement ; un `opt_out` applique la suppression globale.

## 1. Résumé exécutif

IAT Protocol possède déjà une base substantielle pour devenir l'infrastructure
économique de GOIA :

- découverte machine et contrats publics ;
- registre, catalogue et cycle de vie vendeur ;
- moteur de décision déterministe et explicable ;
- moteur de prospection gouverné ;
- exécution, reprise et supervision ;
- checkout USDC vers IAT sur Solana devnet ;
- commission, settlement et ledger comptable ;
- sécurité réseau applicative et contrôles d'autorité.

Le dépôt n'est toutefois pas encore prêt à recevoir un moteur général de
recherche commerciale directement dans son API centrale. Deux fichiers
historiques concentrent près de 43 000 lignes et plusieurs chemins
d'exécution coexistent. Ajouter le crawler, l'index commercial, l'affiliation
et l'attribution dans ces monolithes augmenterait fortement les risques.

La recommandation centrale est donc :

> Conserver IAT Protocol comme couche d'identité économique, de décision,
> d'exécution et de règlement, et construire GOIA comme un nouveau domaine
> modulaire de découverte commerciale, connecté à IAT par des contrats
> versionnés.

La première version de GOIA ne doit ni chercher à indexer tout Internet ni
dépendre d'une API de recherche payante. Elle doit :

1. indexer localement un secteur pilote ;
2. exploiter les catalogues, sitemaps et données structurées ;
3. vérifier les offres à leur source ;
4. classer indépendamment des commissions ;
5. utiliser la demande réelle pour prospecter les marchands ;
6. rémunérer IAT uniquement sur les conversions attribuées.

## 2. Périmètre et méthode

L'audit couvre :

- code Python sous `iat/` ;
- programme Anchor `programs/iat-checkout` ;
- API FastAPI et routes publiques, vendeurs, internes et administratives ;
- persistance SQLite/PostgreSQL ;
- moteur d'action, vendeurs et croissance ;
- checkout, settlement et ledger ;
- SDK, intégrations et agents de démonstration ;
- documentation et tests.

Les vérifications réalisées comprennent :

- inventaire des fichiers et modules ;
- recherche des routes, tables, configurations et marqueurs de simulation ;
- lecture des documents d'architecture, sécurité, état et finance ;
- inspection des principaux chemins publics et de démarrage ;
- collecte de la suite de tests ;
- exécution de la suite existante sans échec signalé.

Repères quantitatifs observés :

| Indicateur | Valeur observée |
|---|---:|
| Code Python/Rust IAT + tests | environ 72 140 lignes |
| `iat/api/agent_b_api.py` | 12 475 lignes |
| `iat/api/db.py` | 30 804 lignes |
| Routes FastAPI détectées | environ 300 |
| Tables `CREATE TABLE IF NOT EXISTS` détectées | environ 103 |
| Tests collectés par pytest | 189 |
| Modèles/requêtes/réponses API détectés | environ 86 |

Ces chiffres décrivent la taille et la complexité, pas une couverture ou une
qualité garantie.

## 3. Vision produit recommandée

### 3.1 Positionnement

IAT Protocol reste l'infrastructure :

- identité économique ;
- politiques ;
- confiance ;
- décision ;
- paiement ;
- commission ;
- settlement ;
- audit.

GOIA devient le produit de découverte commerciale :

- compréhension du besoin ;
- exploration du Web ouvert ;
- index de produits et services ;
- comparaison ;
- vérification ;
- recommandation ;
- attribution de conversion ;
- acquisition de partenaires.

Nom de présentation provisoire :

> GOIA, powered by IAT Protocol

Le nom devra faire l'objet d'une vérification de marques, domaines, réseaux
sociaux et conflits logiciels avant toute adoption publique.

### 3.2 Boucle économique

```text
Demandes des agents
        |
        v
Connaissance de la demande réelle
        |
        v
Détection des catégories et offres insuffisantes
        |
        v
Prospection de marchands pertinents
        |
        v
Catalogues plus riches et plus frais
        |
        v
Meilleures recommandations
        |
        v
Conversions attribuées et commissions
        |
        v
Financement de l'index et de la vérification
```

La recherche doit rester très peu coûteuse. Le revenu doit venir principalement
des ventes, leads ou abonnements effectivement attribués, pas de chaque requête.

## 4. Cartographie de l'existant

### 4.1 API centrale

Composant principal :

- `iat/api/agent_b_api.py`

État :

- serveur FastAPI réel et point d'entrée du conteneur ;
- environ 300 routes au total dans le projet ;
- forte concentration de routes, orchestration et imports ;
- coexistence de routes canoniques et historiques ;
- démarrage de plusieurs services et workers dans le processus web.

Réutilisation GOIA :

- conserver l'authentification et les contrats existants à court terme ;
- ne pas ajouter les routes internes de crawling au monolithe ;
- monter un router GOIA public minimal dans l'application actuelle au début ;
- déplacer ensuite GOIA vers un service indépendant.

Décision : **adapter avec frontière stricte**.

### 4.2 Découverte machine

Composants :

- `iat/discovery.py`
- `iat/api/public.py`
- `/.well-known/iat.json`
- `/v1/capabilities`
- `/llms.txt`

Forces :

- manifeste lisible par les agents ;
- capacités et invariants publiés ;
- contrats publics structurés ;
- documentation orientée machine.

Écarts GOIA :

- aucun manifeste marchand générique ;
- aucun contrat d'offre commerciale ;
- absence de fraîcheur, preuve et attribution ;
- vocabulaire encore centré sur les agents fournisseurs.

Évolution :

- `/.well-known/goia.json` pour découvrir GOIA ;
- `/.well-known/goia-provider.json` pour les marchands ;
- `/.well-known/goia-catalog.json` ou lien vers un flux ;
- versions explicites et compatibilité ascendante.

Décision : **conserver et étendre**.

### 4.3 Marketplace

Composants :

- endpoints `/marketplace`, `/services`, `/agents` ;
- `iat/platform/marketplace.py` ;
- catalogue vendeur dans la base ;
- registre dynamique d'agents.

État :

- adapté aux services exécutés par des agents ;
- couche `platform/marketplace.py` essentiellement présentative ;
- pas de modèle canonique pour produits physiques ou offres externes ;
- pas d'historique de prix ou de disponibilité.

Écarts GOIA :

- produit, variante et identité marchande ;
- prix total ;
- devise et fiscalité ;
- expédition ;
- retours ;
- disponibilité ;
- géographie ;
- preuves et date d'observation ;
- déduplication inter-sites.

Décision : **ne pas étendre directement le catalogue agent**. Créer un domaine
commercial séparé relié par des identifiants et événements.

### 4.4 Moteur de décision

Composants :

- `iat/intelligence/decision_core.py`
- `iat/intelligence/decision_learning.py`
- `iat/intelligence/seller_intelligence.py`
- `iat/intelligence/demand_forecasting.py`
- `iat/api/decision_api.py`

Forces :

- déterministe ;
- explicable ;
- politiques versionnées ;
- contraintes de prix, capacité, confiance et fiabilité ;
- stratégies `balanced`, `cheapest`, `fastest`, `safest`, `quality` ;
- hash de décision et enregistrement des résultats.

Limites :

- prix en `float` dans plusieurs chemins ;
- score prix principalement relatif au budget maximum ;
- aucune notion de coût total commercial ;
- aucune fraîcheur d'observation ;
- aucune confiance au niveau de chaque attribut ;
- aucune séparation native organique/sponsorisé ;
- simulation annoncée dans le résultat du cœur.

Évolution GOIA :

- calcul monétaire exact en unités mineures/`Decimal` ;
- fonctions de classement commerciales séparées ;
- score de fraîcheur ;
- score de preuve ;
- pénalité d'incertitude ;
- coût total rendu ;
- compatibilité géographique ;
- disponibilité ;
- politique de retour ;
- classement organique indépendant des commissions ;
- journal d'explication.

Décision : **réutiliser le cadre, pas les métriques telles quelles**.

### 4.5 Intention acheteur

Composants :

- `iat/api/buyer_intent.py`
- preview, confirmation et commandes ;
- SDK acheteur et sandbox.

Forces :

- normalisation d'intention ;
- budget et stratégie ;
- session acheteur ;
- séparation preview/confirmation ;
- sandbox sans fonds.

Limites :

- dépendance Groq dans certaines analyses ;
- schéma orienté services ;
- absence de contraintes produit riches ;
- absence de localisation commerciale complète ;
- pas de boucle de clarification structurée pour attributs manquants.

Évolution GOIA :

- `SearchIntent` générique ;
- type de besoin ;
- pays, devise, langue et destination ;
- contraintes obligatoires et préférences ;
- tolérance à l'occasion/reconditionné ;
- délai et conditions ;
- consentement au rafraîchissement temps réel ;
- explicitation des compromis.

Décision : **adapter et versionner**.

### 4.6 Vendeurs et runtimes

Composants :

- `iat/seller.py`
- `iat/seller_growth.py`
- `iat/seller_runtime/`
- routes `/seller/*`
- factory, sandbox, simulation, approbation et activation.

Forces :

- parcours vendeur complet ;
- API key vendeur ;
- catalogue ;
- HTTP, Python et runtime interne ;
- santé, capacité, risque et confiance ;
- exposition gouvernée ;
- isolation de l'acheteur ;
- reprise et audit.

Limites :

- vendeur assimilé à un fournisseur d'exécution IA ;
- intégration exige souvent un runtime ;
- cycle d'approbation complexe pour un simple flux catalogue ;
- clés vendeur exploitables en base ;
- nombreux états et contrôles concentrés dans le monolithe DB.

Évolution GOIA :

Définir plusieurs classes de partenaires :

1. marchand référencé sans relation commerciale ;
2. marchand affilié ;
3. marchand catalogue connecté ;
4. comparateur ;
5. réseau d'affiliation ;
6. marchand natif IAT ;
7. fournisseur agent historique.

Un marchand catalogue ne doit pas devoir créer un agent exécutable.

Décision : **conserver le seller runtime historique et créer un Partner
Registry commercial adjacent**.

### 4.7 Growth Engine

Composants :

- `iat/growth.py`
- `iat/api/growth_api.py`
- `iat/api/growth_public.py`
- `GROWTH_ENGINE.md`
- agent de test et runbooks.

Forces :

- ingestion canonique et idempotente ;
- qualification ;
- campagnes ;
- quotas ;
- cooldown global de 24 heures ;
- approbation ;
- audit ;
- réponses ;
- désinscription et suppression ;
- circuit breaker ;
- recommandations et rollback ;
- worker et récupération.

Limites :

- segments limités aux acteurs IA et vendeurs génériques ;
- découverte à partir de feeds autorisés ;
- outreach automatique uniquement avec permission publique explicite ;
- pas d'analyse de programme d'affiliation ;
- pas de pipeline contractuel ;
- pas de données de demande GOIA ;
- pas de modèle de partenaire marchand.

Évolution GOIA :

- nouveaux segments `merchant`, `comparison_site`, `affiliate_network`,
  `catalog_platform` ;
- score fondé sur la demande agrégée ;
- détection de programme de partenariat ;
- préparation automatique du dossier ;
- validation humaine initiale ;
- gestion du cycle de négociation ;
- contrat, taux, territoires et dates ;
- activation technique et commerciale séparée ;
- suivi des conversions et valeur du partenaire.

Décision : **réutilisation forte après généralisation du modèle**.

### 4.8 Action Engine

Composants :

- `iat/action_engine/`
- queue, workers, retries, récupération, dead-letter ;
- policies, circuit breakers, événements et métriques.

Forces :

- modèle d'exécution structuré ;
- idempotence ;
- récupération ;
- séparation adaptateurs ;
- supervision ;
- contrôle des actions risquées.

Limites :

- workers réellement distribués incomplets ;
- boucle embarquée dans le serveur web ;
- risque de double boucle avec plusieurs replicas ;
- chemins historiques parallèles ;
- graphe de dépendances incomplet.

Utilisation GOIA :

- collecte planifiée ;
- rafraîchissement d'offres ;
- extraction ;
- vérification ;
- attribution ;
- prospection ;
- réessais et circuit breakers par domaine.

Condition :

- exécuter ces tâches dans un worker séparé ;
- utiliser des leases persistants ;
- limiter concurrence et fréquence par domaine ;
- ne jamais exécuter le crawler dans le processus HTTP public.

Décision : **réutiliser les concepts, durcir la distribution avant charge**.

### 4.9 Checkout USDC vers IAT

Composants :

- `iat/api/checkout_api.py`
- `iat/checkout_*`
- programme Anchor `iat-checkout`
- vérification Solana et livraison.

État vérifié avant cet audit :

- programme déployé sur Solana devnet ;
- transfert direct USDC vers IAT fonctionnel ;
- paiement smoke confirmé ;
- récupération de signature tardive ;
- pool PostgreSQL thread-safe ;
- réponse publique redacted.

Limites :

- devnet uniquement pour le périmètre validé ;
- livraison du service distincte du transfert de token ;
- dépendance RPC ;
- production mainnet non auditée ;
- architecture encore couplée au backend principal.

Utilisation GOIA :

- ne pas modifier pendant la première phase Discovery ;
- connecter uniquement après validation de la recherche et de l'attribution ;
- conserver devnet comme environnement de test.

Décision : **geler fonctionnellement et isoler**.

### 4.10 Settlement et ledger

Composants :

- `iat/checkout_settlement.py`
- `iat/settlement/`
- `iat/api/ledger_db.py`
- `FINANCIAL_RELIABILITY.md`

Forces :

- double entrée append-only pour l'allocation ;
- unités mineures exactes pour les nouveaux enregistrements ;
- invariant montant brut = payout + commission ;
- idempotence ;
- compare-and-swap ;
- réconciliation.

Limites :

- ledger ne couvre pas encore tout le cycle ;
- reçus de fonds, remboursements, litiges et reversals incomplets ;
- réconciliation on-chain à ajouter ;
- colonnes historiques `REAL` encore présentes ;
- commission actuelle pensée en IAT et settlement interne.

Évolution GOIA :

- distinguer commission protocolaire et commission externe ;
- gérer devise de commission ;
- état `pending`, `approved`, `locked`, `paid`, `reversed` ;
- fenêtre de retour marchand ;
- preuve d'attribution ;
- facture/relevé ;
- rapprochement entre réseau d'affiliation, marchand et IAT.

Décision : **réutiliser le ledger après extension comptable dédiée**.

### 4.11 Sécurité et réseau

Composants :

- `iat/security/authorities.py`
- `iat/security/network.py`
- validation SSRF ;
- auth Foundation et vendeur ;
- contrôle de payload public.

Forces :

- auth administrative fail-closed ;
- comparaison en temps constant ;
- validation d'URL publique ;
- redirections contrôlées dans Growth ;
- réponses checkout assainies ;
- doctrine de médiation Foundation.

Risques :

- une clé Foundation unique ;
- clés vendeur non hashées ;
- routes admin/interne exposées par la même application ;
- absence de rate limiting applicatif ;
- absence de mTLS/scopes/rotation native ;
- crawler futur exposé aux pages hostiles ;
- contenu Web non fiable et potentiellement injecté.

Exigences GOIA :

- sandbox réseau des fetchers ;
- DNS résolu et revalidé ;
- blocage IP privées/link-local/metadata ;
- limites taille, temps, redirections et types MIME ;
- aucun JavaScript au début ;
- contenu stocké comme donnée non fiable ;
- aucun texte Web interprété comme instruction ;
- extraction structurée avant LLM ;
- secrets séparés par service ;
- conformité `robots.txt` et politique de retrait.

Décision : **durcissement obligatoire avant crawler public**.

### 4.12 Persistance

Composant :

- `iat/api/db.py`

Forces :

- compatibilité SQLite/PostgreSQL ;
- pool PostgreSQL thread-safe ;
- nombreuses structures persistantes ;
- initialisation différée au démarrage ;
- début de versionnement du schéma.

Limites critiques :

- 30 804 lignes ;
- connexion, schémas, repositories et métier mélangés ;
- plus de 100 créations de tables détectées ;
- migrations incrémentales insuffisantes ;
- transactions globales inégales ;
- pas de suite d'intégration PostgreSQL complète ;
- risques de contention lors de croissance.

Évolution GOIA :

- migrations dédiées ;
- schéma `goia` ou préfixes explicites ;
- repositories séparés ;
- tables partitionnables d'observations ;
- politique de rétention ;
- stockage objet pour preuves/pages ;
- index de recherche indépendant lorsque nécessaire.

Décision : **ne pas ajouter les tables GOIA au monolithe `db.py`**.

### 4.13 SDK et intégrations

Composants :

- `iat/sdk.py`
- `iat/buyer.py`
- `iat/seller.py`
- `integrations/`

Forces :

- SDK synchrone ;
- intégrations CrewAI, LangChain, AutoGPT, AgentVerse, MetaGPT, SuperAGI ;
- exemples acheteur/vendeur.

Limites :

- maintenance et niveau de test inégaux ;
- absence de SDK asynchrone ;
- contrats historiques reproduits dans certains adaptateurs ;
- aucun client GOIA.

Évolution :

- `GOIAClient.search()` ;
- `GOIAClient.refresh()` ;
- `GOIAClient.explain()` ;
- `GOIAClient.checkout()` ultérieurement ;
- tests contractuels générés depuis OpenAPI ;
- SDK Python async puis TypeScript.

Décision : **réutiliser les patterns, créer un client versionné**.

## 5. Composants à conserver, adapter, créer ou geler

| Domaine | Décision |
|---|---|
| Manifeste machine IAT | Conserver et étendre |
| Decision Core | Adapter |
| Buyer Intent | Adapter |
| Seller Runtime IA | Conserver |
| Catalogue vendeur IA | Ne pas détourner |
| Growth Engine | Généraliser |
| Action Engine | Durcir puis réutiliser |
| Checkout USDC-IAT devnet | Geler |
| Ledger double entrée | Étendre |
| API centrale monolithique | Réduire progressivement |
| DB monolithique | Découper |
| Agents de démonstration | Isoler du produit |
| GOIA Crawler | Créer |
| GOIA Index | Créer |
| Offer Verification | Créer |
| Partner Registry | Créer |
| Attribution Engine | Créer |
| Commission Disclosure | Créer |

## 6. Architecture cible

```text
Clients humains / agents / SDK
              |
              v
        GOIA Public API
              |
      +-------+---------+
      |                 |
 Search Intent      Results/Explain
      |                 |
      +-------+---------+
              |
        GOIA Query Core
              |
      +-------+---------+----------------+
      |                 |                |
  Local Index      Freshness        Ranking IAT
      |             Policies         (organic)
      |                 |                |
      +-------- Verification ------------+
              |
      GOIA Collection Plane
      |       |       |        |
  Sitemap  JSON-LD  Catalog  Targeted fetch
      |       |       |        |
      +-------+-------+--------+
              |
          Open Web

Demand signals ----------------> Partnership Engine
                                      |
                         Prospect / qualify / negotiate
                                      |
                         Merchant / network / comparator
                                      |
                         Catalog + attribution contract

Conversions --> Attribution --> Commission Ledger --> IAT Settlement
```

### Frontières obligatoires

1. Le query path ne lance pas un crawl large synchrone.
2. Le crawler ne possède aucune clé de paiement.
3. Le classement organique ne reçoit pas le taux de commission comme métrique.
4. L'attribution ne peut pas modifier rétroactivement une recommandation.
5. Le LLM ne constitue jamais une source de prix ou de disponibilité.
6. Toute donnée externe conserve source, date, méthode et confiance.
7. Les tâches Web sont exécutées hors du serveur API.

## 7. Modèle de données cible

### 7.1 Offre et preuve

Entités minimales :

- `Merchant`
- `MerchantDomain`
- `CatalogSource`
- `Product`
- `ProductVariant`
- `Service`
- `Offer`
- `OfferObservation`
- `Evidence`
- `PriceHistory`
- `AvailabilityObservation`
- `ShippingPolicy`
- `ReturnPolicy`

Chaque observation doit contenir :

- identifiant stable ;
- URL canonique ;
- attribut ;
- valeur normalisée ;
- valeur brute ;
- devise/unité ;
- méthode d'extraction ;
- date d'observation ;
- date d'expiration ;
- hash de la preuve ;
- score de confiance ;
- statut de vérification.

### 7.2 Partenariat

Entités minimales :

- `PartnershipProspect`
- `PartnershipOpportunity`
- `PartnershipContact`
- `PartnershipConversation`
- `Partnership`
- `AffiliateProgram`
- `AttributionRule`
- `CommercialTerm`
- `PartnerCatalogCredential`

### 7.3 Conversion

Entités minimales :

- `Referral`
- `Click`
- `Lead`
- `Conversion`
- `CommissionClaim`
- `CommissionAdjustment`
- `CommissionPayout`
- `AttributionEvidence`

Les données personnelles doivent être minimisées et séparées des données
d'offre et de classement.

## 8. Politique d'indépendance et de classement

### 8.1 Principe

GOIA doit rechercher la meilleure réponse pour le client indépendamment de la
relation commerciale.

Le moteur organique peut utiliser :

- conformité aux contraintes ;
- coût total ;
- qualité ;
- confiance ;
- fraîcheur ;
- disponibilité ;
- livraison ;
- retours ;
- fiabilité du marchand ;
- incertitude.

Il ne doit pas utiliser :

- taux de commission ;
- valeur attendue pour IAT ;
- priorité négociée ;
- budget publicitaire.

### 8.2 Présentation

Chaque résultat doit exposer :

- `organic_rank` ;
- `commercial_relationship` ;
- `sponsored` ;
- `commission_may_be_earned` ;
- `commission_changes_organic_rank: false` ;
- raisons du classement ;
- date de vérification.

Une offre sponsorisée doit être présentée séparément et explicitement.

## 9. Stratégie de collecte à coût marginal faible

Ordre de préférence :

1. catalogues fournis par les partenaires ;
2. sitemaps ;
3. JSON-LD Schema.org ;
4. pages autorisées et extracteurs génériques ;
5. extracteurs spécifiques aux domaines prioritaires ;
6. Common Crawl pour amorçage et découverte ;
7. métarecherche auto-hébergée comme secours de découverte ;
8. API privée uniquement en secours plafonné, jamais comme dépendance centrale.

Politique de fraîcheur indicative :

| Donnée | Durée indicative |
|---|---:|
| Disponibilité volatile | 5 à 15 minutes |
| Prix volatil | 15 à 60 minutes |
| Prix stable | 6 à 24 heures |
| Livraison | 1 à 7 jours |
| Caractéristiques | 7 à 30 jours |
| Conditions contractuelles | 1 à 7 jours |
| Identité marchand | 30 jours |

Avant une transaction, GOIA effectue une vérification ciblée de l'offre
sélectionnée au lieu de rafraîchir tout le marché.

## 10. Moteur de prospection partenaires

### 10.1 Entrées

- requêtes agrégées ;
- taux de résultats insuffisants ;
- catégories sans offre fraîche ;
- marchands fréquemment cités ;
- comparateurs pertinents ;
- programmes d'affiliation publics ;
- couverture géographique ;
- qualité et réputation.

### 10.2 Score de prospect

Proposition initiale :

| Signal | Poids |
|---|---:|
| Demande réelle IAT/GOIA | 30 % |
| Compatibilité du catalogue | 20 % |
| Qualité et réputation | 15 % |
| Intégration technique | 15 % |
| Potentiel économique | 10 % |
| Fraîcheur accessible | 5 % |
| Risque | 5 % |

Le potentiel économique sert à prioriser la prospection, pas à classer les
offres pour l'acheteur.

### 10.3 Cycle

```text
discovered
  -> qualified
  -> human_review
  -> contact_ready
  -> contacted
  -> interested
  -> negotiating
  -> contracted
  -> integrating
  -> active
  -> paused/terminated
```

Au lancement :

- découverte et qualification automatisées ;
- dossier et message préparés automatiquement ;
- validation humaine obligatoire avant envoi ;
- fréquence et suppression héritées de Growth ;
- aucune tentative de contournement de canaux ou refus.

## 11. Risques prioritaires

### P0 — avant tout crawler

1. Séparer le worker Web du processus API.
2. Mettre en place la protection SSRF complète.
3. Définir robots, fréquence, retrait et identité `GOIABot`.
4. Traiter le contenu Web comme hostile.
5. Séparer les secrets collecte, partenariat et paiement.
6. Définir une politique de rétention des pages.

### P0 — dépôt et secrets

Des artefacts sensibles ou historiques sont suivis par Git :

- `iat_backup.dump`
- `backups/agent_b_api_broken_20260429_134829.py`
- plusieurs fichiers `.bak` présents dans le répertoire de travail.

Leur contenu n'a pas été reproduit dans cet audit. Il faut :

1. analyser localement leur sensibilité sans les afficher dans les logs ;
2. faire tourner tout secret potentiellement exposé ;
3. retirer les artefacts du suivi Git ;
4. nettoyer l'historique si une donnée sensible est confirmée ;
5. stocker les backups hors dépôt avec chiffrement et accès contrôlé.

### P1 — architecture

1. Extraire progressivement les routers de `agent_b_api.py`.
2. Ne plus ajouter de métier dans `db.py`.
3. Créer migrations et repositories GOIA.
4. Définir les événements entre GOIA et IAT.
5. Éliminer les doubles chemins canoniques/historiques après télémétrie.

### P1 — commerce

1. Séparer organique, affilié et sponsorisé.
2. Versionner les règles d'attribution.
3. Gérer retours, annulations et clawbacks.
4. Ne comptabiliser aucune commission avant validation.
5. Prévoir les obligations de disclosure et protection consommateur.

### P2 — qualité

1. Tests PostgreSQL.
2. Tests concurrents des workers.
3. Jeu de vérité terrain pour les offres.
4. Mesure de fraîcheur et exactitude.
5. Tests contractuels des catalogues.
6. Monitoring et budgets par domaine.

## 12. Dette technique observée

- monolithes API et DB ;
- nombre élevé de routes administratives/internes ;
- logique historique parallèle aux chemins canoniques ;
- schéma versionné mais migrations incrémentales limitées ;
- exceptions générales et opérations best-effort ;
- `float` encore utilisé dans des décisions monétaires ;
- workers distribués incomplets ;
- boucle autonome dans le serveur web ;
- auth Foundation unique ;
- clés vendeur non hashées ;
- intégrations externes inégalement testées ;
- documentation et code parfois en décalage ;
- sauvegardes et fichiers historiques suivis dans Git.

La suite de 189 tests constitue un actif, mais elle reste faible par rapport
aux quelque 72 000 lignes et à la surface d'environ 300 routes. Une mesure de
couverture fiable par domaine doit être ajoutée à la CI.

## 13. Feuille de route recommandée

### Phase 0 — gouvernance du chantier

Livrables :

- choix provisoire du nom ;
- principes d'impartialité ;
- politique de collecte ;
- politique commerciale ;
- définition du secteur pilote ;
- critères de succès.

Critère de sortie :

- décisions écrites et approuvées.

### Phase 1 — frontières et contrats

Livrables :

- architecture GOIA ;
- `SearchIntent v1` ;
- `OfferObservation v1` ;
- `Merchant/Partner v1` ;
- événements GOIA vers IAT ;
- contrat `/.well-known/goia-provider.json`.

Critère de sortie :

- contrats testés sans crawler.

### Phase 2 — index local pilote

Livrables :

- migrations GOIA ;
- repositories ;
- ingestion manuelle de catalogues ;
- recherche locale ;
- classement organique ;
- preuves et fraîcheur ;
- API publique de recherche.

Critère de sortie :

- résultats déterministes sur un jeu de référence.

### Phase 3 — collecte ouverte ciblée

Livrables :

- worker séparé ;
- robots et sitemaps ;
- extracteur JSON-LD ;
- fetcher sécurisé ;
- scheduler ;
- cache et détection de changements ;
- tableau de bord de collecte.

Critère de sortie :

- collecte stable de quelques domaines autorisés sans intervention.

### Phase 4 — partenariat

Livrables :

- extension Growth ;
- scoring fondé sur la demande ;
- registre de partenaires ;
- pipeline de négociation ;
- catalogues partenaires ;
- validation humaine de l'outreach.

Critère de sortie :

- premier partenaire intégré ou programme d'affiliation accepté.

### Phase 5 — attribution et commission

Livrables :

- liens/codes/attribution ;
- conversion et fenêtre de validation ;
- ledger de commission ;
- ajustements et annulations ;
- disclosures ;
- rapprochement.

Critère de sortie :

- première commission testée de bout en bout en environnement contrôlé.

### Phase 6 — intégration IAT

Livrables :

- handoff vers checkout ;
- règlement IAT ;
- réputation post-transaction ;
- litiges ;
- monitoring financier.

Critère de sortie :

- transaction pilote vérifiée, réconciliée et auditable.

## 14. Secteur pilote recommandé

Commencer par :

- logiciels SaaS ;
- API ;
- hébergement ;
- outils pour agents et IA ;
- services numériques standardisés.

Raisons :

- cohérence avec l'audience actuelle d'IAT ;
- catalogues et prix plus faciles à structurer ;
- absence de logistique physique ;
- programmes d'affiliation fréquents ;
- couverture internationale ;
- possibilité de livraison et validation numériques.

Éviter au premier pilote :

- produits réglementés ;
- crédit et finance grand public ;
- santé ;
- voyages complexes ;
- marketplaces à variantes logistiques importantes ;
- biens à fort taux de retour.

## 15. Indicateurs de succès

### Recherche

- taux de requêtes satisfaites ;
- précision prix/disponibilité ;
- âge médian des observations ;
- taux de résultats cités ;
- coût infrastructure par recherche ;
- latence p50/p95 ;
- taux de cache.

### Comparaison

- respect des contraintes ;
- taux de clic sur le premier résultat ;
- taux de changement après vérification ;
- taux de plaintes ;
- stabilité et diversité des résultats.

### Partenariat

- prospects qualifiés ;
- taux de réponse ;
- taux d'accord ;
- délai d'intégration ;
- catalogues actifs ;
- fraîcheur partenaire.

### Économie

- conversions attribuées ;
- commissions validées ;
- commissions annulées ;
- revenu par mille recherches ;
- coût par conversion ;
- couverture des coûts d'infrastructure.

### Confiance

- part de résultats affiliés ;
- part de résultats non affiliés classés premiers ;
- disclosures affichés ;
- différences entre classement organique et sponsorisé ;
- incidents de données ou collecte.

## 16. Décisions à prendre avant le premier code GOIA

1. Confirmer GOIA comme nom de travail.
2. Choisir le secteur pilote exact.
3. Valider que le classement organique ignore toujours la commission.
4. Choisir le premier pays et la première devise.
5. Définir les règles de collecte et de retrait.
6. Définir le niveau de validation humaine de la prospection.
7. Choisir si GOIA démarre dans le même dépôt ou comme service séparé.
8. Définir le budget d'infrastructure maximal du pilote.

## 17. Recommandation finale

Le protocole actuel doit être considéré comme un socle économique et de
gouvernance, pas comme l'endroit où accumuler toute la logique de recherche.

La trajectoire recommandée est :

```text
IAT Protocol
    = confiance + décision + exécution + paiement + commission

GOIA
    = demande + index + comparaison + preuve + partenaires
```

La prochaine étape ne doit pas être le crawler. Elle doit être la
spécification des contrats GOIA et la séparation nette entre :

- recherche organique ;
- relation commerciale ;
- attribution ;
- règlement.

Une fois ces frontières validées, le premier code pourra être un index pilote
alimenté par des catalogues contrôlés, puis enrichi progressivement par le Web
ouvert.
