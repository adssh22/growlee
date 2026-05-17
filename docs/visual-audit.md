# Growlee — audit CSS/visuel avant refactor

Date : 2026-05-17

Objectif : identifier quoi factoriser sans refaire le design, sans supprimer les animations et sans casser les variables dynamiques merchant.

## Synthèse exécutive

Le design Growlee est cohérent et premium, mais le CSS est fortement concentré dans des blocs `<style>` inline, souvent minifiés sur quelques lignes. Le risque principal n’est pas esthétique : c’est la maintenabilité.

Constats clés :

- 25 templates contiennent au moins un bloc `<style>`.
- Les plus gros foyers CSS sont :
  1. `templates/public/home.html`
  2. `templates/public/play.html`
  3. `templates/admin/base.html`
  4. `templates/public/info_page.html`
  5. `templates/admin/onboarding.html`
  6. `templates/admin/login.html` / `templates/admin/signup.html`
- Les tokens visuels sont très dupliqués : violet, vert, ink, muted, paper, radius, shadows, glassmorphism.
- `!important` est massivement utilisé dans certains templates, surtout landing/nav/dark mode.
- Le dark mode est premium mais fragile, car il repose souvent sur des overrides très spécifiques et `!important`.
- Le responsive existe partout, mais il est dispersé par page au lieu d’être porté par des composants/layouts communs.
- Les animations participent à la signature premium ; il faut les préserver, mais les isoler dans une couche dédiée avec `prefers-reduced-motion`.

Recommandation : refactor progressif en couches, pas extraction massive en une fois.

## Templates inspectés

| Fichier | Zone | Taille CSS approx. | Risque |
| --- | --- | ---: | --- |
| `templates/public/home.html` | landing publique | ~266k chars | Très élevé |
| `templates/public/play.html` | parcours client mobile | ~42k chars | Très élevé |
| `templates/admin/base.html` | admin commerçant | ~28k chars | Très élevé |
| `templates/public/info_page.html` | landing publique / pages info | ~25k chars | Élevé |
| `templates/admin/onboarding.html` | admin commerçant / onboarding | ~20k chars | Élevé |
| `templates/admin/signup.html` | auth | ~14k chars | Élevé |
| `templates/admin/login.html` | auth | ~12k chars | Élevé |
| `templates/public/contact.html` | pages légales/contact | ~7k chars | Moyen |
| `templates/admin/configuration.html` | admin commerçant | ~7k chars | Moyen |
| `templates/public/partners.html` | pages publiques/contact | ~6k chars | Moyen |
| `templates/admin/staff_merchants.html` | Growlee Control | ~5k chars | Moyen |
| `templates/admin/staff_merchant_detail.html` | Growlee Control | ~3k chars | Moyen |
| `templates/admin/staff_support.html` | Growlee Control | ~3k chars | Moyen |
| `templates/admin/pending_payment.html` | auth/billing | ~3k chars | Moyen |
| `templates/admin/rewards.html` | admin commerçant | ~2.6k chars | Faible/Moyen |
| `templates/public/reward_claim.html` | parcours client mobile | ~2.2k chars | Moyen |
| `templates/admin/staff_control_mfa_setup.html` | Growlee Control/auth | ~2.2k chars | Faible |
| `templates/admin/staff_control_verify.html` | Growlee Control/auth | ~1.6k chars | Faible |
| `templates/admin/employee.html` | admin commerçant/mobile | ~1.4k chars | Moyen |
| `templates/admin/customer_detail.html` | admin commerçant | ~1.3k chars | Faible |
| `templates/public/demo.html` | landing publique | ~1.2k chars | Faible |
| `templates/public/wallet_pending.html` | parcours client mobile | ~1k chars | Moyen |
| `templates/admin/game_config.html` | admin commerçant | <1k chars | Faible |
| `templates/public/rate_limited.html` | public/system | <1k chars | Faible |
| `templates/public/legal.html` | pages légales/contact | <1k chars | Faible |

## Métriques notables

| Fichier | `!important` | `@media` | dark mode refs | `@keyframes` | animations |
| --- | ---: | ---: | ---: | ---: | ---: |
| `public/home.html` | ~2913 | 58 | ~519 | 65 | 72 |
| `public/play.html` | ~302 | 13 | 7 | 12 | 16 |
| `public/info_page.html` | ~336 | 10 | 63 | 0 | 0 |
| `admin/base.html` | ~229 | 4 | 51 | 1 | 1 |
| `admin/login.html` | ~140 | 5 | 0 | 0 | 0 |
| `admin/signup.html` | ~140 | 6 | 0 | 0 | 0 |
| `admin/onboarding.html` | ~78 | 2 | 50 | 1 | 1 |

