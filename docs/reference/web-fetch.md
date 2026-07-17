# Web fetch — ARIA reads a pasted URL

ARIA can read a single web page the user pastes and ground its answer in it,
using Anthropic's native `web_fetch` server-tool. The fetch runs on
**Anthropic's infrastructure, not ours**, so there is no server-side
request-forgery (SSRF) surface on ARIA's own network.

## Ships OFF by default

The tool is attached to a cognition call **only when all three hold**:

1. `WEB_FETCH_ENABLED=true`, **and**
2. `WEB_FETCH_ALLOWED_DOMAINS` is a non-empty (comma-separated) allow-list, **and**
3. the user's message contains an `http(s)` URL.

With the defaults (`WEB_FETCH_ENABLED=false`, empty allow-list) ARIA behaves
exactly as before — the cognition call is byte-for-byte unchanged.

## Settings

| Env var | Default | Meaning |
|---------|---------|---------|
| `WEB_FETCH_ENABLED` | `false` | Master switch. |
| `WEB_FETCH_ALLOWED_DOMAINS` | *(empty)* | Comma-separated, deny-by-default allow-list. Empty ⇒ the tool is never attached. |
| `WEB_FETCH_MAX_USES` | `2` | Max fetches per cognition call. |
| `WEB_FETCH_MAX_CONTENT_TOKENS` | `10000` | Truncates fetched page text to bound token spend. |

## Before you enable it — preconditions

1. **Envelope parsing is hardened.** A fetched page can influence the model's
   output, so the cognition response parser must degrade gracefully on a
   malformed envelope instead of erroring. (Done — the `_parse_response`
   guard catches `ValueError`/`TypeError` as well as JSON/key errors.)
2. **Choose the allow-list carefully.** The allow-list is the *only* control
   preventing a hostile page from steering ARIA to encode owner memory (PII)
   into an outbound URL. **Never allow-list a domain that:**
   - echoes or logs query-string parameters to a third party,
   - has an open redirect, or
   - hosts arbitrary user-generated content (wikis, paste sites, comment threads).

   Keep the allow-list narrow and trusted.

## Built-in guardrails

- Anthropic blocks private/loopback IPs and robots-disallowed URLs on their side.
- ARIA **suppresses any memory fact-write** (`world_model_update`) on a turn
  where a fetch ran, so a page cannot poison ARIA's memory.
- The `pause_turn` continuation loop is hard-bounded.
- Fetch errors degrade to a normal answer (no crash, no assumed success).
