# Pterodactyl-Discord

A Discord bot that lets members of a single trusted role list [Pterodactyl](https://pterodactyl.io/) panel
server instances and control their power state (start, restart, stop, kill) from Discord — without giving
anyone panel access.

## What it does

- **`/servers`** — lists every server on the panel (name, identifier, node) as a paginated embed.
- **`/server start`** / **`/server restart`** / **`/server stop`** / **`/server kill`** — sends a power
  action to one server, picked via autocomplete.

## Permission model

Every command is gated behind a **single** Discord role, configured via `ALLOWED_ROLE_ID`. There is no
tiered access (e.g. "kill" isn't restricted to a smaller group than "start") — anyone with that one role
can run every command. If you need finer-grained access control, put people who shouldn't have `kill`
access in a different role and don't give them the allowed role at all.

A member without the allowed role gets a generic ephemeral "you don't have permission" message — it never
reveals server names, node info, or anything else about the panel.

> [!CAUTION]
> **`/server kill` force-terminates the server process.** It's the equivalent of pulling the power cord —
> not a graceful shutdown — and can corrupt in-progress writes (world saves, databases, etc.). Use `stop`
> first; only reach for `kill` when a server is unresponsive to `stop`.
>
> To prevent an accidental tap from killing a server, `kill` shows an ephemeral confirmation prompt with
> **Force Kill** / **Cancel** buttons and does nothing until you explicitly press **Force Kill**. The
> prompt expires after 30 seconds with no action taken (treated as cancelled) if you don't respond.

## Pterodactyl-side prerequisites

The bot talks to two different Pterodactyl APIs, and each needs its own credential.

### 1. Client API key — a dedicated bot user with subuser access

The **Client API** key is what actually reads power state and sends power actions
(`/api/client/servers/{id}/resources` and `/power`). Client API keys are scoped to whatever servers the
owning account can see, so:

1. In the panel, create a **new, non-admin user** dedicated to the bot (e.g. `discord-bot`). Don't reuse
   your own admin account — if that account's key ever leaks, you don't want it carrying admin rights.
2. For **every server the bot should be able to manage**, go to that server → **Users** → add the bot user
   as a **subuser**, and grant at least the **Control → Send Power Actions** permission. Without this
   permission the bot will authenticate fine but get a `403 Forbidden` the moment it tries to send a power
   action against that server.
3. Log in as the bot user → **Account Settings → API Credentials → Create API Key** → give it a
   description (e.g. `discord-bot`) → save. Copy the key immediately, it's only shown once. This is your
   `PTERODACTYL_CLIENT_API_KEY`.

Repeat step 2 for any server added later — the bot only sees/controls servers where its user is explicitly
added as a subuser (or owner).

### 2. Application API key — an admin account

The **Application API** key is what lists all servers for `/servers` and the `/server` autocomplete
(`/api/application/servers`). This is an admin-scoped credential:

1. Log in as a user with the **Administrator** flag.
2. Go to **Admin (gear icon) → Application API**.
3. **Create New** → give it a description (e.g. `discord-bot`) → **Create**.
4. Copy the key immediately, it's only shown once. This is your `PTERODACTYL_APP_API_KEY`.

Application API keys carry full admin-level API access, so treat this key the same as an admin password —
store it as a secret, don't commit it, and don't log it (the bot itself never logs it either — see
[Logging](#logging) below).

## Environment variables

All configuration comes from environment variables — there's no config file baked into the image or repo.
Copy [`.env.example`](.env.example) to `.env` for local runs.

| Variable                     | Description                                                                 | Example                          |
| ----------------------------- | ---------------------------------------------------------------------------- | --------------------------------- |
| `DISCORD_TOKEN`               | Bot token from the Discord Developer Portal's **Bot** tab.                   | *(copy from the Bot tab — treat as a secret)* |
| `DISCORD_GUILD_ID`            | ID of the Discord server (guild) the bot operates in. Slash commands sync to this guild only. | `987654321098765432`             |
| `ALLOWED_ROLE_ID`             | ID of the single Discord role permitted to use any bot command.             | `123456789012345678`             |
| `PTERODACTYL_URL`             | Base URL of the panel, no trailing slash.                                   | `https://panel.example.com`      |
| `PTERODACTYL_APP_API_KEY`     | Application API key from an admin account (see above).                      | *(copy from Admin → Application API — treat as a secret)* |
| `PTERODACTYL_CLIENT_API_KEY`  | Client API key from the dedicated bot subuser account (see above).          | *(copy from Account Settings → API Credentials — treat as a secret)* |
| `PTERODACTYL_SKIP_SSL_VERIFY` | Disables TLS certificate verification for the panel connection. **Insecure** — see [Troubleshooting](#the-bot-cant-verify-the-panels-tls-certificate-certificate_verify_failed). Optional, defaults to `false`. | `false` |
| `LOG_LEVEL`                   | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. Optional, defaults to `INFO`. | `INFO` |

To get an ID, enable **Settings → Advanced → Developer Mode** in Discord, then right-click the server or
role and choose **Copy ID**.

## Running with Docker

### `docker run`

```bash
docker run -d \
  --name pterodactyl-discord-bot \
  --restart unless-stopped \
  -e DISCORD_TOKEN=your-bot-token \
  -e DISCORD_GUILD_ID=your-guild-id \
  -e ALLOWED_ROLE_ID=your-role-id \
  -e PTERODACTYL_URL=https://panel.example.com \
  -e PTERODACTYL_APP_API_KEY=your-application-api-key \
  -e PTERODACTYL_CLIENT_API_KEY=your-client-api-key \
  -e LOG_LEVEL=INFO \
  ghcr.io/notamorningspartan/pterodactyl-discord:latest
```

(Or build locally with `docker build -t pterodactyl-discord-bot .` and swap the image name above.)

### `docker-compose.yml`

```yaml
services:
  bot:
    image: ghcr.io/notamorningspartan/pterodactyl-discord:latest
    restart: unless-stopped
    env_file:
      - .env
```

With a `.env` file (based on [`.env.example`](.env.example)) sitting next to `docker-compose.yml`, then:

```bash
docker compose up -d
```

The container runs as a non-root user and never has your `.env` baked into the image — it's only read at
runtime via `env_file`/`-e`.

## Discord bot setup

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) → **New Application**.
2. Under **Bot**, click **Reset Token** to generate a token — this is your `DISCORD_TOKEN`. Keep it secret.
3. Still under **Bot**, leave **Privileged Gateway Intents** all disabled. The bot doesn't request
   Message Content, Server Members, or Presence intents — it reads the invoking member's roles directly
   off each slash command interaction, which Discord includes without any privileged intent.
4. Under **OAuth2 → URL Generator**:
   - **Scopes**: check `bot` and `applications.commands`.
   - **Bot Permissions**: none are required — leave the permission integer at `0`. All of the bot's
     responses are ephemeral slash-command replies, which don't need channel-level permissions like
     Send Messages or Embed Links. Access control is entirely the `ALLOWED_ROLE_ID` check, not Discord
     permissions.
5. Open the generated URL, pick your server, and authorize it.
6. Start the bot with `DISCORD_GUILD_ID` set to that server's ID. On startup it syncs its slash commands
   directly to that guild (see [Troubleshooting](#troubleshooting) if commands don't show up right away).

## Logging

The bot logs startup, command invocations, and Pterodactyl API errors through Python's `logging` module,
formatted as `<timestamp> <level> <logger>: <message>`. `LOG_LEVEL` controls verbosity for the bot's own
logs. The `httpx`/`httpcore` loggers (used by the Pterodactyl client) are always capped at `WARNING`
regardless of `LOG_LEVEL`, because at `DEBUG` those libraries log full request/response headers — including
the `Authorization: Bearer <api-key>` header. The Discord bot token and both Pterodactyl API keys are never
written to a log line at any level.

## Troubleshooting

### Bot crashes on startup with `discord.errors.Forbidden: 403 Forbidden (error code: 50001): Missing Access`

This happens during the guild command sync in `setup_hook`, and almost always means one of:

- The bot was invited with only the `bot` OAuth2 scope, missing `applications.commands`. Regenerate the
  invite URL under **OAuth2 → URL Generator** with both scopes checked (see
  [Discord bot setup](#discord-bot-setup)), open it, and re-authorize — you don't need to remove the bot
  from the server first, re-authorizing adds the missing scope to its existing membership.
- `DISCORD_GUILD_ID` doesn't match a guild the bot has actually joined. Double-check the ID (right-click
  the server with Developer Mode enabled → **Copy Server ID**) against the one in your environment.

The bot's own log output includes a line identifying which of these it's likely to be before the traceback.

### Pterodactyl API returns 403 when sending a power action

The bot's client account authenticated successfully but isn't allowed to control that specific server. Go
to the server in the panel → **Users**, and confirm the bot's dedicated user is listed as a subuser with
**Control → Send Power Actions** checked. This is set per-server — adding the bot as a subuser on one
server doesn't grant it access to any others. See [Pterodactyl-side prerequisites](#pterodactyl-side-prerequisites)
above.

### The bot can't verify the panel's TLS certificate (`CERTIFICATE_VERIFY_FAILED`)

If the bot crashes with something like:

```
httpx.ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate
```

it couldn't build a trusted certificate chain when connecting to `PTERODACTYL_URL`. This is almost always
one of:

- **The panel's web server isn't serving its full certificate chain** (a common Let's Encrypt + nginx/Caddy
  misconfiguration — the leaf cert is sent without the intermediate). Browsers often paper over this via
  AIA fetching; most non-browser HTTP clients, including this bot's, don't. Run
  `curl -vI https://your-panel-url` from another machine — if curl fails the same way, this is almost
  certainly it, and the real fix is on the panel's reverse-proxy config (point `ssl_certificate` at
  `fullchain.pem`, not just the leaf cert), not the bot.
- **The panel uses a self-signed certificate or an internal/private CA** (common for homelab or
  internal-network-only panels). The correct long-term fix is a real certificate in front of the panel
  (e.g. Caddy or nginx + Let's Encrypt, including via a DNS-01 challenge for internal-only hostnames).

If you can't fix the certificate right now and are on a trusted network, set `PTERODACTYL_SKIP_SSL_VERIFY=true`
to disable certificate verification for the panel connection. This is insecure — it means anyone who can
observe that traffic could intercept both Pterodactyl API keys, which are sent in the `Authorization`
header on every request — so treat it as a stopgap, not a permanent setting, and never use it over an
untrusted network. The bot logs a warning on startup whenever this is enabled as a reminder it's active.

### Discord says a slash command doesn't exist ("This command is outdated" / doesn't appear at all)

The bot syncs commands to `DISCORD_GUILD_ID` on every startup (guild-scoped sync, not global), which is
fast but not always instant, and Discord clients cache the command list locally. If a command is missing or
looks stale right after (re)deploying:

- Wait a few seconds and try again — guild syncs are near-instant server-side but the Discord client can
  take a moment to pick up the change.
- Fully restart your Discord client (desktop/web) to force it to refetch the guild's command list.
- Confirm `DISCORD_GUILD_ID` in your environment actually matches the server you're testing in — commands
  synced to the wrong guild ID simply won't appear anywhere you can see.
- Check the bot's logs for `Synced N slash command(s) to guild ...` on startup; if that line is missing or
  errored, the bot may not have connected or the guild ID may be invalid.