Interprétation :

- `public/home.html` est devenu une mini design-system dans un template. C’est prioritaire, mais dangereux à extraire brutalement.
- `public/play.html` a beaucoup de variables merchant dynamiques (`--brand`, `--accent`, fonts, couleurs). Il faut le traiter comme une app mobile thémable, pas comme une page statique.
- `admin/base.html` est le bon point d’ancrage pour extraire les tokens et composants admin.
- `login.html` et `signup.html` semblent partager une structure très proche : bon candidat pour factorisation rapide.

## Duplications de tokens

### Couleurs récurrentes

Tokens observés très souvent :

- Violet marque : `#534ab7`, `#534AB7`, `#766cf0`, `#766CF0`, `#afa9ec`, `#30257f`.
- Vert accent : `#1d9e75`, `#1D9E75`, `#72e0bc`, `#72E0BC`, `#3f9d87`.
- Texte : `#17152b`, `#172033`, `#111827`, `#0f172a`, `#69647f`, `#6f6b86`.
- Fond : `#fbfbff`, `#f7f6ff`, `#fff`, `#ffffff`, `#f8fafc`.
- Bordures : `#eceaf7`, `#e5e7eb`, `rgba(39,32,91,...)`.
- Danger : `#b42318`, `#ef4444`, `#fee4e2`, `#fff1f0`.
- Success : `#1d9e75`, `#22c55e`, `#067647`, `#ecfdf3`.

Problème : mêmes valeurs avec casse différente et variations proches. Cela rend les ajustements dark/light ou contraste très coûteux.

Proposition de tokens globaux :

```css
:root {
  --gw-purple: #534ab7;
  --gw-purple-2: #766cf0;
  --gw-purple-soft: #afa9ec;
  --gw-purple-dark: #30257f;
  --gw-green: #1d9e75;
  --gw-green-2: #72e0bc;
  --gw-ink: #17152b;
  --gw-muted: #69647f;
  --gw-paper: #fbfbff;
  --gw-surface: #ffffff;
  --gw-line: #eceaf7;
  --gw-danger: #b42318;
  --gw-success: #1d9e75;
}
```

À ne pas confondre avec les variables merchant du parcours client :

- `--brand`
- `--accent`
- `--brand-dark`
- `--font-heading`
- `--font-body`

Ces variables doivent rester dynamiques et proches du template ou injectées via un petit bloc style dédié.

### Spacing / radius / shadows

Patterns récurrents :

- Radius : `18px`, `20px`, `24px`, `28px`, `32px`, `999px`.
- Padding cartes : `18px`, `20px`, `24px`, `28px`, `30px`, `32px`.
- Ombres : nombreuses variantes de `0 20px 50px rgba(...)`, `0 24px 70px`, `0 30px 90px`.
- Glassmorphism : `background: rgba(255,255,255,.8/.9)`, `backdrop-filter: blur(...)`, border translucide.

Proposition :

```css
:root {
  --gw-radius-sm: 14px;
  --gw-radius-md: 20px;
  --gw-radius-lg: 28px;
  --gw-radius-xl: 36px;
  --gw-radius-pill: 999px;
  --gw-space-1: 4px;
  --gw-space-2: 8px;
  --gw-space-3: 12px;
  --gw-space-4: 16px;
  --gw-space-5: 20px;
  --gw-space-6: 24px;
  --gw-space-8: 32px;
  --gw-shadow-card: 0 20px 60px rgba(39,32,91,.10);
  --gw-shadow-elevated: 0 30px 90px rgba(39,32,91,.16);
}
```

## Composants récurrents à factoriser

### Global/public

- `.btn`, `.btn.primary`, `.btn.secondary`.
- `.nav`, `.links`, hamburger, theme toggle.
- `.card`, `.section`, `.hero`, `.badge`, `.pill`.
- Footer / brand block.
- Ambient backgrounds : gradients, blobs, glass panels.
- Form fields public contact/partner.

### Admin commerçant

