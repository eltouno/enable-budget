# EnableBudget Mac (SwiftUI)

Objectif: application macOS native répliquant le flux du script `enable_budget_web.py` pour gérer l’accès aux comptes via Enable Banking, stocker les secrets/localement et exporter les transactions en CSV.

## Fonctionnalités MVP

- Authentification Enable (`/auth` → banque → callback) via `ASWebAuthenticationSession`.
- Échange du `code` contre `session_id` + liste des comptes (`/sessions`).
- Consultation des soldes (`/accounts/{uid}/balances`).
- Consultation des transactions avec filtre date et pagination (`/accounts/{uid}/transactions`).
- Export CSV (aplatissement JSON) via panneau d’enregistrement.
- Stockage pérenne: `APP_ID` et clé privée PEM en Keychain, `session_id` en Keychain, comptes/état en `Application Support`.

## Pré-requis

- Xcode 15+ (macOS 13+ recommandé).
- Avoir un `APP_ID` Enable et une clé privée RSA (PEM, RS256), identiques à celles utilisées par le script.
- Avoir ajouté une URL de redirection dans le dashboard Enable (whitelist): par exemple `enablebudget://callback`.

## Création rapide du projet Xcode

1) Ouvrir Xcode → Create a new Project → App (macOS) → Interface: SwiftUI → Language: Swift.
2) Nommer l’app « EnableBudget » (ou autre). Identifiant de bundle: com.votreorg.EnableBudget.
3) Dans « Signing & Capabilities », activer App Sandbox (Network Outbound) si nécessaire.
4) Dans « Info » → URL Types:
   - Identifier: `enablebudget`
   - URL Schemes: `enablebudget`
   - Role: Editor
   - Document Types: non nécessaire.
5) Dans Enable (dashboard), ajouter `enablebudget://callback` comme `redirect_url` autorisée.
6) Ajoutez les fichiers Swift de `macos/EnableBudgetMac/Sources/` dans votre projet (glisser-déposer, « Copy items if needed » coché).

## Variables à configurer (dans l’app)

- APP ID (Enable): à saisir dans l’écran « Réglages ». Stocké en Keychain.
- Clé privée PEM (RSA): coller le contenu PEM (PKCS#1 `BEGIN RSA PRIVATE KEY` ou PKCS#8 `BEGIN PRIVATE KEY`). Stockée en Keychain.
- API Base (optionnel): par défaut `https://api.enablebanking.com`.
- Redirect URL: `enablebudget://callback` (doit être whitelistée chez Enable).

## Notes sécurité

- La clé privée est stockée dans le trousseau (Keychain) de l’utilisateur. Vous pouvez restreindre davantage (kSecAttrAccessible). N’embarquez pas la clé dans le binaire.
- Le `session_id` Enable est stocké aussi en Keychain; les listes de comptes sont stockées en clair dans `Application Support`.

## Organisation du code

- `Core/JWT.swift`: création JWT RS256 via `Security` et la clé PEM.
- `Core/EnableAPI.swift`: appels HTTP et pagination.
- `Core/WebAuth.swift`: gestion `ASWebAuthenticationSession` pour le parcours consentement.
- `Core/Keychain.swift`: helpers Keychain.
- `Core/Persistence.swift`: lecture/écriture `Application Support`.
- `Core/CSV.swift`: export CSV à partir d’objets JSON dynamiques.
- `App/*.swift`: vues SwiftUI basiques pour onboarding, comptes et transactions.

## Limitations connues

- Le schéma JWT RS256 gère PKCS#1 et PKCS#8 les plus courants; si votre PEM a un encodage atypique, convertissez-le en PKCS#8.
- Les modèles JSON sont peu typés; l’UI affiche les champs principaux si présents.

## Prochaines étapes suggérées

- Ajouter cache des transactions (offline), filtrage/tri avancés.
- Gérer les erreurs spécifiques (422, consent expired) avec UX dédiée.
- Internationalisation et thèmes.

