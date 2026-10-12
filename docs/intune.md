# Deploying with Intune

FreeDocs ships a per-machine `.msi`, and that is what an organisation deploys:
wrapped as a **Win32 app**, installed as SYSTEM, detected by its product code.
`app/packaging/intune.py` does the wrapping and prints the settings the portal
asks for. Nothing here is specific to one organisation.

```powershell
# on the Windows machine that built the .msi, from a release checkout
python app\packaging\intune.py --tool C:\Tools\IntuneWinAppUtil.exe
# -> app\dist-intune\FreeDocs_0.2.0_x64_en-US.intunewin
# -> app\dist-intune\FreeDocs_0.2.0_x64_en-US.intune.json   (the settings sheet)
```

**Not yet done end to end.** The script's checks are tested on macOS, and its
PowerShell parses there; reading a real MSI, running `IntuneWinAppUtil` and
installing through Intune have not happened yet. The first pilot fills in the
table at the bottom.

## Why these choices

**MSI, not the NSIS `-setup.exe`.** Tauri's NSIS installer installs for the
current user by default, and Intune runs installers as SYSTEM — so the app would
land in the SYSTEM profile, where nobody can launch it. The MSI installs under
Program Files for every user. The NSIS installer is left as it is, because that
default is right for somebody installing it on their own machine.

**Win32 app, not a line-of-business MSI.** A Win32 app can declare Tesseract as a
dependency, replace the previous version through supersedence, and use a custom
detection rule if the MSI one ever stops being enough. A line-of-business app
can do none of that.

**The upgrade code is pinned.** `bundle.windows.wix.upgradeCode` in
`tauri.conf.json` is what makes Windows treat 0.3.0 as an upgrade of 0.2.0 rather
than a second product beside it. Tauri used to derive it from `productName`, so
renaming the product would have silently forked every installation. The pinned
value is exactly the value Tauri derived (`tauri inspect wix-upgrade-code`), so
an MSI built from `v0.2.0`, before the pin, is the same product.

**Unsigned.** Nothing in this project is signed (see [packaging](packaging.md)).
Intune does not require a signature for a Win32 app, and an app installed by the
Intune Management Extension carries no mark of the web, so SmartScreen does not
appear. What *can* refuse it is a tenant policy: WDAC, Smart App Control, or the
Defender ASR rule that blocks executables by prevalence. The sidecar is several
hundred unsigned DLLs, so check on the pilot machine before rolling out.

## 1. A release version

WiX accepts only a numeric `X.Y.Z`, and `develop` always carries `-dev.N`. Build
from `main` or a `v*` tag; see [gitflow](gitflow.md). The script refuses a
development version even if an older `.msi` happens to be lying in `target/`.

## 2. The MSI

On a Windows machine prepared as in [building](building.md#windows-11):

```powershell
git checkout v0.2.0
cd engine
uv sync --extra pdf --extra ooxml --extra ner --extra restore
uv run --with pyinstaller python packaging/build.py    # sidecar, plus a smoke test that loads the model
cd ..\app
npm ci
$env:CI = "true"; npm run tauri build -- --bundles msi
```

The `.msi` lands in `app\src-tauri\target\release\bundle\msi\`.

## 3. The package

`IntuneWinAppUtil.exe` is Microsoft's Content Prep Tool
(github.com/microsoft/Microsoft-Win32-Content-Prep-Tool). The script never
downloads it; pass `--tool`, set `INTUNEWINAPPUTIL`, or put it on `PATH`.

```powershell
python app\packaging\intune.py --check-only     # verify the MSI and print the settings
python app\packaging\intune.py --tool ...        # ... and write the .intunewin
```

Before packaging it reads the MSI's own Property table and refuses one whose
`ProductVersion` is not this tree's version or whose `UpgradeCode` is not the
pinned one. It stages the MSI alone, because `IntuneWinAppUtil` packs the whole
folder it is given and anything else in it would be installed on every machine.

## 4. The portal

Apps → Windows → Add → **Windows app (Win32)**, upload the `.intunewin`. Intune
reads the MSI inside and pre-fills most of this; compare it against the
`.intune.json` the script wrote.

| Field | Value |
|---|---|
| Install command | `msiexec /i "FreeDocs_<version>_x64_en-US.msi" /qn /norestart` |
| Uninstall command | `msiexec /x {ProductCode} /qn /norestart` |
| Install behavior | System |
| Return codes | Intune's defaults: 0, 1707 success; 3010 soft reboot; 1641 hard reboot; 1618 retry |
| Requirements | x64, Windows 10 1809 or later (WebView2's floor) |
| Detection | MSI, the product code; no version check |
| Dependencies | optional: Tesseract, see below |

**A new version** is a new app that supersedes the previous one. Leave
*Uninstall previous version* off: the MSI's own upgrade, keyed on the pinned
upgrade code, removes the old version, and an uninstall first would be a second
mechanism doing the same job.

## What happens on the user's machine

- The app installs under Program Files, about 1.1 GB.
- **The first document downloads the NER model**, about 1.2 GB, from Hugging Face
  into the user's own cache (`%USERPROFILE%\.cache\huggingface`). Once per user,
  not per machine. This needs `huggingface.co` reachable; it is the one outbound
  call the engine permits, see `core/egress.py`. On a machine several people
  share, or one with no route to Hugging Face, the weights can be placed once in a
  shared directory and named by a machine-wide `FREEDOCS_NER_MODEL` — the same
  mechanism the [portable](portable.md) bundle uses. That is a second Win32 app
  and not built here.
- **WebView2** is part of Windows 11. On Windows 10 without it, the MSI fetches
  Microsoft's bootstrapper, which needs the network at install time.
- **OCR for scanned PDFs** needs the Tesseract binary, which is never bundled.
  The language data is already inside the sidecar. Deploy the UB Mannheim
  installer as its own Win32 app (silent: `/S`) and make it a dependency; the
  engine looks in `C:\Program Files\Tesseract-OCR\` without being told. Without
  it everything except scans works, and the window says why scans do not.

## What the pilot has to confirm

| Claim | How to check | Result |
|---|---|---|
| The MSI installs per machine | `C:\Program Files\FreeDocs\` exists after an Intune install | not yet checked |
| `intune.py` reads a real MSI | `--check-only` prints a product code | not yet checked |
| The package installs silently as SYSTEM | Company Portal or the IME log shows success | not yet checked |
| A standard user can launch it | Start menu, as a non-admin | not yet checked |
| The model downloads through the network in use | the first scrub finds a name | not yet checked |
| No tenant policy blocks the unsigned sidecar | the first scrub finds a name | not yet checked |
| An upgrade replaces rather than duplicates | install 0.2.0, then the next version; one entry in Apps | not yet checked |

Record the outcome in [building](building.md) as well, which is where the first
Windows launch of any kind belongs.
