# Poster Maker reuse

- Repository: https://github.com/dabodamjan/poster-maker
- Revision: fa6b21e1e8528fb7eafaeacc40124871f9d2661e
- License: MIT, preserved verbatim in `LICENSE`.
- Original reference files: `releaserocket-instagram-post.html`, `export.js`.
- Adaptations: `backend/poster_templates/product.html` reuses the dot field,
  ember glow, typography hierarchy and chip treatment. It replaces the upstream
  brand/copy/assets with approved Chinese product content and original product
  images, adds a light theme and three aspect ratios, and uses local system fonts.
- `backend/poster_renderer.py` adapts the browser export sequence to Python
  Playwright, blocks network requests, fits long text, and records layout bounds.
- No upstream production API credentials, external font requests, SaaS accounts,
  product names, prices or endorsements are imported.
