# FreeDocs documentation

The [README](../README.md) is the short version. This is everything else.

English only, deliberately: the README exists in four languages because it is
what a first visitor reads, while a measurement duplicated four times is a
measurement that disagrees with itself after the next benchmark run.

| Page | What is in it |
|---|---|
| [architecture.md](architecture.md) | The six stages, the offset map that makes in-place editing possible, and the detection layers L1 to L3 |
| [benchmark.md](benchmark.md) | Every published figure, the command that reproduces it, and what the corpus can and cannot show |
| [cli.md](cli.md) | Every command, every flag, every exit code |
| [hidden-content.md](hidden-content.md) | What Word, Excel and PowerPoint files keep where reading the document does not reveal it |
| [scanned-pdfs.md](scanned-pdfs.md) | OCR setup, redacting pixels instead of glyphs, and why a scan is verified differently |
| [desktop-app.md](desktop-app.md) | The Tauri window: how it is built, what it shows, and what it deliberately refuses to decide |
| [gitflow.md](gitflow.md) | The branching model, the one version authority, and what the two git hooks can and cannot enforce |
| [packaging.md](packaging.md) | Building the sidecar and the installers, and the honest multi-platform status |
| [portable.md](portable.md) | The unzip-and-run bundle: why it needs no writable state, and what does not travel with it |
| [restore.md](restore.md) | The reverse path: the opt-in encrypted key file, and putting the values back into what the model returned |
| [terms.md](terms.md) | The encrypted term list: values removed on every scrub, what the encryption protects and what it does not |
| [llm-review.md](llm-review.md) | The opt-in second opinion over already-anonymised text |
| [security-review.md](security-review.md) | A source review of the whole project: sixteen findings, what was done about each, and what is deliberately still open |

Contributing is covered in [CONTRIBUTING.md](../CONTRIBUTING.md); the threat
model and how to report a vulnerability are in [SECURITY.md](../SECURITY.md).