- Layout shell/sidebar/topbar dans `admin/base.html`.
- `.card`, `.metric-card`, `.list-row`, `.status-row`.
- `.btn`, `.secondary`, `.neutral`, `.danger`.
- Badges/pills/status.
- Module cards / switches.
- Form fields admin.
- Empty states.

### Growlee Control

- Staff hero/top/brand/wrap.
- Stats grid.
- Tables/cards.
- Badges `on/off/warn/danger`.
- Delete/archive boxes.
- Filters/search.

Ces styles sont actuellement recopiés dans :

- `staff_merchants.html`
- `staff_merchant_detail.html`
- `staff_support.html`
- `staff_control_mfa_setup.html`
- `staff_control_verify.html`

### Auth

`admin/login.html` et `admin/signup.html` partagent fortement :

- shell split layout ;
- intro/proof/steps ;
- card formulaire ;
- background grid/orbs ;
- badges/liens ;
- responsive mobile.

C’est un bon candidat de migration rapide vers `auth.css` ou un partial CSS commun.

### Parcours client mobile

`public/play.html`, `reward_claim.html`, `wallet_pending.html` partagent :

- mobile app shell ;
- panels/cartes ;
- CTA ;
- reward pass/ticket ;
- variables couleur merchant ;
- animations roue/confetti/scratch.

À traiter avec prudence : c’est la zone la plus sensible aux variables dynamiques merchant.

## Classes redondantes ou ambiguës

Classes très génériques utilisées dans plusieurs zones avec sens potentiellement différent :

- `.btn`
- `.card`
- `.badge`
- `.pill`
- `.hero`
- `.grid`
- `.top`
- `.brand`
- `.muted`
- `.secondary`
- `.danger`
- `.wrap`

Risque : si elles deviennent globales trop vite, elles peuvent casser des pages par collision.

Recommandation : utiliser des préfixes par couche avant globalisation :

- `.gw-btn`, `.gw-card`, `.gw-badge` pour composants globaux.
- `.admin-card`, `.admin-pill` ou garder le scope admin sous `.admin-shell`.
- `.control-card`, `.control-badge` pour Growlee Control si besoin.
- `.play-card`, `.play-cta` pour parcours client mobile.

## Surusage de `!important`

Foyers principaux :

1. `public/home.html` : ~2913 occurrences.
2. `public/info_page.html` : ~336.
3. `public/play.html` : ~302.
4. `admin/base.html` : ~229.
5. `admin/login.html` / `admin/signup.html` : ~140 chacun.
6. `admin/onboarding.html` : ~78.

Racines probables :

- overrides dark mode ;
- overrides responsive/nav ;
- classes génériques qui se battent entre elles ;
- style inline compact issu d’itérations rapides ;
- besoin de préserver un rendu premium sans design-system stable.

Objectif raisonnable : ne pas viser zéro `!important` immédiatement. Viser d’abord :

- réduire dans les composants extraits ;
- conserver temporairement les overrides critiques ;
- supprimer les `!important` uniquement quand le scope CSS est clair.

## Dark mode fragile

Zones concernées :

- `public/home.html` : dark mode riche mais très volumineux.
- `public/info_page.html` : nav/theme/footer avec nombreux overrides.
- `admin/base.html` : tokens dark admin et overrides composants.
- `admin/onboarding.html` : dark mode spécifique.
- `public/contact.html`, `public/partners.html` : dark mode partiel.

Risques :

- contraste variable selon carte/glass background ;
- états hover/focus parfois définis en light puis forcés en dark ;
- liens/nav dépendants de `!important` ;
- composants recopiés avec dark mode incomplet d’une page à l’autre.

Recommandation : créer deux fichiers de tokens :

- `tokens.css` pour light par défaut ;
- `themes.css` pour `html[data-theme="dark"]`.

Puis migrer les pages une par une vers ces tokens sans changer le rendu.

## Mobile fragile

Zones sensibles :

- `public/home.html` : 58 `@media`, beaucoup de sections marketing et animations.
- `public/play.html` : parcours mobile critique, roue/scratch/ticket/review/wallet.
- `admin/base.html` : sidebar/topbar/navigation admin responsive.
- `admin/login.html` / `admin/signup.html` : split layout mobile.
- `admin/onboarding.html` : workflow multi-step, formulaires, preview flyer.

Risques :

- media queries page-spécifiques répétées ;
- cartes avec dimensions fixes ;
- animations et éléments absolus pouvant déborder ;
- zones tap/click parfois visuelles plus que structurelles ;
- viewport mobile réel différent des largeurs de test.

