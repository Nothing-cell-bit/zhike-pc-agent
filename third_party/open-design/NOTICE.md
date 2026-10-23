# OpenDesign integration

Repository: https://github.com/EthanGuo2022/OpenDesign

Pinned revision: `7dee599ca39a7c164351e7d637c2b5a24ca23842`.

The original MIT license is preserved in `LICENSE`. Original-file checksums are
recorded in `upstream-sha256.json`.

Actually executed upstream components, under `backend/_vendor/open_design/`:

- `planner.PlannerLoop`: bounded tool-use planning loop and trace records.
- `tools.propose_design_spec`: original Pydantic design specification validation.
- `schema.DesignSpec`, `LayerNode`, `CritiqueReport`, and related data contracts.
- `agents.critic_agent.CriticAgent`: original vision tool loop, image reading,
  source lookup, structured verdict validation, and fail-safe behavior.
- Provider protocol/data classes and small filesystem/logging utilities.

Host adaptations:

1. `llm_backend.make_backend` accepts an injected backend factory so credentials
   and network validation remain owned by the existing application.
2. `config.py` no longer loads or overrides an upstream `.env` file.
3. The planner tool registry exposes only the actual design-proposal handler,
   finishing after a valid proposal. Arbitrary file/code tools are not exposed.
4. The poster critic additionally indexes `product_reference`, allowing direct
   comparison with the original product instead of only the generated poster.
5. `backend/opendesign_engine.py` adapts the model API, compresses visual inputs,
   compiles the validated specification into a complete-image generation prompt,
   and requires both real images to have been delivered before accepting review.
6. `backend/poster_workflow.py` persists plans, task IDs, candidates, and reviews;
   at most one additional image is generated for a requested visual repair.

The upstream academic-poster prompts are included as provenance references. The
live commercial-product task uses explicit product-focused instructions and the
upstream planner/critic code. It does not invoke a fixed HTML poster template.

No model weights, upstream API credentials, fonts, or unrelated presentation,
video, PSD, or HTML rendering components are bundled.
