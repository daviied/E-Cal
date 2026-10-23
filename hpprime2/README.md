# CalcVault 2 for the HP Prime G2

The CalcVault calculators, on the calculator: the same folders, the same
Eq / Input / Output lines, Locked and Unlocked views, d/dx and ∫dx. A PC
program syncs it with the web app over USB, and **online mode** turns the
calculator into a remote for the web app while it is plugged in.

This is the second version. The first, in `../hpprime`, is left as it was;
both read and write the same notes, so you can switch between them (or keep
both installed: this one is called **CalcVault2**).

**What is new in CalcVault 2.** The idea: type the wordy parts (names,
labels, roles) on the PC, and do the math on the calculator.

- **Enter makes a new Eq line.** While typing an Eq line, Enter saves it
  and opens a blank Eq line below it, so a column of equations is typed
  without leaving the keys. Enter on an empty one ends the run (and the
  empty line goes away). **OK** saves and stops. To change an existing
  line, select it and press Enter, or tap it twice.
- **New Eq lines start hidden when locked**, here and in the web app: the
  locked view shows the Inputs and Outputs, with the working out of sight.
  Eq lines that *do* show when locked carry a green **shown** tag in the
  unlocked view. (Menu > Show/hide when locked switches it per line.)
- **Variable palette.** Above the keyboard, a strip of the names the
  calculator defines (its Inputs, `a=...` lines, `f(x)=...` functions, and
  the shared lines below): tap one to type it. `>>` turns the page when
  they do not all fit. Tapped after a name or `)`, a `*` goes in between.
- **Global and folder lines reach the calculator.** The web app's shared
  lines are copied to the note **CVSHR** on every sync, and a calculator
  evaluates the global lines, then each enclosing folder's from the
  outermost in, then its own, exactly like the web app. They are edited on
  the web only (the calculator never writes them), and their names are in
  the palette.
- **Locked: Enter moves to the next Input box**, so a column of values is
  typed without touching the screen.
- **Back where you left off.** Leave CalcVault with a calculator open
  (the Home key) and it reopens that calculator next time.
- **Online mode** (below): stays in sync while CalcVault is open, shows
  **online** in its title bar, and opens what you open in the web app.

```
calc/CALCVAULT2.txt       the calculator app (HP PPL source)
calc/CalcVault2.hpappdir  the app, ready to drag onto the calculator
calc/CALCVAULT2.hpprgm    the same as a plain program, if you prefer
calc/build.py             builds both from the source
sync/                     the PC sync tool (Python 3.8+, plus hidapi for USB)
dev/                      development aids: emulator driver, probes, checks
```

## Putting the app on the calculator

Drag the **`calc/CalcVault2.hpappdir` folder** (the whole folder) onto your
calculator in HP's Connectivity Kit, under *Calculators*, not *Content*. It
then appears on the **Apps** screen with its own icon; select it and press
**Enter** (or tap **Start**).

If you would rather run it as a program, drag `calc/CALCVAULT2.hpprgm`
instead and run it by typing `CALCVAULT2` on Home. Either one works with the
same data; you only need one of them.

Both are built from `calc/CALCVAULT2.txt` by `python calc/build.py` (needs
hp-prime-kit, see below).

## Using it on the calculator

**Folders and calculators.** ▲▼ to move, **Enter** (or touch the selected
row) to open, **Esc** to go up. Soft keys: Open, New, Name, Move, Del, Exit.

**A calculator.** Each line shows its text with its value under it.

| Key | Does |
|---|---|
| Enter / Edit | edit the line (an empty calculator: start typing equations) |
| + / +Line | add an Eq, Input or Output line below |
| Del | delete the line |
| Lock / Unlck | switch between the editing view and the clean view |
| Menu (key or soft key) | d/dx, ∫dx, move line up/down, show/hide when locked, change role, exact/decimal, rename, Settings |
| Esc / Back | back to the folder |
| Home | leave CalcVault; it reopens this calculator next time |

**Settings** (Menu > Settings, or the Menu key in a folder):

