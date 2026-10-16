# CalcVault for the HP Prime G2

The CalcVault calculators, on the calculator: the same folders, the same
Eq / Input / Output lines, Locked and Unlocked views, d/dx and ∫dx. A PC
program syncs it with the web app over USB.

```
calc/CALCVAULT.txt      the calculator app (HP PPL source)
calc/CalcVault.hpappdir the app, ready to drag onto the calculator
calc/CALCVAULT.hpprgm   the same as a plain program, if you prefer
calc/build.py           builds both from the source
sync/                   the PC sync tool (Python 3.8+, plus hidapi for USB)
dev/                    development aids: emulator driver, probes, checks
```

## Putting the app on the calculator

Drag the **`calc/CalcVault.hpappdir` folder** (the whole folder) onto your
calculator in HP's Connectivity Kit, under *Calculators*, not *Content*. It
then appears on the **Apps** screen with its own icon; select it and press
**Enter** (or tap **Start**).

If you would rather run it as a program, drag `calc/CALCVAULT.hpprgm`
instead and run it by typing `CALCVAULT` on Home. Either one works with the
same data; you only need one of them.

Both are built from `calc/CALCVAULT.txt` by `python calc/build.py` (needs
hp-prime-kit, see below).

## Using it on the calculator

**Folders and calculators.** ▲▼ to move, **Enter** (or touch the selected
row) to open, **Esc** to go up. Soft keys: Open, New, Name, Move, Del, Exit.

**A calculator.** Each line shows its text with its value under it.

| Key | Does |
|---|---|
| Enter / Edit | edit the line |
| + / +Line | add an Eq, Input or Output line below |
| Del | delete the line |
| Lock / Unlck | switch between the editing view and the clean view |
| Menu (key or soft key) | d/dx, ∫dx, move line up/down, hide when locked, change role, exact/decimal, rename, on-screen keyboard on/off |
| Esc / Back | back to the folder |

**Locked calculators.** Touch an Input's box and type straight into it; the
results update when you press **Enter**, tap **OK**, or touch anywhere else
(which also does whatever you touched, such as starting on the next box).

**Typing.** Text is edited in CalcVault's own editor, with an on-screen
keyboard: letters (**ABC** switches case), digits, operators, and an **fn**
page of functions, Greek letters and comparisons. **Hide**/**Keys** on the
bottom row, or Settings/Menu, turns the keyboard off or on (remembered).
The calculator's own keys work too:

- digits, `+ - × ÷ ^ ( ) .`, SIN COS TAN LN LOG, and **x t θ n** for `x`
- **Units** types `_`, for names like `X_1`
- **ALPHA** then a key types a capital letter (it stays on until pressed
  again); **Shift ALPHA** for small letters
- ◄ ► move the cursor, **Del** deletes, **Enter** accepts, **Esc** cancels

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
- **CVSET**: the keyboard setting. **CVBAK**: a backup the app makes before
  converting old data or when CVDATA cannot be read.

A calculator whose note cannot be read shows a message and is left as it
is, never saved over. Data from older versions (everything in CVDATA) is
converted the first time the new app or sync tool sees it.

Because of this split, a sync reads the index and only the calculators
whose counter changed, and writes only what differs: usually a few hundred
bytes instead of the whole vault. Each note is read back after writing and
sent again if it did not arrive intact.

## Syncing with the web app

Close HP's Connectivity Kit on the PC (it holds the USB connection), plug
the calculator in and turn it on. Then either:

- **Live:** double-click `sync/Live Sync CalcVault.bat` (or
  `python -m cvsync live` from `sync/`) and leave the window open. Every
  change on the calculator or the web app is copied across within a few
  seconds, and it picks the calculator up again when you plug it back in.
- **Once:** double-click `sync/Sync CalcVault.bat` (or `python -m cvsync sync`).

**Close CalcVault on the calculator for a sync.** A G2 does not answer file
requests over USB while a program is running, so live sync copies your
calculator changes each time you leave CalcVault. (If a PC write does reach
an open CalcVault, the app reloads, and an edit made at that very moment is
dropped with a message rather than written over the PC's data.)

**Connect by cable.** Over USB-over-network (VirtualHere through a VPN)
the calculator's replies were mostly lost: the protocol has no
retransmission. Run the sync on the computer the calculator is plugged into
instead; see Linux below.

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

- **The app** was run in HP's Virtual Calculator (2.4, build 2025-09-15):
  creating folders and calculators, every line role, lock mode, d/dx, the
  CAS evaluation of everything the converter writes, saving and reloading.
  Not yet on a physical G2.
- **The sync logic** is tested against a real CalcVault backend
  (`sync/tests/test_sync_live.py`) and the Virtual Calculator's folder.
- **The math conversion** was checked against the web app's own MathLive +
  math.js: 44 expressions evaluate to the same number on both sides
  (`dev/mlcheck.py`).
- **Live sync** is tested end to end against a real backend with a folder
  standing in for the calculator (`sync/tests/live_check.py`). Whether a
  physical G2 answers USB while a program is running is not known: if it
  does not, live sync still works, but picks up changes only while
  CalcVault is closed on the calculator.
- **USB** follows the protocol as measured on a G2 by Prime Connection Kit
  (github.com/56phil/prime_connection_kit), ported to Python and tested
  against a simulated calculator, but **not yet against a real one**. If it
  does not work, the fallback is `python -m cvsync sync --folder DIR` on a
  folder holding the calculator's CVDATA.hpnote (the Connectivity Kit
  mirrors it to `Documents\HP Connectivity Kit\Calculators\<name>`),
  then dragging the updated CVDATA.hpnote back onto the calculator in the
  Connectivity Kit.

## Tests

From `sync/`:

```bash
python -m unittest tests.test_mathconv tests.test_link_store
```

The live test needs a throwaway backend (it deletes everything on it); see
the top of `tests/test_sync_live.py`. The calculator app's pure functions
are checked with `python dev/pplcheck.py`, which needs
[hp-prime-kit](https://github.com/JordiRigau/hp-prime-kit) (set `HPK` to
its folder).
