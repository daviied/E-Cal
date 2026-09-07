# CalcVault

A self-hosted, Desmos-style calculator (computation only, no graphing).
Organize calculators into folders, and build "functions" that hide all the
math behind one input box and one output.

## Stack

- **Frontend**: static HTML/CSS/JS, no build step at dev time.
  - [MathLive](https://cortexjs.io/mathlive/) `<math-field>` for typing/rendering
    math the same way Desmos does (LaTeX under the hood, so copy/paste between
    this app and Desmos works for standard expressions).
  - [math.js](https://mathjs.org/) does the actual evaluation, using a
    left-to-right variable scope per calculator (same mental model as Desmos:
    define `a = 5`, then `b = a * 2` on the next line, etc).
- **Backend**: Python (FastAPI) + SQLite. All folders and calculators are
  stored server-side in `/app/data/calcvault.db` (mounted as `./data` on the
  host) — nothing lives in browser storage.
- **Auth**: single shared password (from `APP_PASSWORD`), signed session
  cookie. No usernames/accounts, since this is meant for one person.
- **Packaging**: Docker, meant to sit behind your own reverse proxy for TLS.

## How a calculator works

Every calculator is an ordered stack of lines, evaluated top-to-bottom into
one shared scope (same mental model as Desmos: `a = 5`, then `b = a * 2` on
the next line can see `a`). Each line has a role:

- **Eq** — a plain equation/expression as a `<math-field>`, with its computed
  value shown alongside. Can be checked **Hidden when locked**.
- **Input** — a variable with its own display label, independent of the
  variable name (e.g. variable `V`, labeled "Voltage"). Always shown as an
  editable box, in both locked and unlocked views.
- **Output** — an expression with its own display label (e.g. expression
  `V*I`, labeled "Power"), shown as a read-only computed result.

The **Unlocked/Locked** button in the header toggles the whole view:
- **Unlocked** — every line is shown with full controls (role picker, hidden
  checkbox, delete) so you can build/edit freely.
- **Locked** — lines marked "Hidden when locked" disappear (they still
  compute, feeding later lines silently); Input/Output lines collapse down to
  just their label + value, hiding the underlying variable name or formula.
  This is the "type one thing in, see one thing out" mode.

Press **Enter** inside any line's field to insert a new line of the same
role right below it, focused and ready to type. Drag a line's grip handle
(⠿, visible when unlocked) onto another line to reorder them.

## Running it locally without Docker (for quick testing)

You need Python 3.11+ and the vendored frontend libs in `frontend/lib/`
(MathLive + math.js — see "Vendoring the frontend libs" below if that
directory is empty).

```bash
pip install -r backend/requirements.txt
set APP_PASSWORD=testpass123
set SESSION_SECRET=dev-secret-change-me
set HTTPS_ONLY=false
set DB_PATH=./data/calcvault.db
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

(use `export` instead of `set` on macOS/Linux). Then open
`http://127.0.0.1:8000`.

### Vendoring the frontend libs without Node/npm

If you don't have Node installed, you can fetch the two required libraries
directly from the npm registry without `npm`:

```bash
curl -sL https://registry.npmjs.org/mathlive/latest -o /tmp/ml.json
# read .dist.tarball from that JSON, then:
curl -sL <tarball-url> -o mathlive.tgz && tar xzf mathlive.tgz
cp -r package/*.mjs package/*.js package/fonts frontend/lib/mathlive/
# same idea for mathjs, but its browser bundle lives at lib/browser/math.js
# inside the tarball, not dist/ — copy that file to frontend/lib/mathjs.min.js
```

Then create `frontend/lib/import-map.json`:
```json
{ "imports": { "mathlive": "/lib/mathlive/mathlive.min.mjs" } }
```

The Docker build (below) automates all of this — this section is only for
running straight off the Python interpreter for quick iteration.

## Running it with Docker

1. Copy the env file and fill in a real password + session secret. **The
   login password is set entirely through the `APP_PASSWORD` environment
   variable** — there's no username, no password stored in the database,
   nothing to configure in the UI. The container refuses to start if it's
   missing.

```bash
cp .env.example .env
```

```env
APP_PASSWORD=pick-a-strong-password
SESSION_SECRET=$(openssl rand -hex 32)
HTTPS_ONLY=true
```

2. Build and start:

```bash
docker compose up -d --build
```

3. By default the app publishes port `8000` on all interfaces, so it's
   reachable at `http://<host-ip>:8000` on your LAN immediately — convenient
   for CasaOS's dashboard or a reverse proxy container to reach. Once you
   have a reverse proxy in front doing TLS (recommended for anything beyond
   your own LAN), lock it down by changing the `ports:` line in
   `docker-compose.yml` to `"127.0.0.1:8000:8000"` so only that proxy (running
   on the same host) can reach it directly.

   Point the proxy at it with something like an Nginx
   `location / { proxy_pass http://127.0.0.1:8000; }` block (make sure it
   forwards `X-Forwarded-Proto`), or a Caddy `reverse_proxy 127.0.0.1:8000`
   (Caddy sets forwarded headers automatically). Uvicorn runs with
   `--proxy-headers`, so it trusts those forwarded headers for detecting
   HTTPS.

4. If you're testing locally without TLS/a proxy first, set `HTTPS_ONLY=false`
   in `.env` temporarily — otherwise the browser won't send the session
   cookie back over plain HTTP and you'll get bounced to the login screen in
   a loop. Flip it back to `true` once you're behind real HTTPS.

Data persists in `./data/calcvault.db` on the host; back that file up like
you would any SQLite database.

## Running it on CasaOS

CasaOS is just Debian + Docker under the hood, so the compose file above
works as-is. Two ways to install it:

### Option A — terminal (most reliable)

1. Copy this whole `calcvault/` project folder onto the CasaOS box, ideally
   under `/DATA/AppData/calcvault` (CasaOS's usual convention for app data —
   the compose file's `./data` volume will then resolve to
   `/DATA/AppData/calcvault/data`, which shows up nicely in CasaOS's Files app).
2. SSH into the device (or use CasaOS's built-in terminal app) and `cd` into
   that folder.
3. Same steps as above: `cp .env.example .env`, edit it with a real
   `APP_PASSWORD`/`SESSION_SECRET`, then `docker compose up -d --build`.
4. CasaOS should pick up the running container automatically; if not, its
   dashboard can also just show it as an externally-managed container.

### Option B — CasaOS's "Install a customized app" UI

1. Open CasaOS → App Store → the "+" / custom-install option that accepts a
   docker-compose YAML.
2. Paste in `docker-compose.yml`. CasaOS should detect the `${APP_PASSWORD}`,
   `${SESSION_SECRET}`, and `${HTTPS_ONLY}` references and prompt for values
   in its install form — fill in a real password and a random session secret
   there (e.g. from `openssl rand -hex 32`).
3. One catch: CasaOS's custom-install UI builds from a compose file directly
   and may not have this project's `Dockerfile`/`backend`/`frontend` source
   available to build from, since `build: .` needs that context present on
   disk. If the install fails on the build step, use Option A instead (it
   always works since it's just `docker compose` on the actual filesystem),
   or build the image once yourself (`docker compose build`, then
   `docker tag calcvault-calcvault yourname/calcvault:latest` and push it
   somewhere CasaOS can pull it from), swapping `build: .` for
   `image: yourname/calcvault:latest` in the compose file.
4. The `x-casaos:` block in `docker-compose.yml` is purely cosmetic (gives
   CasaOS a title/category to show) — delete it freely if it confuses your
   version of the UI.

## Notes / things worth knowing

- This was built without a live browser/Docker environment to test against,
  so a couple of spots are worth a sanity check on first run:
  - MathLive's exact browser bundle filename can vary by version — the
    Docker build (`build/generate-importmap.js`) resolves it dynamically
    from the installed package's `package.json`, rather than a hardcoded
    name, specifically to avoid this breaking.
  - MathLive needs its font files (shipped alongside its JS in `dist/`) to
    render math glyphs. The whole `dist/` folder is vendored so they sit
    next to the script; if symbols look broken, check the browser console
    for 404s under `/lib/mathlive/` and adjust `MathfieldElement.fontsDirectory`
    in `frontend/app.js` if needed.
  - Copy/paste from Desmos: standard algebraic expressions round-trip fine
    since both use LaTeX. Desmos-specific things this app doesn't implement
    (sliders, graphing, actions, lists/tables, regressions) obviously won't
    translate — this app is compute-only, as requested.
- Rate limiting on login is a simple in-memory per-IP counter (10 attempts /
  15 minutes) — fine for a personal single-user app, not a substitute for
  putting this behind a proxy you control.
- No plotting, by design.
