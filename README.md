# Portfolio Les Conteurs

Le site des références de l’agence, alimenté par la base Notion
**Les Conteurs. Références**. Il est en ligne sur
https://les-conteurs-references.netlify.app.

## Comment ça marche

Toutes les heures en journée du lundi au vendredi (7 h-20 h environ), chaque nuit, et à la demande, GitHub Actions :

1. lit la base Notion publique ;
2. télécharge les **nouveaux** médias uniquement (les autres sont en cache) ;
3. compresse les vidéos (H.264, 720p, < 14 Mo) et les images (WebP) ;
4. génère le site dans `dist/` et le publie sur Netlify, **seulement si quelque chose a changé** dans Notion
   (sinon le passage s’arrête là, sans nouvelle publication).

Le site les-conteurs.com relit ces données au plus tard une heure après : une modification
dans Notion apparaît donc sur le site en 2 heures maximum en semaine. GitHub peut retarder
les passages programmés quand ses serveurs sont chargés.

Ajouter une référence = ajouter une ligne dans Notion. Rien d’autre.

## Ajouter ou modifier une référence dans Notion

| Ce que vous faites dans Notion | Ce qui apparaît sur le site |
|---|---|
| Nouvelle ligne dans la base | Nouvelle carte client |
| Vidéos, images, PDF déposés dans la page | Lecteurs vidéo, galerie, documents |
| Colonne **Références** (Social media, Publicité…) | Filtres « Expertise » |
| Colonnes **Supports** et **Marchés** | Fiche du client |
| Légende d’une vidéo ou d’un PDF | Titre affiché sous le média |
| Première vidéo de la page (ou celle choisie dans `config/site.json` → `covers`) | Miniature de la carte |
| Capture d’écran en tête de page | Ignorée (non publiée) |
| Plusieurs lignes « Client - Volet » (ex. « Carnac - Publicité », « Carnac - Newsletters ») ou portant le même nom | Une seule fiche, un chapitre par volet |

### Colonnes optionnelles (recommandées)

Le script les lit si elles existent dans la base, sinon il les ignore.
Les noms doivent être exactement ceux-ci :

- **Client** (texte) : regroupe plusieurs lignes sous un même client.
- **Secteur** (texte) : « Œnotourisme », « Hôtellerie de plein air »…
  Remplace la valeur saisie dans `config/site.json`.
- **Contexte** (texte) : 2 ou 3 phrases sur la demande du client.
- **Résultats** (texte) : chiffres et retombées. C’est ce qui convainc un prospect.
- **Publié** (case à cocher) : dès que cette colonne existe, seules les lignes
  cochées sont publiées. Pratique pour préparer une référence sans la montrer.

### Colonnes des landings du site (les-conteurs.com)

Ces colonnes alimentent `landings.json`, que l'extension WordPress
« Les Conteurs — Références » lit pour afficher les blocs « On a des preuves »
des landings (shortcode `[conteurs_references landing="production"]`).

- **Landing** (sélection multiple) : la ou les landings où la référence apparaît.
  Valeurs : `Production`, `Social media`, `Trafic`, `Branding`, `Conseil`,
  `Marketing automation`, `Rédaction`, `Home`. Elles deviennent
  `production`, `social-media`, `trafic`, `branding`, `conseil`,
  `marketing-automation`, `redaction`, `home` dans le shortcode.
- **Ordre** (nombre) : 1 = en premier. Sans ordre, la référence passe après.
- **Accroche** (texte) : une ligne sous le nom du client sur la carte.
- **Résultats** (texte) : le premier paragraphe s'affiche en gras sur la carte.
- **Couverture** (fichiers et médias) : l'image de la carte. Si plusieurs fichiers,
  la première est prise. Elle sert aussi de miniature sur ce portfolio.
  Sans couverture : miniature de la première vidéo.

Pensez aussi à **mettre une légende à chaque vidéo** dans Notion : sans elle,
le titre est tiré du nom du fichier (ou de `config/titles.json`).

## Mettre à jour tout de suite

Onglet **Actions** du dépôt → « Mettre à jour le portfolio » → **Run workflow**.
Comptez 2 à 5 minutes par nouvelle vidéo 4K.

### Depuis un bouton Notion (optionnel)

Si votre offre Notion propose l’action d’automatisation « Envoyer un webhook » avec en-têtes personnalisés, elle peut déclencher la mise à jour :

- URL : `https://api.github.com/repos/gregorycassiau-lgtm/references/dispatches`
- En-têtes : `Authorization: Bearer <jeton GitHub>`, `Accept: application/vnd.github+json`
- Corps : `{"event_type": "notion-update"}`

Le jeton GitHub doit être un *fine-grained token* limité à ce dépôt, avec la
permission « Contents : read and write ».

## Mise en place (une seule fois)

1. Créer le dépôt sur GitHub et y pousser ces fichiers.
2. Dans Netlify : *User settings → Applications → Personal access tokens*,
   créer un jeton.
3. Dans GitHub : *Settings → Secrets and variables → Actions*, ajouter :
   - `NETLIFY_AUTH_TOKEN` : le jeton Netlify ;
   - `NETLIFY_SITE_ID` : `1875323c-ca14-45c3-8496-5b834ac392ec`
     (projet `les-conteurs-references`).
4. Lancer le workflow une première fois à la main. Le cache est vide :
   ce premier passage compresse toutes les vidéos et prend environ une heure.
   Les suivants ne traitent que les nouveautés.

## Travailler en local

```bash
sudo apt install ffmpeg poppler-utils imagemagick   # macOS : brew install ffmpeg poppler imagemagick
pip install -r requirements.txt
python3 scripts/build.py          # construit dist/
python3 -m http.server -d dist    # aperçu sur http://localhost:8000
```

## Fichiers

```
scripts/build.py          Lecture Notion, médias, génération du site
src/template.html         Page (styles, mise en page, interactions)
src/logo-les-conteurs.svg Logo officiel
src/favicon.svg           Icône d’onglet
config/site.json          Accès Notion, secteurs, couvertures, liens, regroupements
config/titles.json        Titres des vidéos et PDF (par identifiant de bloc Notion)
netlify.toml              En-têtes de cache, pas de build côté Netlify
.github/workflows/update.yml  Mise à jour nocturne et à la demande
```

## Points d’attention

- **La base Notion doit rester publiée sur le web** : le script lit la version
  publique (`les-conteurs.notion.site`). C’est une interface que Notion ne
  documente pas ; si elle change, il faudra passer à l’API officielle avec une
  clé d’intégration.
- **Le site est public** pour qui a le lien. Il n’est pas indexé par les moteurs
  (`noindex`).
- **Bande passante** : le site est surtout de la vidéo. Surveiller la
  consommation dans Netlify si le lien circule beaucoup.
- **Droits** : vérifier que les vidéos UGC et les contenus publiés sur les
  comptes clients peuvent être montrés en démonstration commerciale.
