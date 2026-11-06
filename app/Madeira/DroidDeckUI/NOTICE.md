# Attribution and source references

This UI port adapts presentation code, geometry, animation parameters, the
wordmark, translations, and emulator icons from **DroidDeck 0.6.9**:

https://github.com/Droid-Deck/DroidDeck/tree/0a07926ef3477c90db911d169904137cfc5e2505

DroidDeck contributors retain copyright in the upstream work. The adapted
presentation code and upstream resources are distributed under GPL-3.0;
see `LICENSE-DroidDeck.txt`. The HTML/CSS/JavaScript renderer and the iOS wrapper
are modifications made for this mdeck branch. Android backend code is not
included in the application target.

The complete reference UI source list and hashes are recorded in
`docs/droiddeck-source-manifest.json`. The importer is
`tools/droiddeck/import-ui.py`.

Resource origins:

- `logo.png`, `emu_*.png`: DroidDeck's `app/src/main/res/drawable-nodpi/`.
- `droiddeck-startup.webm`: DroidDeck's `app/src/main/assets/steam-startup/`.
- `Roboto.ttf`: Google Fonts, `ofl/roboto/Roboto[wdth,wght].ttf`;
  SIL Open Font License, see `assets/LICENSE-Roboto.txt`.
- `MaterialSymbolsOutlined.ttf`: Google Material Design Icons repository,
  `variablefont/MaterialSymbolsOutlined[FILL,GRAD,opsz,wght].ttf`;
  Apache 2.0, see `assets/LICENSE-MaterialSymbols.txt`.
- `game-<appid>.jpg`, `library_hero-<appid>.jpg`, and `logo-<appid>.png`:
  Valve Steam CDN display artwork at
  `https://cdn.akamai.steamstatic.com/steam/apps/<appid>/`.
  Copyright remains with each game's rights holder. These are bundled visual
  fixtures, not GPL-licensed game content, executable games, or entitlement
  to use those games. The application performs no artwork requests at runtime.

Steam, DroidDeck, emulator names, and game names are owned by their respective
rights holders. This fork is not an official release of those products.
