# HTTPS for phone tests (M3, week 5)

Passkeys (and the phone camera for face) only work in a **secure context**: `https://…`, or
`http://localhost`. A phone cannot open our laptop's `localhost`, and `http://192.168.x.x:5173` is not
secure, so the browser hides WebAuthn there. We use an **ngrok tunnel**: the phone opens
`https://<name>.ngrok-free.app`, ngrok forwards to the Vite server on the laptop, and Vite forwards `/api`
to the backend, so page and API stay on one origin.

```
phone  --https-->  ngrok cloud  --tunnel-->  ngrok agent on laptop  -->  Vite :5173  --/api-->  backend :8000
```

## 1. One-time set-up

1. Create a free ngrok account and install the agent: <https://ngrok.com/download>.
2. `ngrok config add-authtoken <your token>` (from the ngrok dashboard; never commit it).
3. In the dashboard, under **Domains**, claim your **one free static domain**, e.g.
   `trustauth-demo.ngrok-free.app`.

**Why a static domain matters:** a passkey is bound to the RP ID (the domain). With a random ngrok URL
that changes every start, every volunteer's passkey would stop working the next day. Use **one fixed
domain for the whole study** and share it in the team (only one member's ngrok account runs the tunnel
during sessions).

## 2. Settings in `.env`

```sh
FACTOR_MODE=real                              # the real passkey factor answers, not the mock
WEBAUTHN_RP_ID=trustauth-demo.ngrok-free.app  # the bare domain: no https://, no port, no slash
WEBAUTHN_ORIGIN=https://trustauth-demo.ngrok-free.app
WEBAUTHN_RP_NAME=TrustAuth
COOKIE_SECURE=true                            # device cookie only over https
TRUSTED_PROXY_HOPS=2                          # ngrok + Vite in front of the backend (see §5)
```

Then restart: `docker compose up -d --build backend`. With `FACTOR_MODE=real` the backend **does not
start** (error in `docker compose logs backend`) if `WEBAUTHN_ORIGIN` is not on the `WEBAUTHN_RP_ID`
domain or is `http://` on a non-localhost domain (`PasskeySettings.check()`). Failing loudly is on
purpose: that mistake would otherwise make every registration fail with `rejected`.

For **laptop-only** development keep the defaults (`localhost`, `http://localhost:5173`,
`COOKIE_SECURE=false`, `TRUSTED_PROXY_HOPS=1`).

## 3. Start the tunnel

```sh
docker compose up -d                                         # the stack, as usual
ngrok http 5173 --url=https://trustauth-demo.ngrok-free.app  # older agents: --domain=trustauth-demo.ngrok-free.app
```

Open `https://trustauth-demo.ngrok-free.app/passkey-demo.html` on the phone. The free plan first shows
an ngrok warning page: tap **Visit Site** (once per browser).

## 4. Test checklist (write the results in the PR)

| # | Device / browser | Expected |
|---|---|---|
| 1 | Laptop, `http://localhost:5173/passkey-demo.html` (localhost settings) | "Secure context"; Windows Hello / Touch ID prompt; server `{"done": true}` |
| 2 | Laptop, same page, close the prompt | server `{"done": false, "reason": "cancelled"}` |
| 3 | Android phone, Chrome, ngrok URL (ngrok settings) | fingerprint / screen lock prompt; `done: true` |
| 4 | iPhone, Safari, ngrok URL | Face ID prompt; `done: true` |
| 5 | Phone, `http://<laptop-ip>:5173/passkey-demo.html` | page says "Not a secure context" (expected: shows why we need HTTPS) |
| 6 | Same account, second device (paste the session) | `done: true`, a 2nd row in `webauthn_credentials` |
| 7 | Same device twice for one account | the browser itself refuses (`InvalidStateError`, because of `excludeCredentials`) → `cancelled` |
| 8 | ngrok settings but page opened via `localhost` | `rejected` (origin does not match): this is the phishing protection working |

Check the stored rows (public keys only, no secrets):

```sh
docker compose exec db psql -U trustauth -c "select user_id, transports, backed_up, created_at from webauthn_credentials;"
```

## 5. Two things the platform does for this (M4)

- `docker-compose.yml` passes `WEBAUTHN_RP_ID`, `WEBAUTHN_ORIGIN`, `WEBAUTHN_RP_NAME`, `COOKIE_SECURE` and
  `TRUSTED_PROXY_HOPS` from `.env` to the backend.
- **Client IP behind proxies.** Behind Vite (and ngrok) the backend would see the proxy's address for
  every login, so "known network" in the risk score would be meaningless. Vite adds the real address in
  `X-Forwarded-For`, and the backend trusts exactly `TRUSTED_PROXY_HOPS` entries from the right: 1 for
  Vite only, 2 for ngrok + Vite. A header the phone sends itself is ignored, so it cannot fake a known
  network.
- Vite 5.4.11 (our version) accepts any host name. If Vite is ever upgraded to 5.4.12 or later, add
  `allowedHosts: [".ngrok-free.app"]` under `server` in `frontend/vite.config.ts`, or ngrok requests are
  refused.
