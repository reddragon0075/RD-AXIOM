# ZeroAuthy (OccupySaaS) — Open-Source Identity Federation for Axiom

## Overview
Axiom supports **[ZeroAuthy](https://github.com/occupysaas/zeroauthy)** by OccupySaaS — an open-source, self-hosted, 100% free alternative to Auth0 under the Apache 2.0 license.

ZeroAuthy provides:
- **No Monthly Active User (MAU) Fees**: Unmetered authentication and identity federation.
- **Auth0 API Parity**: Speaks standard OAuth2, OpenID Connect (OIDC), and Auth0 management endpoints (`/authorize`, `/oauth/token`, `/userinfo`).
- **Enterprise & Social Logins**: Google, Microsoft Azure AD, SAML, and passwordless OTP/magic links.

---

## 1. Running ZeroAuthy via Docker

If Docker is installed on your machine or cloud VPS:

```bash
docker compose -f docker-compose.zeroauthy.yml up -d
```

Check logs to get your first-time admin setup URL:
```bash
docker logs axiom-zeroauthy
```

Access the ZeroAuthy Admin Console:
```text
https://system.localhost:8443/admin/
```

---

## 2. Axiom Configuration

In Axiom:
1. Navigate to **Settings → Roles & Permissions → Identity & SSO (ZeroAuthy)**.
2. Enter your ZeroAuthy tenant domain:
   - Local: `system.localhost:8443`
   - Cloud / Production: `https://auth.yourdomain.com`
3. Client ID: `axiom-fleet-app`
4. Click **Save Settings**.

---

## 3. Built-in Sovereign Fallback
When Docker or an external ZeroAuthy server is not running locally, Axiom's embedded sovereign engine handles the ZeroAuthy OIDC handshake seamlessly, allowing 1-click SSO login without external dependencies.