À vérifier à chaque extraction :

- 360px, 390px, 430px ;
- 768px tablette ;
- desktop 1280/1440 ;
- dark + light ;
- navigation clavier/focus.

## Animations coûteuses

Foyers :

- `public/home.html` : 65 `@keyframes`, 72 `animation:`.
- `public/play.html` : 12 `@keyframes`, 16 `animation:`.
- `public/contact.html` : 2 animations.
- `admin/onboarding.html`, `admin/employee.html`, `public/demo.html` : animations ponctuelles.

À ne pas supprimer : elles font partie de la signature premium.

À améliorer progressivement :

- isoler les animations dans `animations.css` ;
- privilégier `transform` et `opacity` ;
- éviter animations continues sur grosses ombres/blur si possible ;
- ajouter un garde-fou global :

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: .01ms !important;
    animation-iteration-count: 1 !important;
    scroll-behavior: auto !important;
  }
}
```

À introduire prudemment : certaines animations de jeu doivent rester fonctionnelles ; le reduced-motion peut simplifier sans casser.

## Accessibilité — points à auditer en refactor

Problèmes potentiels observés par structure CSS :

- focus styles pas toujours visibles sur boutons/liens custom ;
- contraste à vérifier sur gradients, glass cards et dark mode ;
- animations nombreuses sans couche reduced-motion globale ;
- navigation hamburger/theme toggle : vérifier `aria-expanded`, labels et focus trap éventuel ;
- cartes cliquables : vérifier que l’élément interactif réel est focusable ;
- formulaires : s’assurer que les labels restent associés aux inputs après factorisation ;
- tailles de tap targets sur mobile client/admin ;
- messages d’erreur : contraste et association au champ.

Priorité accessibilité : parcours client mobile (`play.html`, `reward_claim.html`) + auth + checkout/paiement.

## Analyse par zone

### 1. Landing publique

Fichiers :

- `templates/public/home.html`
- `templates/public/info_page.html`
- `templates/public/demo.html`
- `templates/public/partners.html`

Constats :

- `home.html` contient une très grande quantité de CSS et agit comme design-system public autonome.
- Nav, boutons, cartes, sections, badges, footer, dark mode et animations sont réutilisables.
- `info_page.html` semble dupliquer une partie de la nav/brand/theme/footer.
- `partners.html` partage l’univers public mais avec styles propres de formulaires/tableaux.

Priorité : très haute pour `home.html`, mais migration lente.

Plan recommandé :

1. Extraire uniquement tokens publics + reset léger.
2. Extraire nav/footer publics.
3. Extraire boutons/cards/badges publics.
4. Laisser les sections marketing complexes dans `home.html` au début.
5. Migrer `info_page.html`, puis `partners.html`, puis `contact.html` vers les composants publics.

### 2. Admin commerçant

Fichiers :

- `templates/admin/base.html`
- `templates/admin/configuration.html`
- `templates/admin/customer_detail.html`
- `templates/admin/employee.html`
- `templates/admin/game_config.html`
- `templates/admin/onboarding.html`
- `templates/admin/pending_payment.html`
- `templates/admin/rewards.html`

Constats :

- `admin/base.html` contient déjà une base forte : tokens `--color-*`, boutons, cards, rows, sidebar/topbar.
- Certaines pages ajoutent des styles petits mais répétitifs.
- `onboarding.html` est une page spéciale, visuellement riche, avec son propre système `--gw-*`.
- `configuration.html` contient des composants modules très importants à préserver.

Priorité : haute pour `admin/base.html` + `configuration.html`; moyenne pour pages spécialisées.

Plan recommandé :

1. Stabiliser `admin.css` à partir de `admin/base.html`.
2. Extraire composants admin communs : card, btn, badge, grid, switch, module-card.
3. Migrer pages simples : rewards, customer_detail, game_config.
4. Migrer configuration par blocs, sans changer l’organisation modulaire.
5. Garder onboarding en dernier dans admin : plus complexe et très brandé.

### 3. Growlee Control

Fichiers :

- `templates/admin/staff_merchants.html`
- `templates/admin/staff_merchant_detail.html`
- `templates/admin/staff_support.html`
- `templates/admin/staff_control_mfa_setup.html`
- `templates/admin/staff_control_verify.html`

Constats :

- Les pages staff partagent un mini design-system : `wrap`, `top`, `brand`, `hero`, `stats`, `badge`, `pill`, `btn`, `card`.
- Les mêmes couleurs reviennent : `#4e3db7`, `#3f9d87`, `#17152b`, `#6f6b86`, `#eceaf7`, `#f7f6ff`.
- Peu de dark mode actuellement, donc le refactor est moins risqué visuellement.

