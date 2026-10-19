<#
.SYNOPSIS
  Spike: can the existing Windows build ship as an MSIX?

.DESCRIPTION
  Answers a feasibility question, not a release one. It takes an MSI the
  pipeline already produced, unpacks it with an administrative install (which
  yields exactly the installed layout), wraps that layout in an MSIX with a
  full-trust manifest, signs it with a throwaway self-signed certificate,
  installs it, and then checks the things that could plausibly break:

    - path length: the package lands under C:\Program Files\WindowsApps\<long
      name>, and the PyInstaller tree under it is deep;
    - the engine sidecar running from the read-only package directory;
    - the engine running *inside* the package context, where writes to AppData
      are redirected - which is the case the window actually produces;
    - the window starting and spawning its engine.

  Every check records a result and the script carries on, so one run reports
  everything; it exits non-zero at the end if any check failed.

  The Store would sign the package itself and assign the real Identity Name
  and Publisher. Nothing here is what a submission would use.
#>
param(
  [Parameter(Mandatory)] [string] $Source,
  [Parameter(Mandatory)] [string] $Out
)

$ErrorActionPreference = 'Stop'
$results = [System.Collections.Generic.List[object]]::new()
function Record($name, $ok, $detail) {
  $results.Add([pscustomobject]@{ Check = $name; Ok = $ok; Detail = $detail })
  $mark = if ($ok) { 'PASS' } else { 'FAIL' }
  Write-Host "[$mark] $name - $detail"
}

$Out = (New-Item -ItemType Directory -Force -Path $Out).FullName
$work = Join-Path $env:RUNNER_TEMP 'msix-spike'
New-Item -ItemType Directory -Force -Path $work | Out-Null

# -- 1. unpack the MSI ---------------------------------------------------------
$msi = Get-ChildItem -Recurse -Path $Source -Filter *.msi | Select-Object -First 1
if (-not $msi) { throw "no .msi under $Source" }
Write-Host "MSI: $($msi.FullName) ($([math]::Round($msi.Length / 1MB)) MB)"

