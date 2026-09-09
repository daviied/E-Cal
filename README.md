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
(⠿, visible when unlocked) onto another line to reorder them. Folders in
the sidebar (draggable onto each other to nest, with a **+** button per
folder for a subfolder) start collapsed and stay however you leave them
for the rest of the session.

### Math notes

- `log(x)` is base 10 and `ln(x)` is natural log - the usual calculator/
  Desmos convention. (The underlying math.js library defaults the other
  way: `log(x)` natural, no `ln` at all - overridden here on purpose.)
- `|x|` (absolute value bars) works as expected.
- Subscripted variable names work as multi-character/word subscripts, e.g.
  a variable typed as `V_2ab4s` in an Input line's name field matches the
  same variable referenced as `V_{2ab4s}` in any other line's math-field.

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

## Image build & publishing

`docker-compose.yml` runs a **pre-built image** (`ghcr.io/daviied/e-cal:latest`)
rather than building from source — this is what lets CasaOS (or anything
else) install it with no local source and no build wait. The image is built
and published automatically by `.github/workflows/docker-publish.yml`: every
push to `main` triggers a GitHub Actions run that builds the Dockerfile and
pushes `latest` (plus a commit-sha tag) to GitHub Container Registry.

**One-time setup after pushing this repo to GitHub:** the first Actions run
will publish the image, but GHCR packages built this way default to
**private**, even in a public repo. Make it public once so CasaOS (or anyone)
can pull it without authenticating:

1. Push to `main` (or trigger the workflow manually) and let the Action finish.
2. On GitHub: your profile → **Packages** → `e-cal` → **Package settings** →
   change visibility to **Public**.

If you'd rather build locally instead of waiting on Actions:
```bash
docker compose build
docker compose up -d
```
(this still uses `image:`, so `docker compose build` will tag it locally as
`ghcr.io/daviied/e-cal:latest` and `up -d` will run that local copy instead
of pulling).

## Running it locally with Docker (non-CasaOS)

1. Pull and start:

```bash
docker compose up -d
```

2. Before you do, open `docker-compose.yml` and edit the `environment:`
   values directly — **the login password is the `APP_PASSWORD` value**
   (there's no username, and the container refuses to start without it).
   Also generate a real `SESSION_SECRET` (e.g. `openssl rand -hex 32`).

3. The bind-mount volume defaults to the CasaOS convention path
   `/DATA/AppData/calcvault/data`. On a non-CasaOS host, either create that
   directory first (`mkdir -p /DATA/AppData/calcvault/data`) or change the
   `volumes:` `source:` to something like `./data`.

4. By default the app publishes port `8000` on all interfaces, reachable at
   `http://<host-ip>:8000`. Once you have a reverse proxy in front doing TLS,
   set `HTTPS_ONLY=true` and point the proxy at `http://127.0.0.1:8000` (an
   Nginx `location / { proxy_pass http://127.0.0.1:8000; }` block, forwarding
   `X-Forwarded-Proto`, or Caddy's `reverse_proxy 127.0.0.1:8000` which sets
   forwarded headers automatically — Uvicorn runs with `--proxy-headers` so
   it trusts them). Leave `HTTPS_ONLY=false` for plain-http/LAN-only use,
   otherwise the login cookie won't be sent back and you'll loop on the login
   screen.

## Running it on CasaOS

### Option A — CasaOS's "Install a customized app" UI

1. Open CasaOS → App Store → the "+" / custom-install option that accepts a
   docker-compose YAML.
2. Paste in the contents of `docker-compose.yml`.
3. CasaOS reads the `x-casaos.envs` descriptions and should show editable
   fields for `APP_PASSWORD`, `SESSION_SECRET`, and `HTTPS_ONLY` in its
   install form — set a real password and a random session secret there.
4. Install. Since it's a plain `image:` pull (no build), this should be fast
   — just needs to download the image once.

### Option B — terminal

```bash
mkdir -p /DATA/AppData/calcvault && cd /DATA/AppData/calcvault
curl -o docker-compose.yml https://raw.githubusercontent.com/daviied/E-Cal/main/docker-compose.yml
# edit the environment: values in docker-compose.yml directly (APP_PASSWORD, SESSION_SECRET)
docker compose up -d
```

The volume's `source:` already points at `/DATA/AppData/calcvault/data` —
CasaOS's usual convention — so it shows up nicely in its Files app.

### Updating later

New pushes to `main` rebuild and republish `latest` automatically. To pick up
a new version on the CasaOS box:

```bash
docker compose pull
docker compose up -d
```

**Your calculators and folders are safe across updates.** They live in
`calcvault.db` on the bind-mounted `/DATA/AppData/calcvault/data` volume, not
inside the container — `docker compose pull` / `up -d` only replaces the
container and its code, never that host directory. The only ways to actually
lose data are `docker compose down -v` (the `-v` removes volumes - don't use
it) or manually deleting that data folder. The app also reads its database
schema with `CREATE TABLE IF NOT EXISTS`, so it never drops/recreates tables
on startup, and the frontend auto-converts any older data shape it
encounters (e.g. calculators made before Input/Output lines existed) rather
than failing to load them.

### Note on this specific repo

`daviied/E-Cal` is currently a **public** repo that was populated via a
manual file upload rather than `git push`, so it's missing `.gitignore` and
still has a `data/calcvault.db` and `server.log` sitting in it from that
upload — worth deleting those from the repo (and adding `.gitignore`) before
relying on it, both so a public clone doesn't carry your test data and so a
future edit doesn't accidentally commit a real `.env`.

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
