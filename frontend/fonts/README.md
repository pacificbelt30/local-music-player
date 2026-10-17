# UI font

Noto Sans JP is bundled locally; browsers do not contact a font CDN.
The upstream SIL Open Font License and copyright notice are in `OFL.txt`.

Source: https://github.com/google/fonts/tree/main/ofl/notosansjp

The variable-font subset contains Latin, kana, full-width forms, JIS X 0208 level-one kanji,
and characters present in the HTML/JavaScript UI. Other characters use the system Japanese font fallback.
The weight axis is restricted to 400–700. CSS uses the family alias `SyncTune Sans`.

Upstream TTF SHA-256: `c2f3b4d463500a2ddcd3849cded1fceeb9fd6d1c32e6cbecd568453ba50fc68f`

To rebuild, install `fonttools` and `brotli` in a development environment, then run:

```bash
python scripts/build_ui_font.py '/path/to/NotoSansJP[wght].ttf'
```

Keep the upstream license with the generated font. No font build tools are required at runtime.
