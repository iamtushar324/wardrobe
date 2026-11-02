# Wardrobe

A calm, photo-first home for your clothes. Drop a folder of photos — flat-lays, mirror selfies, tag and
receipt shots — and Wardrobe groups them into items, reads tags, removes backgrounds and fills in the
details. Browse by season, colour and occasion, flip between **the clothes** and **you wearing them**, and
let a queue-based **Studio** make the missing pictures with your own ChatGPT subscription.

Built for one person or a household, self-hosted, with a first-class API and MCP server so agents can
manage the wardrobe too.

## What it does

- **Closet** — a grid of every item with filters for season, colour, occasion, category, brand, status and
  more. A single toggle switches every card between the clean product picture and a photo of you wearing it.
- **Bulk import** — drop a whole folder (or many). Photos are analysed with a vision model, grouped into
  items, matched against what you already own, and turned into proposals you review, edit, merge and
  commit. Optional hints (store, purchase date, price, original price, brand, gift from, occasions) are only
  applied when you give them.
- **Items** — every photo of an item in one place (product, on me, AI, tags), automatic cut-outs, purchase
  details, wear log, favourites, and inline editing.
- **Studio** — AI pictures from templates:
  `Product · white`, `Product · ghost mannequin`, `Product · flat lay`, `Product · on hanger`,
  `Detail close-up`, `Outfit board`, `Me · lifestyle`, `Me · studio white`, `Me · at the occasion`,
  `Me · mirror selfie`, `Me · editorial`, `Me · full outfit`, plus your own templates.
  - A real **queue**: pause and resume everything, cancel or retry jobs, move a job to the top.
  - **Auto mode**: pick which templates should be made automatically for every new item, and backfill
    the rest of the closet in one click.
  - **Usage**: daily caps and spacing per engine, today's count, last 7 days, cost, and the ChatGPT plan
    limits reported by the worker, so you can stop before a limit is hit.
  - **Model photos**: choose up to six real photos of yourself that "Me" templates use as the person.
- **Sign in** with Google (via Clerk), with ChatGPT (device code), or with a single owner password.
- **Sharing** — invite people with view or edit access.
- **Agents** — REST API, an MCP server at `/mcp`, personal access tokens (read-only or full), an audit log
  and an agent skill.

## How it fits together

```
browser ──► web (FastAPI + React, :8080) ──► SQLite + media on one volume
                    ▲         ▲
     MCP / REST ────┘         └──── worker (same image): photo analysis, grouping, cut-outs,
                                    OpenRouter pictures
ChatGPT image worker (any machine with the Codex CLI) ── HTTPS + worker token ──► web
```

- `server/` — FastAPI app (`wardrobe.main`) and the background worker (`wardrobe.worker`). SQLite in WAL
  mode; web and worker share the data volume, so run exactly one replica.
- `web/` — React 19 + Vite + Tailwind single-page app, served by the API in production.
- `worker/` — the ChatGPT image worker. It runs `codex login --device-auth` to connect a person's own
  ChatGPT account, keeps one Codex home per wardrobe user, and runs `codex exec` with the built-in image
  tool to make Studio pictures. Standard library only.
- `skills/wardrobe/` — an agent skill (instructions, API reference and a folder-import script).

## Quick start

```bash
mkdir -p credentials && openssl rand -base64 24 > credentials/owner-password
WARDROBE_OWNER_EMAIL=you@example.com docker compose up -d --build
open http://localhost:8080          # sign in with the password above
```

Photo analysis and OpenRouter pictures need `OPENROUTER_API_KEY`. Without it, imports still work as
plain uploads and you fill the details yourself.

### Development

```bash
cd server && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
WARDROBE_AUTH=none WARDROBE_INLINE_WORKER=on .venv/bin/uvicorn wardrobe.main:app --reload --port 8080
cd web && npm ci && npm run dev     # http://localhost:5173, proxies /api to :8080
cd server && .venv/bin/pytest
```

## Configuration

All settings are environment variables with the `WARDROBE_` prefix. Secrets may instead be files in
`WARDROBE_CREDENTIALS_DIR` (one file per secret, Kubernetes-Secret style); an environment variable wins.

| Variable | Default | Meaning |
|---|---|---|
| `PUBLIC_URL` | `http://localhost:8080` | External URL (cookies are `Secure` on https) |
| `AUTH` | `none` | Comma list of `clerk`, `chatgpt`, `password`, `none` (dev: everyone is the owner) |
| `OWNER_EMAIL` / `OWNER_NAME` | | The wardrobe owner |
| `DATA_DIR` | `./data` | SQLite database, media and models |
| `ANALYSIS` / `CUTOUTS` | `on` | Vision analysis and background removal |
| `VISION_MODEL` | `google/gemini-3.8-flash` | OpenRouter model for photo analysis |
| `IMAGE_MODEL` | `google/gemini-3.1-flash-image` | OpenRouter model for Studio pictures |
| `DAILY_VISION_CAP` | `400` | Photo analyses per day |
| `MAX_UPLOAD_MB` | `40` | Per-file upload limit |
| `BLOCKED_CHATGPT_DOMAINS` | | Email domains that may never be connected for pictures (e.g. your employer) |
| `INLINE_WORKER` | `off` | Run the background worker inside the web process (development) |

Secrets: `session-key`, `worker-token`, `openrouter-api-key`, `clerk-secret-key`,
`clerk-publishable-key`, `owner-password`.

## ChatGPT pictures and sign-in

1. Run the worker on a machine with the [Codex CLI](https://github.com/openai/codex) installed, as an
   ordinary user (see `worker/wardrobe-codex-worker.service`). Give it the app URL and the same
   `worker-token` secret.
2. In **Studio → ChatGPT**, choose *Connect*. The page shows a link and a one-time code; finish the
   sign-in on OpenAI's site. The worker keeps that login for your wardrobe account only.
3. With `chatgpt` in `WARDROBE_AUTH`, the same flow also works as a sign-in method.

Pictures count against the connected ChatGPT plan. Only connect your own account, and only enter a device
code that you started yourself.

## Agents

Create a token in **Settings → Agents**. The page shows ready-to-paste snippets, for example:

```bash
claude mcp add --transport http wardrobe https://wardrobe.example.com/mcp \
  --header "Authorization: Bearer <token>"
```

MCP tools include `wardrobe_search`, `wardrobe_get_item`, `wardrobe_create_import`,
`wardrobe_import_status`, `wardrobe_commit_import`, `wardrobe_add_item`, `wardrobe_update_item`,
`wardrobe_link_photo`, `wardrobe_mark_worn`, `wardrobe_templates`, `wardrobe_generate` and
`wardrobe_generation_queue`. The skill in `skills/wardrobe` teaches an agent how to use them and ships a
`wardrobe-ingest` script for importing a local folder:

```bash
WARDROBE_URL=https://wardrobe.example.com WARDROBE_TOKEN=... \
  skills/wardrobe/scripts/wardrobe-ingest ~/Pictures/new-shirts --store "Uniqlo" --wait
```

Admin CLI inside the container: `python -m wardrobe.cli token create --label laptop`,
`python -m wardrobe.cli user invite friend@example.com`.

## Deploy

`docker-compose.yml` for a single machine, `deploy/kubernetes/wardrobe.yaml` for a cluster. Back up the
data directory (SQLite with `sqlite3 wardrobe.sqlite ".backup ..."`, plus `media/`).

## License

MIT. See [NOTICE.md](NOTICE.md) for credits.
