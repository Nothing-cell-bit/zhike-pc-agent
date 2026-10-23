# doocs/md typography adaptation

Source: [doocs/md](https://github.com/doocs/md), revision `f8d91268237bf34c026b91c04586f7daf5fc1f13`.

`default.css` is copied from `packages/shared/src/configs/theme-css/default.css`; upstream WTFPL is retained in `LICENSE`.

`backend/publication.py` applies the basic element rules from this stylesheet to sanitized WeChat publication HTML, resolves a fixed set of theme variables, and inlines the resulting styles. Custom rich-text styles take precedence. This reuses the typography stylesheet, not the complete upstream renderer/editor, diagram engines, or workspace packages. Content structure and prose are generated from the product and scenario.
