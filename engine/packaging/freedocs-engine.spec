# PyInstaller spec for the engine sidecar the desktop app spawns.
#
# One-dir, not one-file. A one-file build unpacks the whole bundle to a temporary
# directory on every launch, and this bundle contains torch — half a gigabyte of
# shared libraries. That is several seconds of startup per run, every run. The
# directory is shipped as a Tauri resource instead and the executable inside it is
# spawned by path, which costs a little Rust and saves all of that.
#
# Built per platform on the platform: PyInstaller does not cross-compile. See
# .github/workflows/app.yml for the matrix that produces all three.
#
# Deliberately *not* bundled:
#   - the NER model weights (~1.2 GB), fetched to the user's Hugging Face cache on
#     first use, because an installer that size is not an installer
#   - Tesseract and its language data, which are a system package and a download
#
# Both absences are already handled: the engine reports what it cannot do through
# `capabilities`, so the app can say so rather than failing mysteriously.

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# PyInstaller resolves a spec's script path relative to the spec file, and pathex
# relative to the working directory. Deriving both from SPECPATH, which PyInstaller
# injects, makes the build independent of where it was invoked from.
ENGINE_DIR = os.path.dirname(SPECPATH)  # noqa: F821 - injected by PyInstaller

# Imported lazily by the engine, so PyInstaller's static analysis cannot see them.
# Missing any of these produces a binary that works until the user opens that
# format, which is the worst time to find out.
hidden = [
    "freedocs.detect.backends.gliner_backend",
    "freedocs.detect.backends.presidio_backend",
    "freedocs.formats.ooxml.docx",
    "freedocs.formats.ooxml.xlsx",
    "freedocs.formats.ooxml.pptx",
    "pymupdf",
    "lxml.etree",
    "lxml._elementpath",
]

# The model stack. gliner_backend imports gliner2 *inside a function*, so listing
# the backend module is not enough: PyInstaller follows imports, and an import that
# only happens at call time is invisible to it. Leaving these out produced a bundle
# that reported the NER layer as present and then failed the moment a document
# needed it — which the build's smoke test now catches.
for package in ("gliner2", "torch", "transformers", "tokenizers", "safetensors"):
    try:
        hidden += collect_submodules(package)
    except Exception:  # noqa: BLE001 - the ner extra may not be installed
        pass

# The key file's cipher. `core/mapping.py` imports it *inside* the two functions
# that need it, because the extra is optional and `mapping_unavailable_reason()` is
# what decides - so PyInstaller sees no import at all, exactly like the NER stack
# above. Leaving it out produces a bundle whose `capabilities` says a key file is
# possible and whose first `--map` fails.
try:
    hidden += collect_submodules("cryptography")
except Exception:  # noqa: BLE001 - the restore extra may not be installed
    pass

# python-stdnum keeps one module per country and looks them up by name at call
# time, so a static analyser sees none of them.
hidden += collect_submodules("stdnum")

# phonenumbers ships its numbering-plan metadata as data modules.
hidden += collect_submodules("phonenumbers")

datas = []
for package in ("gliner2", "transformers", "tokenizers"):
    try:
        datas += collect_data_files(package, include_py_files=False)
    except Exception:  # noqa: BLE001 - an absent optional extra is not an error
        pass

# Tesseract language data, shipped beside the executable because that is the
# first place `tessdata_path()` looks after the two environment variables — see
# `_tessdata_candidates`, whose comment has said "where a packaged build would
# put it" since before any build put it there.
#
# The binary itself is not bundled, and cannot be: PyMuPDF shells out to
# `tesseract`, which is a platform package. So this does not make OCR work on a
# machine without Tesseract, and `capabilities.ocr_available` checks both halves
# for exactly that reason.
#
# Absent rather than fatal when the directory is empty: the files are gitignored
# and downloaded by the README's loop, so a fresh clone can still build an engine
# that refuses scans instead of failing to build at all.
_tessdata = os.path.join(ENGINE_DIR, "models", "tessdata")  # noqa: F821 - injected
if os.path.isdir(_tessdata):
    datas += [
        (os.path.join(_tessdata, name), "tessdata")
        for name in sorted(os.listdir(_tessdata))
        if name.endswith(".traineddata")
    ]

analysis = Analysis(
    [os.path.join(SPECPATH, "sidecar.py")],  # noqa: F821 - injected
    # The engine package itself, so `import freedocs` resolves.
    pathex=[ENGINE_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    # Nothing here is used by the engine and each one drags in large trees.
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "docx", "openpyxl", "pptx"],
    noarchive=False,
)
archive = PYZ(analysis.pure)

executable = EXE(
    archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="freedocs-engine",
    console=True,
    # The engine speaks on stdout and must never be stripped of it.
    strip=False,
    upx=False,
)

COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="freedocs-engine",
)
