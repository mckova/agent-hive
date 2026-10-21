# Token counting

Do not assume that English, terse grammar, or any particular script is always cheapest. The result depends on the model tokenizer and on the complete request.

Use the bundled `compare` command to evaluate variants with literal-preservation checks:

- `--counter heuristic` uses `utf8-bytes/4`. It is offline and suitable only for rough planning.
- `--counter openai --model <id>` uses optional Python `tiktoken` and reports `exact-text`. Message framing, tools, images, output, and cached context are outside that count.
- `--counter anthropic --model <id>` calls Anthropic's token-count endpoint with `ANTHROPIC_API_KEY` and reports `provider-estimate` for a one-message request.
- `--counter auto --model <id>` may fall back. Read the returned precision and note; never hide fallback.

Choose the lowest count only among variants with `preserved: true`. Do not translate literals, filenames, identifiers, commands, quotations, or success criteria. Optimize total expected completion cost, including misunderstandings and retries—not input tokens alone.

Prompt counts are separate from actual usage. Token-budget accounting requires complete provider input and output totals; cached input remains included, and reasoning is a diagnostic subset of output. Missing or incomplete usage after any invocation blocks dispatch until its inspected outcome and confirmed cumulative usage are explicitly reconciled. Never price unknown usage as zero or describe a between-call budget gate as a hard provider spend cap.
