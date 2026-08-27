# Capturing Dabble's SGM pricer

Everything for `dabble_sgm_price` is ready except one thing: the request the app fires
when you add a second leg to a same game multi. Dabble has no web betting UI, so the
browser capture that solved the other six books has nothing to drive — the only client
that builds an SGM is the phone app.

This is a job for you rather than for the agent, because it needs a proxy certificate
installed on your own device. **You are intercepting your own traffic to a service you
hold an account with.** Nothing here touches anyone else's data, and no credential needs
to leave your phone.

---

## What we are hunting

**One request.** When a second leg is added to an SGM, the app asks Dabble what the
combination is worth. That call is the whole prize; everything else is already modelled.

Concretely, save:

- the **full URL** (including query string)
- the **method**
- the **request body**, if any
- the **response body**
- the request **headers**, minus `Authorization` / `Cookie` (see the redaction note below)

If you get that, `dabble_sgm_price` is roughly an hour's work and the six-book comparator
becomes seven.

---

## Recommended: Proxyman (easiest on a Mac + iPhone)

[Proxyman](https://proxyman.io) has a free tier that does everything needed, and its
iOS-setup wizard handles the fiddly parts.

### 1. Install and start

```bash
brew install --cask proxyman
```

Open it. Note the port it reports (default **9090**) and your Mac's LAN IP:

```bash
ipconfig getifaddr en0
```

Phone and Mac must be on the **same Wi-Fi**.

### 2. Set the phone up

In Proxyman: **Certificate → Install Certificate on iOS → Physical Devices**, and follow
the wizard. It walks through three steps that all have to happen:

1. **Point the phone at the proxy.** iOS → Settings → Wi-Fi → your network → ⓘ →
   *Configure Proxy* → **Manual**. Server = your Mac's IP, Port = 9090.
2. **Install the certificate.** Visit `http://proxy.man/ssl` in Safari on the phone,
   download the profile, then Settings → General → VPN & Device Management → install it.
3. **Trust it** — this step is separate and easy to miss. Settings → General → About →
   **Certificate Trust Settings** → enable full trust for Proxyman.

Without step 3 you will see connections but every body will be unreadable.

### 3. Filter to just Dabble

In Proxyman's search box, filter on `dabble`. You want to see traffic to
`api.dabble.com.au`. If you see the domain but bodies show as encrypted, right-click it →
**Enable SSL Proxying** for that host.

### 4. Do the thing

On the phone, in the Dabble app:

1. Open any match with a **Same Game Multi** tab. If AFL is out of season, EPL and WNBA
   both had SGM-eligible markets when this was last checked — any sport with an SGM tab
   works.
2. **Clear Proxyman's log now.** This is the difference between one obvious request and
   four hundred.
3. Add **one** leg. Note what appears.
4. Add a **second** leg. → **This is the request.** Something should fire carrying both
   selections and coming back with a combined price.
5. Optional but genuinely useful: add a **third** leg, then remove one. That shows whether
   Dabble re-prices incrementally or resends the whole set — which decides the tool's
   shape.

### 5. Export

Right-click the request → **Export → Request & Response** (or Copy as cURL). Save it, and
drop it somewhere I can read — a file in the repo scratch dir is fine.

---

## Alternatives, if Proxyman does not suit

| Tool | Notes |
|---|---|
| **mitmproxy** | Free, CLI, scriptable. `brew install mitmproxy`, run `mitmweb`, phone proxy → Mac:8080, cert from `http://mitm.it`. Same trust step required. |
| **Charles Proxy** | The old standard, paid after 30 days. Same three-step phone setup. |
| **HTTP Toolkit** | Free tier, nicest UI of the three. |

Android is the same shape, with one extra wrinkle: since Android 7, apps ignore
user-installed CAs unless they opt in, so a plain APK often will not work without extra
steps. **The iPhone route is much less trouble** — use it if you have the choice.

---

## Before you send anything: redaction

The app is logged in, so its requests carry your session. Please strip, from every request
you send on:

- `Authorization:` headers (Dabble uses a bearer token)
- `Cookie:` / `Set-Cookie:`
- any `x-device-id` you would rather not share — a placeholder is fine, the spec already
  ships a zeroed one
- account ids, balances, and anything in a response that names you

**I do not need any of it.** The pricing call is expected to be anonymous — the other six
books' pricers all are, and Dabble's public feeds already work with no token. If the
capture shows the pricer genuinely *requires* auth, that is itself the finding, and it
would mean the tool cannot ship as a public read: say so and stop there rather than
sending a token.

---

## What happens next

Send the request and response and I will:

1. Replay it **unauthenticated** through plain curl to confirm it is a public read.
2. Probe the edges the way the other six were done — single leg, duplicate leg, redundant
   leg, mutually exclusive legs, an unknown id — since every book so far has had at least
   one silent-wrongness path and there is no reason to expect Dabble to be the exception.
3. Add `dabble_sgm_price` to `dabble.yaml` with a response hint carrying the traps and a
   dated worked example.
4. Add `tests/unit/test_dabble_sgm.py`, and register Dabble in `PRICERS`, `SCALE` and
   `REFUSAL_STYLE` in `test_sgm_comparator.py` — note the units question especially, since
   two of the six turned out not to be plain decimals.
5. Update `documentation/Dabble.md`, the scope doc, and the site catalogue.

## Background

`docs/SGM-AND-PLACEMENT-SCOPE.md` → "Bookmaker 6: Dabble" records what was already ruled
out, so none of it needs redoing: ~40 candidate routes probed against a clean 404 baseline,
no swagger document, and the observation that every fixture declares an SGM market group
(`"Popular SGMs"` / `"Same Game Multi's"`) which appears in `marketGroups` but never in
`marketGroupMappings` — something fills that group, and that something is what this capture
is looking for.
