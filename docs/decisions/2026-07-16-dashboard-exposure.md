# Decision record — dashboard network exposure (P0.5)

**Date:** 2026-07-16 · **Status:** OPTION PENDING OWNER CHOICE (current state
documented below) · **Context:** dashboard binds `0.0.0.0:5000` over plain
HTTP on a public DigitalOcean IP; Basic Auth is enabled; the password was
rotated on 2026-07-16 after exposure in a screenshot.

## Options

### Option A — RECOMMENDED: loopback bind + Tailscale (or SSH tunnel)

The dashboard is unreachable from the public internet; the owner reaches it
from mobile via Tailscale (or an SSH tunnel from Termius).

Server steps (one per line, Termius-safe):

1. `curl -fsSL https://tailscale.com/install.sh | sh`
2. `sudo tailscale up`
3. Edit `docker-compose.yml`: change the dashboard port line to `"127.0.0.1:5000:5000"`
4. `docker compose up -d --no-deps dashboard`
5. On the phone: install the Tailscale app, log in to the same tailnet, open `http://<server-tailscale-ip>:5000`

Properties: no public attack surface, HTTP-over-WireGuard is encrypted in
transit, Basic Auth becomes defence-in-depth instead of the only wall.

### Option B — keep the public bind (accepted-risk variant)

If the owner keeps direct-IP access, ALL of the following are required:

- Basic Auth stays mandatory (`DASHBOARD_AUTH_USER`/`PASS` set — already true).
- Password is treated as sensitive (never in screenshots; rotate on exposure —
  done 2026-07-16).
- A firewall allowlist (`ufw allow from <owner-ip> to any port 5000` when the
  owner IP is stable, otherwise at minimum fail2ban on 401 spam).
- Accepted residual risk: plain-HTTP means credentials and dashboard content
  are readable by any on-path observer; the Flask/waitress surface is exposed
  to the internet.

## Current state (as of this branch)

- Compose still publishes `5000:5000` (Option B shape) so the owner's existing
  access keeps working; the Option A line is present as a comment.
- Basic Auth enforced on every route except `/health` (container healthcheck).
- `/api/system_state` reports `publicly_reachable` + a recommendation; no
  secrets appear in any endpoint, log line, or error page (adapter payloads
  are built from fetched data only and error strings are sanitised).

## Decision

- [ ] Option A (recommended) — owner runs the 5 steps above.
- [x] Option B until the owner picks — risk accepted **temporarily**, recorded
      here per the task-pack requirement. Revisit at Phase 1 dashboard
      redesign at the latest.
