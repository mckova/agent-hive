export function tokenize(text) {
  return String(text)
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter(Boolean);
}

export function bm25Rank(query, documents, { k1 = 1.5, b = 0.75 } = {}) {
  const queryTerms = [...new Set(tokenize(query))];
  const tokenized = documents.map((document) => tokenize(document.text));
  const averageLength = tokenized.reduce((sum, tokens) => sum + tokens.length, 0) / Math.max(1, tokenized.length);
  const frequencies = new Map();

  for (const term of queryTerms) {
    frequencies.set(term, tokenized.filter((tokens) => tokens.includes(term)).length);
  }

  const scores = tokenized.map((tokens) => {
    const counts = new Map();
    for (const token of tokens) counts.set(token, (counts.get(token) || 0) + 1);
    return queryTerms.reduce((score, term) => {
      const count = counts.get(term) || 0;
      if (!count) return score;
      const documentFrequency = frequencies.get(term) || 0;
      const idf = Math.log(1 + (documents.length - documentFrequency + 0.5) / (documentFrequency + 0.5));
      const lengthPenalty = count + k1 * (1 - b + b * tokens.length / Math.max(1, averageLength));
      return score + idf * count * (k1 + 1) / lengthPenalty;
    }, 0);
  });

  return scores
    .map((score, index) => ({ score, index }))
    .sort((left, right) => right.score - left.score || left.index - right.index)
    .map((item) => item.index);
}

export function answerMetrics(prediction, expected) {
  const predictedTokens = normalizeAnswer(prediction).split(" ").filter(Boolean);
  const expectedTokens = normalizeAnswer(expected).split(" ").filter(Boolean);
  const exactMatch = predictedTokens.join(" ") === expectedTokens.join(" ") ? 1 : 0;
  const counts = new Map();
  for (const token of predictedTokens) counts.set(token, (counts.get(token) || 0) + 1);
  let overlap = 0;
  for (const token of expectedTokens) {
    const count = counts.get(token) || 0;
    if (count > 0) {
      overlap += 1;
      counts.set(token, count - 1);
    }
  }
  if (!predictedTokens.length || !expectedTokens.length) {
    return { exactMatch, tokenF1: exactMatch, exactLoss: 1 - exactMatch, taskLoss: 1 - exactMatch };
  }
  const precision = overlap / predictedTokens.length;
  const recall = overlap / expectedTokens.length;
  const tokenF1 = precision + recall ? 2 * precision * recall / (precision + recall) : 0;
  return { exactMatch, tokenF1, exactLoss: 1 - exactMatch, taskLoss: 1 - tokenF1 };
}

export function aggregateUsage(calls = []) {
  return calls.reduce((total, call) => {
    const usage = call.usage || {};
    total.inputTokens += usage.input_tokens || 0;
    total.outputTokens += usage.output_tokens || 0;
    total.reasoningTokens += usage.output_tokens_details?.reasoning_tokens || 0;
    total.totalTokens += usage.total_tokens || (usage.input_tokens || 0) + (usage.output_tokens || 0);
    total.modelLatencyMs += call.latencyMs || 0;
    return total;
  }, { inputTokens: 0, outputTokens: 0, reasoningTokens: 0, totalTokens: 0, modelLatencyMs: 0 });
}

export function enforceAnswerContract(question, answer) {
  const trimmed = String(answer || "").trim();
  if (!/^(are|is|was|were|do|does|did|can|could|will|would|has|have|had)\b/i.test(String(question).trim())) return trimmed;
  if (/^yes(?:\b|[.,;:])/i.test(trimmed)) return "yes";
  if (/^no(?:\b|[.,;:])/i.test(trimmed)) return "no";
  return trimmed;
}

export function aggregateMethods(examples) {
  const names = [...new Set(examples.flatMap((example) => Object.keys(example.systems || {})))];
  return Object.fromEntries(names.map((name) => {
    const rows = examples.map((example) => example.systems[name]).filter(Boolean);
    const usage = rows.reduce((total, row) => {
      for (const key of ["inputTokens", "outputTokens", "reasoningTokens", "totalTokens"]) {
        total[key] += row.usage?.[key] || 0;
      }
      return total;
    }, { inputTokens: 0, outputTokens: 0, reasoningTokens: 0, totalTokens: 0 });
    return [name, {
      examples: rows.length,
      calls: rows.reduce((sum, row) => sum + (row.calls?.length || 0), 0),
      exactMatch: mean(rows.map((row) => row.quality.exactMatch)),
      tokenF1: mean(rows.map((row) => row.quality.tokenF1)),
      exactLoss: mean(rows.map((row) => row.quality.exactLoss)),
      taskLoss: mean(rows.map((row) => row.quality.taskLoss)),
      averageEndToEndLatencyMs: mean(rows.map((row) => row.endToEndLatencyMs)),
      p50EndToEndLatencyMs: percentile(rows.map((row) => row.endToEndLatencyMs), 0.5),
      usage,
      averageTokensPerExample: rows.length ? usage.totalTokens / rows.length : 0
    }];
  }));
}

function normalizeAnswer(text) {
  return String(text)
    .toLowerCase()
    .replace(/\b(a|an|the)\b/g, " ")
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function mean(values) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

function percentile(values, fraction) {
  if (!values.length) return 0;
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.floor((sorted.length - 1) * fraction)];
}
