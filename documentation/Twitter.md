# X (Twitter) API Documentation

Reference for the **X API v2** read surface as modelled by the packaged provider
spec (`src/sportsdata_mcp/specs/twitter.yaml`). One host: `api.x.com`
(docs: https://docs.x.com/x-api/introduction).

> **A key is required** — X has no anonymous tier. Spec written 2026-06-12 from
> the official docs; shapes follow X's standard v2 envelope
> (`{data, includes, meta}`).

## Auth — bring your own Bearer token

Every request sends `Authorization: Bearer <token>` (app-only auth). The token
resolves in this order:

1. **`X_BEARER_TOKEN` env var** — set it where the server runs. An operator can
   ship a deployment-wide token here (everyone using that deployment rides it,
   and their usage counts against that project's quota).
2. **`secrets: { X_BEARER_TOKEN: "..." }`** in the config file — local-dev
   convenience.

The env var holds the **bare token**; the spec's `value_prefix` adds `Bearer `.
Get a token from a project/app at https://developer.x.com (the *app-only Bearer
Token*, not the consumer keys). It is never stored in the repo and never appears
in tool output.

**Mind your tier.** X rate-limits per endpoint per 15-minute window and caps
monthly post reads by tier (Free is ~100 reads/month — effectively demo-only;
Basic and up are usable). The spec throttles to ~0.5 req/s and never auto-retries
a 429 (the window is 15 minutes — retrying burns quota). Check your cap with
`twitter_usage` before a heavy pull.

## Field params

X's `tweet.fields` / `user.fields` aren't valid tool-parameter names, so the
tools take `tweet_fields` / `user_fields` / `expansions` and map them to the
wire names. Rich defaults are baked in (`created_at`, `public_metrics`,
`author_id` + expanded authors) — override only when you need more.

## Posts — group `twitter.tweets`

| Tool | Path | Capability |
|---|---|---|
| `twitter_search_recent` | `/2/tweets/search/recent?query=` | `social.post_search` |
| `twitter_tweet_counts` | `/2/tweets/counts/recent?query=&granularity=` | `social.post_search` |
| `twitter_tweets` | `/2/tweets?ids=` | `social.post_detail` |
| `twitter_tweet` | `/2/tweets/{id}` | `social.post_detail` |
| `twitter_quote_tweets` | `/2/tweets/{id}/quote_tweets` | `social.post_detail` |
| `twitter_retweeted_by` | `/2/tweets/{id}/retweeted_by` | — |
| `twitter_liking_users` | `/2/tweets/{id}/liking_users` | — |

Query operators: `from:wojespn`, `"Storm v Cowboys"`, `#NBAFinals lang:en
-is:retweet`. `twitter_tweet_counts` gauges buzz without spending post reads.

## Users — group `twitter.users`

| Tool | Path | Capability |
|---|---|---|
| `twitter_user_by_username` | `/2/users/by/username/{username}` | `social.user_profile` |
| `twitter_users_by_usernames` | `/2/users/by?usernames=` | `social.user_profile` |
| `twitter_user` | `/2/users/{id}` | `social.user_profile` |
| `twitter_users` | `/2/users?ids=` | `social.user_profile` |
| `twitter_user_tweets` | `/2/users/{id}/tweets` | `social.user_timeline` |
| `twitter_user_mentions` | `/2/users/{id}/mentions` | `social.user_timeline` |

Flow: `twitter_user_by_username("AFL")` → numeric `id` → `twitter_user_tweets(id)`.

## Trends & usage — group `twitter.trends`

| Tool | Path | Capability |
|---|---|---|
| `twitter_trends` | `/2/trends/by/woeid/{woeid}` (1 = worldwide, 23424977 = US, 23424748 = AU, 23424975 = UK) | `social.trends` |
| `twitter_usage` | `/2/usage/tweets` | — (monthly cap monitoring) |

## Not modelled

- **Anything that writes or needs user context** — posting/deleting, likes,
  reposts, follows/blocks/mutes management, bookmarks, DMs, the home timeline
  (OAuth 2.0 user-context surfaces).
- **Streaming** (`/2/tweets/search/stream`) — long-lived connections don't fit
  the request/response tool model.
- **Full-archive search** (`/2/tweets/search/all`), **users search**
  (`/2/users/search`) and followers/following lookups — Pro+/tier-gated; add
  later if a consumer's tier carries them.
- Spaces, Lists, Communities, Media upload — not sports-data surfaces.

## Sports use & cross-provider comparison

The `social.*` tags are single-provider for now, but compose with the rest of
the catalogue by entity: resolve a fixture from a league feed (NRL/AFL/MLB/...),
then `twitter_search_recent("\"Storm\" \"Cowboys\" lang:en -is:retweet")` for
sentiment/news, or `twitter_user_tweets` on club/insider accounts next to
bookmaker odds movements (`sport.prices`) around team-news drops.
