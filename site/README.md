# Fieldbrief
Official public incident feeds in a practical map and briefing interface. USGS, GDACS, NASA EONET and NWS are fetched directly by the visitor's browser; upstream failures are visible. Time coverage differs across publishers: recent earthquakes, active alerts and ongoing events are not a uniform14-day cohort.

A deterministic brief copies structured fields. Optional pretrained Gemma3 1B q4 via transformers.js runs on the visitor's device after explicit download (~860MB). No custom foundation-model training or paid inference. English/Japanese. Side trace shows actual prompts, raw output and limited checks. Model license/details: https://huggingface.co/onnx-community/gemma-3-1b-it-ONNX.

Checks establish citation-index validity, numeric occurrence and maximum alert level only. They do not establish semantic factuality, correct event linking, supported nonnumeric prose, safe instructions, headline/watch correctness or real-world truth. `node tests-brief.mjs` includes an explicit unsupported-prose counterexample that passes limited checks but stays `factualVerification: not_established`; six checks total. The UI now states these limits in its main result label, not just the footer. Noninteger references are rejected without an undefined-document crash.

Not an official warning service. Use linked official sources for decisions. Follow `npm ci && npm run dev`; `npm run build` checks types and builds the static site. Source attribution and public data URLs live in src/lib/feeds.ts.

Late replies are scoped to the selected incident document content and language. Selecting another incident while generation is in flight cannot display the old report under the new source list. A controlled deferred-model UI fixture verifies this independently of model quality.