- *On-screen keyboard*: on or off (also **Hide**/**Keys** while typing).
- *Let the PC sync while open*: on (the default) makes the app sleep a few
  milliseconds between key checks, so the calculator can answer the PC
  while CalcVault is open. Turn it off only if typing ever feels sluggish.
- *Follow the web app*: in online mode, open on the calculator whatever
  calculator you open in the web app.

**Locked calculators.** Touch an Input's box and type straight into it; the
results update when you press **Enter** (which moves on to the next Input),
tap **OK**, or touch anywhere else (which also does whatever you touched,
such as starting on another box).

**Typing.** Text is edited in CalcVault's own editor, with an on-screen
keyboard: letters (**ABC** switches case), digits, operators, and an **fn**
page of functions, Greek letters and comparisons, and the variable palette
above it. The calculator's own keys work too:

- digits, `+ - × ÷ ^ ( ) .`, SIN COS TAN LN LOG, and **x t θ n** for `x`
- **Units** types `_`, for names like `X_1`
- **ALPHA** then a key types a capital letter (it stays on until pressed
  again); **Shift ALPHA** for small letters
- ◄ ► move the cursor, **Del** deletes, **Enter** accepts (in an Eq line:
  accepts and starts the next one), **Esc** cancels

Lines are evaluated top to bottom in the calculator's CAS, like the web app
does with math.js: `a=5` defines `a`, `f(x)=x^2+1` defines a function, an
Input's variable is set to its value. Text is typed the calculator's way
(`sqrt(x)`, `x^2`, `when(x>=0,x^2,-x)` for the web app's `x ≥ 0 ? x² : -x`).
`log` is base 10 and `ln` natural, as on the web. Names may contain
underscores (`X_1`, `V_in`); the CAS would read some of them as units
(`V_s`, volts times seconds), so CalcVault hides the underscore from it.

Data is kept in notes, saved after every change:

- **CVDATA**: the index of folders and calculators (names, lock, and a
  change counter per calculator). Small, read when the app starts.
- **CVC1**, **CVC2**, …: one note per calculator, holding its lines, read
  when you open that calculator and rewritten only when you change it.
- **CVREV**: changes on every save, so the PC knows to sync.
- **CVSHR**: the web app's global and folder lines, written by the PC.
- **CVLINK**, **CVFOCUS**: online mode's heartbeat and "open this one".
- **CVSET**: the settings, and the calculator to reopen. **CVBAK**: a
  backup the app makes before converting old data or when CVDATA cannot be
  read.

A calculator whose note cannot be read shows a message and is left as it
is, never saved over. Data from older versions (everything in CVDATA) is
converted the first time the new app or sync tool sees it.

Because of this split, a sync reads the index and only the calculators
whose counter changed, and writes only what differs: usually a few hundred
bytes instead of the whole vault. Each note is read back after writing and
sent again if it did not arrive intact.

## Syncing with the web app

Close HP's Connectivity Kit on the PC (it holds the USB connection), plug
the calculator in and turn it on. Then one of:

- **Online, from the web app (nothing to install):** the **HP Prime**
  button in the web app's sidebar, then **Connect calculator** and switch
  **Online** on. See the next section.
- **Online, from the PC tool:** double-click `sync/Online CalcVault.bat`
  (or `python -m cvsync online` from `sync/`) and leave the window open.
- **Live:** double-click `sync/Live Sync CalcVault.bat` (or
  `python -m cvsync live`). Every change on the calculator or the web app
  is copied across within a few seconds.
- **Once:** double-click `sync/Sync CalcVault.bat` (or `python -m cvsync sync`).

If a PC write reaches an open CalcVault, the app reloads, and an edit made
at that very moment is dropped with a message rather than written over the
PC's data.

**Connect by cable.** Over USB-over-network (VirtualHere through a VPN)
the calculator's replies were mostly lost: the protocol has no
retransmission. Run the sync on the computer the calculator is plugged into
instead; see Linux below.

### Online mode

The calculator as a remote for the web app: build calculators on the PC
(names, labels, roles, long formulas), and use them on the calculator,
which keeps working on its own copy when unplugged (that is the offline
mode: nothing to switch, just unplug).

**From the web app**, in Chrome or Edge on the computer the calculator is
plugged into (the page talks to the calculator over USB itself, through
WebHID, so there is nothing to install):

1. Close HP's Connectivity Kit, plug the calculator in, turn it on.
2. In the web app: **HP Prime** (sidebar) > **Connect calculator**, pick the
   HP Prime in the browser's list (once; the browser remembers it).
3. Switch **Online** on, and open CalcVault 2 on the calculator.

Online stays on for that browser: from then on, opening the web app with
the calculator plugged in is enough, and the sidebar button reads
**HP Prime: online** (or **waiting** while the calculator does not answer).
Keep the page open; it can be in a background tab. Only one tab runs it.
The page needs HTTPS (or localhost), which a server behind your reverse
proxy has.

**From the PC tool** instead: `Online CalcVault.bat` does the same from a
console window, for a browser without WebHID. Use one or the other.

Either way, while it runs and the calculator is plugged in with CalcVault 2
open:

- Changes on either side are copied across within a second or two.
- The calculator's title bar shows a green **online** badge (the page or
  the PC tool writes a heartbeat every few seconds; the badge goes after
  about 12 s without).
- Opening a calculator in the web app opens it on the calculator too
  (Settings > Follow the web app).

**The one thing not yet known.** The first version found that a G2 does not
answer USB while a program is running: it was measured with CalcVault
checking the keys flat out. CalcVault 2 sleeps briefly between checks
(Settings > Let the PC sync while open) so the calculator can get to its
USB; whether a real G2 then answers has not been tried yet. To find out,
with CalcVault 2 open on the calculator:

```
cd sync
python tests/open_probe.py
```

It asks the calculator for a note once a second and prints whether it
answered (it only reads). Without Python: switch Online on in the web app
and open CalcVault 2 on the calculator; the sidebar button says **HP Prime:
online** when it answers, **waiting** when it does not. If it answers, online mode works as described. If
it does not, online mode still works but only syncs while CalcVault is
closed: leave CalcVault with the Home key, wait for the PC window to say
"synced", and reopen it (it comes back to the same calculator). The other
way around a firmware limit is a USB host link instead of the PC's: the
calculator's `USBOpen`/`USBSend`/`USBRecv` commands talk to a device
plugged *into* the calculator, which is what `../../calcvault-pi` (a
Raspberry Pi Zero 2 W on an OTG cable, with its own Wi-Fi) is built on.

### Linux (Mint, Ubuntu, Debian)

Copy the `hpprime/sync` folder to the Linux machine, then:

```bash
cd sync/linux
bash install.sh
```

It installs the tool in `~/.local/share/calcvault-sync` with its own Python
environment, adds the commands `calcvault-sync` and `calcvault-live` and
two menu entries (CalcVault Sync, CalcVault Live Sync), and adds a udev rule
(`/etc/udev/rules.d/70-hp-prime.rules`, asks for your password) so your
user can reach the calculator over USB. Then unplug and replug the
calculator and:

```bash
calcvault-sync login     # once: web address and password
calcvault-sync           # one sync
calcvault-live           # live sync; leave it running
calcvault-sync online    # online mode; leave it running
```

`bash install.sh --service` also runs live sync in the background at every
login (log in first; follow it with `journalctl --user -u calcvault-live -f`).
`bash install.sh --remove` takes it all out. Settings and backups are in
`~/.config/CalcVaultSync`.

The first run asks for the web app's address and password. The address is
remembered; the password is not stored, only the 30-day session cookie the
app hands out.

What a sync does:

- Changed on one side only: copied to the other.
- Changed on both sides: the web app's version wins, and the calculator's is
  kept as a new calculator named "… (calculator copy)". Nothing is lost.
- Deleted on one side and unchanged on the other: deleted on both. Deleted on
  one side but changed on the other: kept.
- A one-off sync shows the plan and asks before anything is deleted or a
  conflict is resolved. `--dry-run` shows the plan and changes nothing;
  `--yes` does not ask. Live sync does not ask; the backups below are its
  safety net.
- Every sync first saves the calculator's CVDATA, and the web app's data if
  it is about to change, under `%APPDATA%\CalcVaultSync\backups`.
- After writing to the calculator it reads the note back and compares.

Only lines that changed are converted between LaTeX and calculator text; an
untouched line keeps its exact LaTeX on the web and its exact text on the
calculator.

`python -m cvsync status` shows what is configured and whether a calculator
is attached. `--emulator` syncs HP's Virtual Calculator instead (close it
first).

### Conversion notes

- A multi-letter name only exists in the web app as a subscripted one, so a
  calculator name like `Vin` reaches the web app as `V_{in}`. Write it
  `V_in` on the calculator to keep it the same on both.
- Greek names: `θ` on the calculator is `\theta` (math.js: `theta`) on the web.
- An nth root goes to the web as a power (`x^{1/3}`) and `logb(x,b)` as
  `ln(x)/ln(b)`, because the web app's math.js cannot evaluate MathLive's
  `\sqrt[n]{}` or `\log_b`.
- `arcsin`, `arccos` and `arctan` work on the calculator but not in the web
  app (math.js calls them `asin`/`acos`/`atan`, and MathLive writes
  `arcsin`); that is a gap in the web app, not in the sync.
- `\begin{cases}` does not evaluate in the web app and is not converted.

## How sure is this

- **CalcVault 2 on the calculator** was run in HP's Virtual Calculator
  (2.4, build 2025-09-15) on a test vault (`dev/seed_emu.py --program`):
  shared lines evaluated in a calculator (a folder's Input and a global
  line feeding its own lines), the variable palette and tapping a name in,
  Enter saving an Eq line and opening the next, Enter on an empty one
  ending the run, new lines hidden when locked, the locked view and Enter
  in an Input, Settings, and reopening the last calculator. Not yet on a
  physical G2. The `online` badge and following the web app need a PC
  writing notes while the app runs, which the emulator cannot do, so they
  are checked only on the PC side (next point).
- **Online mode, PC side** is tested end to end against a real backend with
  a folder standing in for the calculator (`sync/tests/online_check.py`):
  heartbeat, focus, shared lines and their edits, edits both ways.
- **Online mode in the web app** was run in a browser against a real
  backend and a simulated G2 (`dev/fakeg2.js`, a stand-in WebHID device
  speaking the link protocol): first sync with shared lines, heartbeat,
  opening a calculator on the page sending it to the calculator, a save on
  the calculator reaching the web app (2 s) and a web edit reaching the
  calculator (3 s), and a calculator that stops answering and comes back.
  Whether Chrome lists a real G2 in its device chooser is the same unknown
  as for the web app's sync panel.
- **Online mode with CalcVault open on a real G2** is the open question:
  see "The one thing not yet known" above, and `sync/tests/open_probe.py`.
- **The sync logic** is tested against a real CalcVault backend
  (`sync/tests/test_sync_live.py`), and the shared-lines note by
  `sync/tests/test_shared.py`.
- **The math conversion** was checked against the web app's own MathLive +
  math.js: 44 expressions evaluate to the same number on both sides
  (`dev/mlcheck.py`).
- **USB** follows the protocol as measured on a G2 by Prime Connection Kit
  (github.com/56phil/prime_connection_kit), ported to Python. Syncing a
  real G2 has worked, though not reliably: requests sometimes stall or time
  out, which the sync retries but which online mode, writing every few
  seconds, will meet more often. If USB does not work at all, the fallback
  is `python -m cvsync sync --folder DIR` on a folder holding the
  calculator's CVDATA.hpnote (the Connectivity Kit mirrors it to
  `Documents\HP Connectivity Kit\Calculators\<name>`), then dragging the
  updated CVDATA.hpnote back onto the calculator in the Connectivity Kit.

## Tests

From `sync/`:

```bash
python -m unittest tests.test_mathconv tests.test_link_store tests.test_shared
```

The live tests need a throwaway backend (they delete everything on it); see
the top of `tests/test_sync_live.py`, then `tests/live_check.py` and
`tests/online_check.py` take its address and password. The calculator
app's pure functions are checked with `python dev/pplcheck.py`, which
needs [hp-prime-kit](https://github.com/JordiRigau/hp-prime-kit) (set
`HPK` to its folder). In the 2.4 emulator, notes copied into its folder
are not loaded, so `dev/seed_emu.py --program` writes a program that makes
the test vault on the calculator itself.
