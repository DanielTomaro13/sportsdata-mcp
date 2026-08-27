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

## Why the easy-looking shortcuts do not work

Worth knowing before you start, because two obvious ideas stop one step short:

- **iPhone Mirroring / screen sharing** mirrors *pixels and input*. The app's requests
  still go phone → Dabble directly and the Mac never sees them.
- **USB capture** genuinely works — `rvictl` ships with macOS at
  `/Library/Apple/usr/bin/rvictl` and creates a virtual interface mirroring the phone's
  traffic, no proxy and no certificate needed. But what it yields is **TLS-encrypted
  packets**: the handshake, the SNI (`api.dabble.com.au`), timings and byte counts — not
  the URL path, not the body, not the response.

Reading the payload means terminating TLS, and that means the phone trusting a certificate
you control. **That step is unavoidable on every route.** Everything else about the setup
is negotiable, and the option below keeps it to one device.

---

## Recommended: an on-device HTTPS debugger (no Mac involved)

Simplest path by a distance. These run the proxy on the phone itself, so there is no
second machine, no Wi-Fi proxy configuration and no same-network requirement:

- **Proxyman for iOS**
- **Thor**
- **Stream**

Any of them works. The flow is the same:

1. Install from the App Store and open it.
2. Let it install its **certificate profile** — it will walk you through it.
3. **Trust it**, which is a separate step and the one people miss: Settings → General →
   About → **Certificate Trust Settings** → enable full trust for the app's certificate.
   Skip this and you will see connections with unreadable bodies rather than an error,
   which is a confusing way to fail.
4. Start recording, and filter to `api.dabble.com.au`.

Then, in the Dabble app:

1. Open any match with a **Same Game Multi** tab. If AFL is out of season, EPL and WNBA
   both had SGM-eligible markets when this was last checked — any sport with an SGM tab
   works.
2. **Clear the capture log now.** This is the difference between one obvious request and
   four hundred.
3. Add **one** leg. Note what fires.
4. Add a **second** leg. → **This is the request.** Something should carry both selections
   and come back with a combined price.
5. Optional but genuinely useful: add a **third** leg, then remove one. That shows whether
   Dabble re-prices incrementally or resends the whole set, which decides the tool's shape.

Share the request and response out of the app — export, or copy as cURL.

---

## If you would rather use the Mac: Proxyman on macOS

More moving parts, but the desktop UI is nicer for picking through a busy log.

```bash
brew install --cask proxyman
```

Note the port (default **9090**) and your Mac's LAN IP:

```bash
ipconfig getifaddr en0
```

Phone and Mac must be on the **same Wi-Fi**. Then **Certificate → Install Certificate on
iOS → Physical Devices** and follow the wizard, which covers three things that all have to
happen:

1. **Point the phone at the proxy.** Settings → Wi-Fi → your network → ⓘ →
   *Configure Proxy* → **Manual**. Server = your Mac's IP, Port = 9090.
2. **Install the certificate** — visit `http://proxy.man/ssl` in Safari on the phone, then
   Settings → General → VPN & Device Management → install.
3. **Trust it** — Settings → General → About → **Certificate Trust Settings**.

Filter on `dabble`; if bodies show as encrypted, right-click the host → **Enable SSL
Proxying**. Then follow the same in-app steps as above, and
**Export → Request & Response**.

---

## If the Dabble app says "connection offline" once the proxy is on

Three different causes, and only one of them means stopping. Triage in this order.

**The decisive test.** Turn SSL proxying OFF for `api.dabble.com.au` (Proxyman → Tools →
SSL Proxying List, remove the host) and restart the app. Proxyman then tunnels the
connection through untouched instead of terminating it.

- **App works again** → the proxy and certificate are fine; the app is rejecting *your*
  certificate specifically. That is **certificate pinning**. Stop — see below.
- **App still offline** → not pinning. It is the setup; work through the list.

**Setup checks, in order:**

1. **Is the certificate TRUSTED, not just installed?** Settings → General → About →
   **Certificate Trust Settings** → toggle on. Installing the profile and trusting it are
   two separate actions and the second is the one that gets missed.
2. **Is the proxy routing at all?** Load any HTTPS site in Safari on the phone. Decrypted
   in Proxyman → certificate and trust are good, so the problem is Dabble-specific.
   Nothing in Proxyman at all → the Wi-Fi proxy settings are not taking.
3. **Has the Mac's IP moved?** DHCP reassigns. `ipconfig getifaddr en0`.

**A Dabble-specific cause that looks identical to pinning.** Dabble is Cloudflare-fronted
and bot-gated — see the provider notes at the top of `dabble.yaml`. A proxy changes the TLS
fingerprint the client presents, so Cloudflare can reject the connection before Dabble's
own app logic is reached. Tell them apart by what Proxyman shows:

| Proxyman shows | Cause |
|---|---|
| nothing at all | proxy not routing — setup, check 2 above |
| TLS handshake failure / immediate client reset | certificate pinning |
| a 403, or a Cloudflare challenge page | Cloudflare bot gating on the TLS fingerprint |

**If it is pinning, stop there.** Defeating it means patching the app binary, which is well
past what this is worth. Say so and Dabble gets recorded as blocked-with-a-reason — a
perfectly good outcome, and one the scope doc already treats as a first-class result
rather than a failure.

---

## Other desktop options

| Tool | Notes |
|---|---|
| **mitmproxy** | Free, CLI, scriptable. `brew install mitmproxy`, run `mitmweb`, phone proxy → Mac:8080, cert from `http://mitm.it`. Same trust step. |
| **Charles Proxy** | The old standard, paid after 30 days. Same phone setup. |
| **HTTP Toolkit** | Free tier, nicest desktop UI of the three. |

Android is the same shape with one extra wrinkle: since Android 7 apps ignore
user-installed CAs unless they opt in, so a plain APK often will not work at all without
patching. **The iPhone route is much less trouble** — use it if you have the choice.

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