Priorité : moyenne/haute, bon rendement.

Plan recommandé :

1. Créer `control.css`.
2. Extraire layout staff + boutons + badges + cards + tables.
3. Migrer `staff_merchants`, `staff_merchant_detail`, `staff_support` ensemble.
4. Migrer MFA ensuite ou le rattacher à `auth.css` selon rendu souhaité.

### 4. Parcours client mobile

Fichiers :

- `templates/public/play.html`
- `templates/public/reward_claim.html`
- `templates/public/wallet_pending.html`

Constats :

- `play.html` est critique business et très dynamique.
- Les variables merchant pilotent couleur et typographie. Il ne faut pas les déplacer naïvement dans un CSS statique.
- Beaucoup de composants récurrents : app shell, panel, choice, CTA, reward pass, wallet card, review choices.
- Animations jeu/confetti/scratch doivent rester intactes.

Priorité : haute, mais à migrer très prudemment.

Plan recommandé :

1. Garder un petit bloc inline uniquement pour variables merchant :
   - `--brand`
   - `--accent`
   - `--brand-dark`
   - `--font-heading`
   - `--font-body`
2. Extraire CSS statique dans `play.css`.
3. Extraire animations dans `play-animations.css` ou section dédiée.
4. Migrer `reward_claim.html` et `wallet_pending.html` vers les mêmes tokens mobile.
5. Vérifier impérativement mobile light/dark, toutes étapes du parcours, gains, review, wallet.

### 5. Auth

Fichiers :

- `templates/admin/login.html`
- `templates/admin/signup.html`
- `templates/admin/pending_payment.html`
- éventuellement `staff_control_mfa_setup.html`, `staff_control_verify.html`

Constats :

- Login/signup ont une duplication évidente et un volume CSS élevé.
- Bon candidat pour une extraction rapide avec faible risque fonctionnel.
- `pending_payment.html` partage les tokens mais est plus billing/plan.

Priorité : haute pour quick win.

Plan recommandé :

1. Créer `auth.css`.
2. Extraire shell, card, intro, steps, proof, fields.
3. Migrer login + signup dans le même commit.
4. Vérifier mobile + erreurs formulaire.
5. Ajouter pending_payment si le rendu converge.

### 6. Pages légales/contact

Fichiers :

- `templates/public/contact.html`
- `templates/public/legal.html`
- `templates/public/rate_limited.html`
- `templates/public/partners.html`
- `templates/public/info_page.html`

Constats :

- `legal.html`, `rate_limited.html` sont simples.
- `contact.html` et `partners.html` partagent des composants publics/formulaires.
- `info_page.html` est plus proche de la landing publique que des pages légales simples.

Priorité : moyenne.

Plan recommandé :

1. Après tokens/nav/footer publics, migrer `legal.html` et `rate_limited.html`.
2. Migrer `contact.html` avec composants de formulaire publics.
3. Migrer `partners.html` après stabilisation boutons/cards/tableaux publics.

## Fichiers prioritaires

### Priorité P0 — cartographie/refactor préparatoire

1. `templates/public/home.html`
2. `templates/public/play.html`
3. `templates/admin/base.html`

Pourquoi : plus gros volume CSS, plus grand impact, plus haut risque de régression.

### Priorité P1 — extraction à fort rendement

4. `templates/admin/login.html`
5. `templates/admin/signup.html`
6. `templates/public/info_page.html`
7. `templates/admin/onboarding.html`
8. `templates/admin/configuration.html`

Pourquoi : duplications visibles, pages importantes, mais extractibles par blocs.

### Priorité P2 — consolidation par zone

9. `templates/admin/staff_merchants.html`
10. `templates/admin/staff_merchant_detail.html`
11. `templates/admin/staff_support.html`
12. `templates/public/contact.html`
13. `templates/public/partners.html`
14. `templates/public/reward_claim.html`
15. `templates/public/wallet_pending.html`

Pourquoi : composants récurrents, taille moyenne, bon nettoyage après tokens.

### Priorité P3 — petits templates

