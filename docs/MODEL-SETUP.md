# Optional model assistance

The complete deterministic workflow needs no model or API key. AI assistance is an opt-in proposal step after a review. It cannot change the metric contract. Every proposed SQL revision is checked and executed through the same restrictions as user SQL.

## Local Ollama

Run [Ollama](https://ollama.com/) separately with a model already installed. The default model is `qwen3.5:9b`; change `QUERYPROOF_MODEL` to another installed model. QueryProof never downloads models automatically. `QUERYPROOF_OLLAMA_URL` defaults to `http://127.0.0.1:11434` and only accepts a loopback HTTP origin.

```sh
uv run queryproof
```

## Use your own API key

The optional hosted adapter implements the [OpenAI Chat Completions protocol](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create). It requires an HTTPS API base, a model supporting JSON-object responses and `max_completion_tokens`, and your own provider key. Some compatible providers/models do not support these parameters; those requests fail visibly without changing deterministic results. Native Anthropic/Gemini APIs are not supported by this adapter.

Copy `.env.example` to `.env`, then select the hosted provider and fill in the model/key on your own computer:

```dotenv
QUERYPROOF_PROVIDER=openai-compatible
QUERYPROOF_API_BASE=https://api.openai.com/v1
QUERYPROOF_MODEL=your-model-id
QUERYPROOF_API_KEY=your-own-key
```

Load that file explicitly when starting the server:

```sh
uv run --env-file .env queryproof
```

Alternatively set those variables in the process environment. `.env` is ignored by Git. The browser never receives or stores the key. The server sends it only in the provider Authorization header; redirects are refused so credentials are not forwarded to another endpoint. The [OpenAI authentication guidance](https://developers.openai.com/api/reference/overview) likewise requires keeping keys on the server.

The interface shows the configured provider, model, endpoint hostname and whether the service is local. It requires explicit consent before sending the SQL, metric contract, schema, row counts and bounded diagnostic evidence. Diagnostic SQL and group evidence can contain data values. Imported CSV files and full raw tables are not sent. Consider the configured provider's data handling policy before consenting.

Each assistance run has a maximum of eight diagnostic calls, 60 seconds and 2,048 generated tokens. Token usage is shown when the provider reports it; if absent, the requested allowance is reserved so it cannot bypass the cap. These are run limits, **not a dollar-spending guarantee**. Set your own account spending limits before using hosted inference. No hosted calls or purchases were made while implementing this adapter; its protocol and error boundaries were tested through a local HTTP test service with a dummy credential.

The hosted adapter uses the model's default sampling settings for compatibility. The documented temperature-zero, fixed-context evaluation configuration applies to local Ollama runs. Hosted results require their own recorded evaluation; no local accuracy result transfers automatically to another model or provider.

Full or smoke hosted evaluations additionally require `--allow-hosted` to avoid accidentally starting billed batches. A full comparison schedules 144 assistance runs. The ordinary browser assistance action remains one explicitly requested run.

```sh
uv run --env-file .env python scripts/evaluate.py --smoke --allow-hosted
```

Provider errors show a safe status without echoing raw response bodies or credentials. Expired keys, unsupported model parameters and malformed/truncated output remain failed assistance; the completed deterministic report remains available.
