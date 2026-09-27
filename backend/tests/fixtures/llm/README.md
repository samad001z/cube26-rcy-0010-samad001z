# LLM response fixtures

Responses in the shape google-genai returns from `models.generate_content` on Vertex AI
(`GenerateContentResponse`, dumped as JSON). Tests replay them through a fake client, so no
test reaches the network.

The files here were **written by hand** in that shape: this build environment has no Vertex
access. Replace or add real ones with `make llm-smoke RECORD=tests/fixtures/llm/<name>.json`,
which saves the response of one real call (text, token counts, model version; no
credentials are in a response). `_about` says where each file came from.