$admin = Join-Path $work 'admin'
$p = Start-Process msiexec.exe -Wait -PassThru -ArgumentList @(
  '/a', "`"$($msi.FullName)`"", '/qn', "TARGETDIR=`"$admin`"")
if ($p.ExitCode -ne 0) { throw "msiexec /a exited $($p.ExitCode)" }

$exe = Get-ChildItem -Recurse -Path $admin -Filter FreeDocs.exe | Select-Object -First 1
if (-not $exe) { $exe = Get-ChildItem -Recurse -Path $admin -Filter app.exe | Select-Object -First 1 }
if (-not $exe) { throw 'no application executable in the unpacked MSI' }
Write-Host "Application: $($exe.FullName)"

$stage = Join-Path $work 'stage'
Copy-Item -Recurse -Path $exe.Directory.FullName -Destination $stage
Get-ChildItem -Path $stage -Filter *.msi | Remove-Item

# The version the MSI carries, as MSIX wants it: four numeric parts. The Store
# reserves the fourth for itself and requires it to be 0.
$version = (Get-Item (Join-Path $stage $exe.Name)).VersionInfo.ProductVersion
$parts = @(($version -split '[^0-9]+') | Where-Object { $_ -ne '' } | Select-Object -First 3)
while ($parts.Count -lt 3) { $parts += '0' }
$msixVersion = ($parts -join '.') + '.0'
Write-Host "Version: $version -> $msixVersion"

# -- 2. path length --------------------------------------------------------------
# Name_Version_Arch__PublisherHash; the hash is always 13 characters.
$identity = 'Realise.FreeDocs'
$prefix = "C:\Program Files\WindowsApps\${identity}_${msixVersion}_x64__abcdefghjkmnp\"
$longest = Get-ChildItem -Recurse -File -Path $stage |
  ForEach-Object { $_.FullName.Substring($stage.Length + 1) } |
  Sort-Object Length -Descending | Select-Object -First 1
$installed = $prefix.Length + $longest.Length
Record 'Path length under WindowsApps' ($installed -lt 260) "$installed characters for $longest"

# -- 3. manifest and assets ------------------------------------------------------
$assets = Join-Path $stage 'Assets'
New-Item -ItemType Directory -Force -Path $assets | Out-Null
$icons = Join-Path $PSScriptRoot '..\src-tauri\icons'
foreach ($name in 'StoreLogo.png', 'Square150x150Logo.png', 'Square44x44Logo.png') {
  Copy-Item (Join-Path $icons $name) $assets
}

$publisher = 'CN=FreeDocs MSIX Spike'
@"
<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
         xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
         xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
         IgnorableNamespaces="uap rescap">
  <Identity Name="$identity" Publisher="$publisher" Version="$msixVersion" ProcessorArchitecture="x64" />
  <Properties>
    <DisplayName>FreeDocs</DisplayName>
    <PublisherDisplayName>Realise</PublisherDisplayName>
    <Logo>Assets\StoreLogo.png</Logo>
  </Properties>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.17763.0" MaxVersionTested="10.0.26100.0" />
  </Dependencies>
  <Resources>
    <Resource Language="en-us" />
  </Resources>
  <Applications>
    <Application Id="FreeDocs" Executable="$($exe.Name)" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements DisplayName="FreeDocs"
                          Description="Remove confidential data from documents, locally"
                          BackgroundColor="transparent"
                          Square150x150Logo="Assets\Square150x150Logo.png"
                          Square44x44Logo="Assets\Square44x44Logo.png" />
    </Application>
  </Applications>
  <Capabilities>
    <rescap:Capability Name="runFullTrust" />
  </Capabilities>
</Package>
"@ | Set-Content -Encoding utf8 -Path (Join-Path $stage 'AppxManifest.xml')

# -- 4. pack and sign ------------------------------------------------------------
$kit = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\makeappx.exe" |
  Sort-Object FullName | Select-Object -Last 1
$makeappx = $kit.FullName
$signtool = Join-Path $kit.DirectoryName 'signtool.exe'
$package = Join-Path $Out "FreeDocs_${msixVersion}_x64.msix"

$started = Get-Date
& $makeappx pack /o /d $stage /p $package | Select-Object -Last 5
Record 'makeappx pack' ($LASTEXITCODE -eq 0 -and (Test-Path $package)) `
  ("exit $LASTEXITCODE in {0:N0}s" -f ((Get-Date) - $started).TotalSeconds)
if (-not (Test-Path $package)) { $results | Format-Table -AutoSize; exit 1 }
$msixMB = [math]::Round((Get-Item $package).Length / 1MB)
Record 'Package size' $true "MSIX $msixMB MB, MSI $([math]::Round($msi.Length / 1MB)) MB"

$cert = New-SelfSignedCertificate -Type Custom -Subject $publisher `
  -KeyUsage DigitalSignature -FriendlyName 'FreeDocs MSIX spike' `
  -CertStoreLocation 'Cert:\CurrentUser\My' `
  -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3', '2.5.29.19={text}')
& $signtool sign /fd SHA256 /sha1 $cert.Thumbprint $package | Select-Object -Last 3
Record 'signtool sign' ($LASTEXITCODE -eq 0) "exit $LASTEXITCODE"
$cer = Join-Path $Out 'FreeDocs-test.cer'
Export-Certificate -Cert $cert -FilePath $cer | Out-Null
Import-Certificate -FilePath $cer -CertStoreLocation 'Cert:\LocalMachine\TrustedPeople' | Out-Null

# For installing this exact package on a real machine. The private key never
# leaves this runner and dies with it, so trusting the .cer lets this package
# install and nothing else can be signed with it afterwards.
@'
# Run in an elevated PowerShell, from the folder holding these files.
# 1. Trust the throwaway certificate this test package was signed with.
Import-Certificate -FilePath .\FreeDocs-test.cer -CertStoreLocation Cert:\LocalMachine\TrustedPeople
# 2. Install.
Add-AppxPackage -Path (Get-ChildItem .\FreeDocs_*.msix | Select-Object -First 1).FullName
# Afterwards, to undo both:
#   Get-AppxPackage Realise.FreeDocs | Remove-AppxPackage
#   Get-ChildItem Cert:\LocalMachine\TrustedPeople | Where-Object Subject -eq 'CN=FreeDocs MSIX Spike' | Remove-Item
'@ | Set-Content -Encoding utf8 -Path (Join-Path $Out 'install-test.ps1')

# -- 5. install ------------------------------------------------------------------
try {
  Add-AppxPackage -Path $package
  $pkg = Get-AppxPackage -Name $identity
  Record 'Add-AppxPackage' ($null -ne $pkg) $pkg.InstallLocation
} catch {
  Record 'Add-AppxPackage' $false $_.Exception.Message
  $results | Format-Table -AutoSize -Wrap
  exit 1
}
$pfn = $pkg.PackageFamilyName
$engine = Join-Path $pkg.InstallLocation 'freedocs-engine\freedocs-engine.exe'
Record 'Engine present in package' (Test-Path $engine) $engine

# -- 6. the engine, outside and inside the package context -----------------------
$sample = Join-Path $work 'campione.txt'
'Il contratto e firmato da Mario Rossi, residente in Via Nassa 5, 6900 Lugano.' |
  Set-Content -Encoding utf8 -Path $sample
$requests = Join-Path $work 'requests.jsonl'
@(
  (@{ jsonrpc = '2.0'; id = 1; method = 'capabilities' } | ConvertTo-Json -Compress),
  (@{ jsonrpc = '2.0'; id = 2; method = 'inspect'; params = @{ path = $sample } } | ConvertTo-Json -Compress)
) | Set-Content -Encoding utf8NoBOM -Path $requests

function Read-Engine($path) {
  $lines = @(Get-Content -Path $path -ErrorAction SilentlyContinue | Where-Object { $_.Trim() })
  $formats = @(); $entities = @(); $errors = @(); $ocr = $null
  foreach ($line in $lines) {
    try { $m = $line | ConvertFrom-Json } catch { continue }
    if ($m.error) { $errors += $m.error.message }
    $payload = if ($m.result) { $m.result } else { $m.params }
    if ($payload.formats) { $formats += $payload.formats }
    if ($null -ne $payload.ocr_available) { $ocr = $payload.ocr_available }
    if ($payload.findings) { $entities += $payload.findings | ForEach-Object { $_.entity } }
  }
  [pscustomobject]@{
    Formats = ($formats | Sort-Object -Unique) -join ' '
    Entities = ($entities | Sort-Object -Unique) -join ' '
    Errors = $errors -join '; '
    Ocr = $ocr
  }
}

# Outside the package context Windows refuses to start anything under
# WindowsApps - measured on the first run: `Access is denied.` and no output.
# That is the platform, not the package, and it is why the CLI cannot be reached
# from an MSIX install without an execution alias. Asserted, so a change in it
# is noticed.
$direct = Join-Path $work 'direct.jsonl'
cmd /c "type `"$requests`" | `"$engine`" > `"$direct`" 2> `"$direct.err`""
$denied = (Get-Content "$direct.err" -Raw -ErrorAction SilentlyContinue) -match 'Access is denied'
Record 'Direct launch from WindowsApps is refused' $denied `
  ((Get-Content "$direct.err" -Raw -ErrorAction SilentlyContinue) -replace "`r?`n", ' ')

# Inside the package context: AppData writes are redirected here, which is the
# environment the window's own sidecar runs in. Invoke-CommandInDesktopPackage
# returns at once, so the output file is polled.
$inside = Join-Path $work 'inside.jsonl'
try {
  # The window hands its sidecar the bundled Tesseract through
  # FREEDOCS_TESSERACT (`portable_env` in engine.rs); this does the same, so the
  # OCR answer below is the one the window would get.
  $tesseract = Join-Path $pkg.InstallLocation 'bin\tesseract.exe'
  $setOcr = if (Test-Path $tesseract) { "set `"FREEDOCS_TESSERACT=$tesseract`"&& " } else { '' }
  Invoke-CommandInDesktopPackage -PackageFamilyName $pfn -AppId 'FreeDocs' -Command 'cmd.exe' `
    -Args "/c $setOcr type `"$requests`" | `"$engine`" > `"$inside`" 2> `"$inside.err`"" -PreventBreakaway
  $deadline = (Get-Date).AddMinutes(10)
  do {
    Start-Sleep -Seconds 5
    $r = Read-Engine $inside
  } until (($r.Entities -match 'PERSON') -or $r.Errors -or (Get-Date) -gt $deadline)
  Record 'Engine run inside the package context' ($r.Entities -match 'PERSON') `
    ("formats [{0}]; entities [{1}] {2}" -f $r.Formats, $r.Entities, $r.Errors)
  if (Test-Path $tesseract) {
    Record 'Bundled Tesseract usable from the package' ($r.Ocr -eq $true) "ocr_available = $($r.Ocr)"
  } else {
    Record 'Bundled Tesseract usable from the package' $true 'not in this build (before 1.2.0-dev.4); skipped'
  }
} catch {
  Record 'Engine run inside the package context' $false $_.Exception.Message
}

# -- 7. the window ---------------------------------------------------------------
try {
  Start-Process "shell:AppsFolder\$pfn!FreeDocs"
  Start-Sleep -Seconds 45
  $app = Get-Process -Name ($exe.BaseName) -ErrorAction SilentlyContinue | Select-Object -First 1
  $sidecar = Get-Process -Name 'freedocs-engine' -ErrorAction SilentlyContinue | Select-Object -First 1
  Record 'Window process running' ($null -ne $app) ($app.Path)
  Record 'Window spawned its engine' ($null -ne $sidecar) ($sidecar.Path)
} catch {
  Record 'Window launch' $false $_.Exception.Message
}

# Where the package's redirected writes ended up (WebView2 profile, localStorage).
$private = Join-Path $env:LOCALAPPDATA "Packages\$pfn"
$listing = if (Test-Path $private) {
  (Get-ChildItem -Recurse -Depth 3 -Directory $private | ForEach-Object { $_.FullName.Substring($private.Length) }) -join "`n"
} else { '(none)' }
$listing | Set-Content -Path (Join-Path $Out 'package-private-dirs.txt')
Copy-Item -Path "$direct*", "$inside*" -Destination $Out -ErrorAction SilentlyContinue

# -- 8. uninstall ----------------------------------------------------------------
Get-Process -Name ($exe.BaseName), 'freedocs-engine' -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 3
try {
  Remove-AppxPackage -Package $pkg.PackageFullName
  Record 'Remove-AppxPackage' ($null -eq (Get-AppxPackage -Name $identity)) 'removed'
} catch {
  Record 'Remove-AppxPackage' $false $_.Exception.Message
}

# -- report ----------------------------------------------------------------------
$results | Format-Table -AutoSize -Wrap
if ($env:GITHUB_STEP_SUMMARY) {
  $md = @('| Check | Result | Detail |', '|---|---|---|')
  $md += $results | ForEach-Object {
    "| $($_.Check) | $(if ($_.Ok) { 'PASS' } else { 'FAIL' }) | $($_.Detail -replace '\|', '/' -replace "`r?`n", ' ') |"
  }
  $md | Add-Content -Path $env:GITHUB_STEP_SUMMARY
}
if ($results | Where-Object { -not $_.Ok }) { exit 1 }
# Explicit: the runner's pwsh wrapper exits with the last $LASTEXITCODE, which
# is the refused direct launch above - the expected outcome, read as a failure.
exit 0
