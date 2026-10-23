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
  - [nerdamer](https://nerdamer.com/) does the symbolic differentiation behind
    the `d/dx` button on Eq/Output lines.
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
  value shown alongside. Can be checked **Hidden when locked**; a new Eq
  line starts checked, so the locked view shows only Inputs and Outputs
  until you choose otherwise.
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

### Global and shared lines

A calculator can use lines it doesn't contain itself, at two levels:

- **Global lines** - the **Global lines** entry at the top of the sidebar.
  Anything defined there (constants, formulas, givens) is available in every
  calculator.
- **Folder lines** - the **Σ** button on a folder header (always visible on a
  touch screen). Shared by every calculator in that folder *and its
  subfolders*, so one folder per assignment can hold that assignment's givens.

Both are edited in the same line editor as a calculator (Eq and Input lines;
an Output line has no use there). A calculator evaluates, in order: the
global lines, the shared lines of each folder from the outermost down to the
one it sits in, then its own lines. Later lines win, so a question can
override a shared value just by assigning it again (`m = 5` after the folder
defined `m = 2` changes `m` for that question only). A banner above a
calculator's lines shows which sets it uses, with their line counts; tap one
to edit it. A small **Σ3** badge in the sidebar means that folder (or the
global set) has three lines. Moving a calculator to another folder changes
what it inherits immediately.

Errors in a shared line show where that line is edited, not in every
calculator that uses it. Shared lines are edited in the web app only. The
first HP Prime app's sync (`hpprime/`) copies each calculator's own lines but
not these, so there a line that relies on a shared constant will not know
it. **CalcVault 2** (`hpprime2/`) copies them to the calculator, read-only,
and evaluates them in the same order as here.

### Math notes

- `log(x)` is base 10 and `ln(x)` is natural log - the usual calculator/
  Desmos convention. (The underlying math.js library defaults the other
  way: `log(x)` natural, no `ln` at all - overridden here on purpose.)
- `|x|` (absolute value bars) works as expected.
- **Piecewise functions**: there's no dedicated piecewise UI - type a
  condition as a ternary, e.g. `x \geq 0 ? x^2 : -x` (type `>=`/`<=`/`!=` or
  use the virtual keyboard's ≥/≤/≠ - both work). Nest ternaries for more
  than two branches: `x<0 ? -1 : (x==0 ? 0 : 1)`. MathLive's own
  `\begin{cases}...\end{cases}` notation renders prettily but doesn't
  evaluate - math.js has no notion of it - so stick to the ternary form for
  anything meant to compute.
- Subscripted variable names work as multi-character/word subscripts, e.g.
  a variable typed as `V_2ab4s` in an Input line's name field matches the
  same variable referenced as `V_{2ab4s}` in any other line's math-field.
- Matrices: the **⊞** button next to an Eq/Output field's math-field inserts
  a matrix template (prompts for rows/cols). Type `\det` (or click the
  virtual keyboard's det button, if your MathLive build has one) around it
  to get the determinant, e.g. `\det\begin{pmatrix}2&1\\1&3\end{pmatrix}`
  evaluates to `5`. Plain matrix arithmetic (addition, multiplication)
  works too, since it's just math.js underneath.

### CAS: derivatives

Eq and Output lines have a **d/dx** button next to the matrix button. It
asks which variable to use (pre-filled with its best guess — the first
letter in the expression that isn't a known function name), then drops the
symbolic derivative into a fresh line right below, leaving the original
expression untouched. It is computed by [nerdamer](https://nerdamer.com/), a
separate symbolic-algebra engine from math.js (which only ever evaluates to
a number) — vendored the same way as MathLive and math.js.

- `log(x)`/`ln(x)` round-trip through this app's base‑10/natural convention
  correctly (nerdamer's own convention is the opposite, similar to
  math.js's — the conversion happens automatically in both directions).
- The `V_2ab4s`-style multi-character subscript variable names described
  above aren't recognized as a single symbol by nerdamer's parser (it reads
  `V_2ab4s` as `V_2` times a separate variable `ab4s`) - stick to
  single-letter variable names (with or without a single-character
  subscript, e.g. `x_1`) when using this button.
- Invalid input shows an error dialog instead of adding a line.

### Complex numbers

`i` is the imaginary unit, so `z = 1 + 2i` works, and so do arithmetic,
`|z|` (magnitude), `\sqrt{-4}` (`2i`) and polar form (`3e^{i\pi/4}`).
Results print as `a + bi`. To take a number apart:

| To get | Type | Keypad |
|---|---|---|
| real part | `Re(z)` or `\Re(z)` | SHIFT 2 |
| imaginary part | `Im(z)` or `\Im(z)` | SHIFT 3 |
| conjugate | `conj(z)` or `\overline{z}` (bar over z) | SHIFT + |
| angle (radians) | `rg(z)` | SHIFT 0 |
| magnitude | `\|z\|` (absolute-value bars) | SHIFT ^ |

`Re`/`Im` must be followed by an opening parenthesis (that is how they are
told apart from letters multiplied together); pasted TI-Nspire text
`real(z)`, `imag(z)` and `angle(z)` is understood too, and the **⇄** copy
button writes them back as `real`, `imag` and `angle`. (On a TI-Nspire the
imaginary unit is its own ⅈ symbol rather than the letter i, so type that
when pasting a number with an imaginary part back into it.)

### Copying to/from TI-Nspire

**Values**: every computed result has a small **⧉** copy button next to it
that copies just the plain number to the clipboard — no notation to
translate, so it pastes cleanly into any app's number entry, TI-Nspire
included.

**Pasting an equation from Nspire into this app** already works with no
special handling: copy an expression off an Nspire (or type it directly into
a line's math-field) and Ctrl+V it into any Eq/Input/Output field. Nspire's
clipboard is plain text that writes multiplication as an explicit `*` (e.g.
copying `14229ab+1` off an Nspire and pasting into a plain text editor
yields the literal text `14229*ab+1`) but otherwise uses bare juxtaposition
for implied multiplication between single-letter variables (`ab` meaning
`a*b`) — MathLive already parses pasted plain text exactly the same way it
parses typed input, so `ab` becomes two separate variables the same way
Desmos would read it, and math.js already evaluates the result correctly.

**Copying an equation from this app for Nspire**: the **⇄** button next to
a line's value-copy button (on Eq lines, and on Output lines) copies the
underlying equation as plain text formatted for Nspire's entry line —
every multiplication written out as an explicit `*` (since we can't be sure
Nspire's parser accepts bare juxtaposition of an arbitrary/multi-character
variable name the way math.js does), `log()`/`ln()` left alone (Nspire uses
the same base‑10/natural convention this app does), and everything else
passed through as-is. This has **not been verified against real Nspire
hardware** — if a copied equation doesn't paste cleanly, the most useful
thing to report back is the exact text produced by both directions (what
`⇄` copies, and what pasting Nspire's own clipboard into a plain text
editor produces) so the conversion in `frontend/app.js`'s `toNspireText`
can be corrected. Matrices are out of scope for this converter — Nspire's
matrix literal syntax hasn't been verified at all.

## Installing as an app on a phone/tablet (PWA)

CalcVault ships a web app manifest, icons, and a small service worker, so
Chrome on Android can install it to the home screen as a standalone,
full-screen app (menu → **Install app** / **Add to Home screen**).

**It must be served over HTTPS** for the install prompt (and the service
worker) to work - browsers refuse both on plain `http://` LAN addresses like
`http://192.168.1.50:8000` (only `localhost` is exempt). Put it behind a
reverse proxy that does TLS (see "Running it locally with Docker") and set
`HTTPS_ONLY=true`. Over plain http, "Add to Home screen" still makes a
bookmark-style shortcut, but it opens in a normal browser tab rather than as
an installed app.

The service worker is network-first (never cache-first), so a redeploy is
picked up immediately, and it never touches `/api/*` - the app still needs a
connection to your server to load or save calculators.

On phone-width screens (≤760px) the app switches to a handheld-calculator
layout, modeled loosely on the HP Prime G2: a dark body, a light "screen"
showing the calculator's lines under a blue title bar, and an on-screen
keypad docked at the bottom that replaces both MathLive's own keyboard and
the OS keyboard. Keys type into whichever line you last tapped:
**SHIFT** (blue) one-shots the small blue label above a key (sin⁻¹, eˣ, 10ˣ,
√ ↔ π, ≥ ≤ ≠ < > ? : _ =, a/b fraction, |x|, i, Re, Im, conj, arg, CLEAR…); **ALPHA** (orange)
swaps in a letters layer for variable names (one-shot; tap twice to lock,
**123** to return); **▲/▼** move between lines, and SHIFT+▲ runs the d/dx
CAS action on the current line; **ENTER** adds a new line below,
like pressing Enter on desktop. The **⌨** button in the title bar switches to your phone's normal keyboard
for equation fields (hiding the keypad until you tap it again); an Input
line's variable-name and label boxes always use the normal keyboard. The ⋯
button in the title bar reveals the
move-to-folder and delete controls. The sidebar becomes a slide-out drawer
(☰ to open, closes itself when you pick a calculator) and each line wraps so
the equation gets its own full-width row. On wider screens the sidebar can be
hidden with **«** and brought back with ☰; that choice is remembered per
device. Drag-to-reorder lines/folders uses desktop-style drag and drop, which
touch browsers don't support, so reordering is a desktop/mouse feature for
now.

## HP Prime G2: CalcVault 2 and online mode

`hpprime2/` holds the second version of the calculator app and its PC sync
tool (the first, `hpprime/`, is unchanged). It adds Enter-for-a-new-Eq-line,
a tap-to-type palette of the calculator's variable names, shared lines on
the calculator, and an **online mode**: the calculator works as a remote for
this app, kept in step within about half a minute while CalcVault 2 is open on
it, and opening a calculator here opens it there too. Online mode runs in
this page (the **Online** switch in the HP Prime panel below; nothing to
install), or from the PC tool `hpprime2/sync/Online CalcVault.bat`, which
learns what is open here through `GET`/`PUT /api/hp-focus` (a hint kept in
memory only). See `hpprime2/README.md`.

## Syncing with an HP Prime G2 from the web page

The **HP Prime** button in the sidebar opens a panel that connects a G2 and
syncs it with this app: the same two-way merge as the PC tool in
`hpprime2/` (see `hpprime2/README.md` for the calculator app itself and for how
folders, lines, conflicts and deletions are handled), but run from the web
page, with nothing to install on the PC.

How it works: the calculator's USB cable goes into the computer the
**browser** is running on. The page talks to the calculator directly with
WebHID (`frontend/hp.js`, a JavaScript port of the USB layer in
`hpprime2/sync/cvsync/primelink.py`), while the merge runs on the server
(`backend/app/hp.py` → `hpprime2/sync/cvsync/webrun.py`), which asks the page
over a WebSocket to read or write one note at a time. Nothing about your
calculators is sent anywhere except between your browser and your own server.

To use it: plug the calculator in, turn it on, leave it on its Home screen
with CalcVault closed, close HP's Connectivity Kit, then in the panel press
**Connect calculator** (pick the HP Prime in the browser's chooser, once) and
**Sync now**. A sync that would delete something or resolve a conflict shows
what it will do and asks first. **Online** keeps syncing by itself (within a
half a minute of a change on either side) and does *not* ask, like the PC
tool's live mode, with backups as the safety net. It is meant for CalcVault 2
left open on the calculator (it also shows "online" there and opens what you
open here), stays on for this browser until switched off, and restarts by
itself when the page is opened with the calculator plugged in. With the first
CalcVault app, close it on the calculator for a sync.

Requirements and limits:

- A browser with WebHID: **Chrome or Edge on a computer** (Windows, macOS,
  Linux, ChromeOS). Not Firefox, not Safari, and **not Android or iOS** - on a
  phone or tablet the panel just says so. (Use the web app there as usual and
  sync with a computer.)
- The page must be served over **HTTPS** (or be `localhost`); browsers refuse
  USB access to plain `http://` pages.
- Like the PC tool, the sync's merge state and backups (the last 30 of each)
  are kept on the server, in a `hpsync/` folder next to the database (so on
  the Docker data volume). Use **either** this panel **or** the PC tool for a
  given calculator: each keeps its own record of what was last synced, so
  alternating between them makes it report changes as conflicts (nothing is
  lost - the calculator's version is kept as a "(calculator copy)").
- The Docker image includes the sync code from `hpprime2/sync/cvsync`
  (CalcVault 2's, which works with either calculator app and also copies the
  global and folder lines); if you
  build a stripped-down image without that folder, the panel says the server
  cannot sync (the rest of the app is unaffected).
- **How sure is this:** the server half is tested end to end with a simulated
  calculator, and the page's USB code is checked byte for byte against the
  Python implementation (checksums, messages, note encoding, report framing)
  and run against a simulated G2 through the real panel (connect, sync both
  ways, confirm, cancel, auto-sync). It has **not been tried on a physical
  G2** - the PC tool's USB layer it is ported from hasn't either, and WebHID
  adds one more unknown: whether Chrome lists the G2 in its device chooser
  (it hides devices that look like keyboards or mice). If it doesn't appear,
  or a sync fails, the PC tool remains the fallback.

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

If you don't have Node installed, you can fetch the three required libraries
directly from the npm registry without `npm`:

```bash
curl -sL https://registry.npmjs.org/mathlive/latest -o /tmp/ml.json
# read .dist.tarball from that JSON, then:
curl -sL <tarball-url> -o mathlive.tgz && tar xzf mathlive.tgz
cp -r package/*.mjs package/*.js package/fonts frontend/lib/mathlive/
# same idea for mathjs, but its browser bundle lives at lib/browser/math.js
# inside the tarball, not dist/ — copy that file to frontend/lib/mathjs.min.js
# nerdamer ships its whole bundle (core + Calculus + Solve, etc) as one
# pre-built file at the package root, all.min.js - copy that straight to
# frontend/lib/nerdamer/nerdamer.all.min.js
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