16. `templates/admin/rewards.html`
17. `templates/admin/customer_detail.html`
18. `templates/admin/employee.html`
19. `templates/admin/game_config.html`
20. `templates/admin/pending_payment.html`
21. `templates/admin/staff_control_mfa_setup.html`
22. `templates/admin/staff_control_verify.html`
23. `templates/public/demo.html`
24. `templates/public/legal.html`
25. `templates/public/rate_limited.html`

Pourquoi : faible volume ou dépendants de composants extraits ailleurs.

## Plan de migration CSS progressif

### Étape 0 — règles de sécurité

- Un seul domaine visuel par PR/commit : public, admin, control, auth ou play.
- Ne pas modifier HTML métier sauf si nécessaire pour classes/scopes.
- Ne pas supprimer d’animations.
- Ne pas déplacer les variables merchant dynamiques dans un fichier statique.
- Capturer screenshots light/dark/mobile avant/après pour pages touchées.
- Garder les blocs inline temporairement si extraction incertaine.

### Étape 1 — créer l’architecture statique

Créer progressivement :

```text
static/css/
  growlee-tokens.css
  growlee-base.css
  growlee-components.css
  growlee-public.css
  growlee-admin.css
  growlee-control.css
  growlee-auth.css
  growlee-play.css
  growlee-animations.css
```

Ne pas tout remplir d’un coup. Commencer par tokens + une zone.

### Étape 2 — tokens globaux sans changement de rendu

- Extraire couleurs/radius/shadows/spacing les plus sûrs.
- Mapper les anciens tokens vers les nouveaux si besoin.
- Ne pas remplacer toutes les valeurs immédiatement.
- Objectif : rendre possible les extractions futures.

### Étape 3 — auth quick win

- Migrer `login.html` + `signup.html` vers `growlee-auth.css`.
- Réduire duplication et `!important`.
- Vérifier mobile, erreurs, liens, focus.

Pourquoi commencer ici : duplication forte, risque business modéré, feedback rapide.

### Étape 4 — admin base

- Extraire la base de `admin/base.html` vers `growlee-admin.css`.
- Garder les styles page-spécifiques dans les templates au début.
- Migrer progressivement : rewards, customer_detail, game_config.

### Étape 5 — Growlee Control

- Extraire le mini système staff vers `growlee-control.css`.
- Migrer les trois pages principales ensemble : list, detail, support.
- Vérifier tableaux, filtres, actions sensibles archive/delete.

### Étape 6 — public shared

- Extraire nav/footer/boutons/cards publics depuis `home.html` et `info_page.html`.
- Migrer `info_page.html` d’abord.
- Ensuite `contact.html`, `partners.html`, `legal.html`, `rate_limited.html`.

### Étape 7 — parcours client mobile

- Créer `growlee-play.css` avec CSS statique.
- Conserver inline uniquement : variables merchant et calculs dynamiques.
- Migrer par sections : shell → panels → wheel/scratch → reward pass → review/wallet.
- Ajouter tests visuels manuels stricts.

### Étape 8 — landing home

- Extraire composants stabilisés déjà migrés ailleurs.
- Laisser les sections marketing complexes tant qu’elles ne sont pas réutilisées.
- Isoler animations vers `growlee-animations.css` quand les tokens sont stables.
- Réduire `!important` par zones, pas globalement.

## Checklist de validation visuelle par migration

Pour chaque page touchée :

- Desktop 1440px light.
- Desktop 1440px dark si supporté.
- Mobile 390px light.
- Mobile 390px dark si supporté.
- Focus clavier visible.
- Hover/active boutons OK.
- Formulaires : erreurs et succès OK.
- Pas de scroll horizontal mobile.
- Animations présentes.
- `prefers-reduced-motion` ne casse pas le parcours.
- Variables merchant toujours appliquées sur parcours client.

## Recommandation finale

Ne pas commencer par `home.html` malgré son volume. Il est prioritaire à auditer, mais pas le meilleur premier refactor.

Ordre recommandé :

1. `auth.css` : login/signup.
2. `admin.css` : base admin + petites pages.
3. `control.css` : Growlee Control.
4. `public.css` : nav/footer/cards publics.
5. `play.css` : parcours client mobile avec variables merchant conservées inline.
6. `home.html` : extraction finale par sections stabilisées.

Cette approche réduit le risque, garde le design premium intact et évite une refonte brutale.
