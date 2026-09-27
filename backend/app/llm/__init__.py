"""LLM layer (D-022). It writes plain-English explanations of decisions from their trace,
and nothing else: it never sets a decision, an amount or a citation (CLAUDE.md rule 2).
Off by default (LLM_ENABLED=false); then every decision gets the standard template."""
