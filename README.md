# doc2md watcher

A Python CLI that recursively watches one or more directory trees and creates
revisioned conversions:

- `.docx` → `.md`
- `.xlsx` → `.csv`
- `.md` → `.docx`
- `.csv` → `.xlsx`
- `.pdf` → `.md`
- `.json`, `.yaml`, `.yml`, `.xml` → `.md`
- `.html`, `.htm`, `.txt`, `.log`, `.rtf` → `.md`
- `.pptx`, `.odt` → `.md`
- `.ods`, `.tsv`, `.jsonl`, `.ndjson` → `.csv`
- `.eml`, `.msg`, `.ipynb` → `.md`

Generated files are named `name_r001.ext`, `name_r002.ext`, etc. Before a new
revision is written, older generated revisions for the same source are moved to
`<watch-root>/98_archive/<relative source folder>/`.

## Install

Requires Python 3.10 or newer. The same package supports macOS and Windows.

### macOS

```bash
python -m pip install -e .
```

Launch the dashboard and choose a folder:

```bash
./run_macos.command
```

### Windows

From Command Prompt or PowerShell:

```bat
py -m pip install -e .
run_windows.bat
```

## Run

```bash
doc2md-watch ~/Documents/incoming ~/Documents/other
```

If the user-level scripts directory is not on `PATH`, use:

```bash
python -m doc2md_watcher ~/Documents/incoming ~/Documents/other
```

Show the floating status dashboard:

```bash
python -m doc2md_watcher --gui --initial ~/Documents/incoming
```

When `--gui` is used without a folder, a native folder chooser opens:

```bash
python -m doc2md_watcher --gui --initial
```

## Startup configuration

On the first successful launch, the app stores its startup settings in
`config.json` in the current working directory:

```json
{
  "folders": ["/path/to/watch"],
  "gui": true,
  "initial": true,
  "settle_seconds": 1.0,
  "verbose": false
}
```

If `config.json` exists, it is the startup source and its values take precedence
over CLI arguments. If it does not exist, CLI inputs are used and saved as the
new configuration. Folder paths may be absolute or relative to `config.json`.
Delete or edit the file to change the saved startup behavior.
The machine-local `config.json` is ignored by Git; copy `config.example.json`
when preparing a configuration manually.

The dashboard stays above other windows and shows discovered documents, pending
jobs, files waiting to be released, active conversion, completed work, failures,
and recent activity. Conversion runs in a dedicated child process. Before each
job, the child polls until the file has stable size/modification time, has no
Microsoft Office owner file, and can obtain a non-blocking lock.

File locking is platform-aware: it uses `flock` semantics on macOS and native
mandatory file locking on Windows. The watcher uses a portable polling backend,
so it also works with network and synced folders where native change APIs can be
unreliable.

The pending queue is persisted at
`<watch-root>/98_archive/.doc2md-watcher-queue.json`. If the application is
stopped while a file is queued, waiting for release, or converting, that job is
restored automatically on the next launch. This recovery does not require
`--initial`.

## Governance provenance

Every output has a companion `<output>.manifest.json` containing the source and
output SHA-256 hashes, sizes, formats, UTC conversion timestamp, converter
version, and revision number. Manifests move into the matching `98_archive`
subfolder with their output revision.

The original evidence file is never modified. Executables, scripts,
macro-enabled Office files (`.docm`, `.xlsm`, `.pptm`), archives, and serialized
model binaries are intentionally not processed.

Process files that already exist before watching:

```bash
doc2md-watch --initial ~/Documents/incoming
```

Other useful options:

```bash
doc2md-watch --settle-seconds 1.5 --verbose /path/to/root
```

The archive contains a `.doc2md-watcher-state.json` file used to recognize
generated outputs across restarts. The archive tree is excluded from watching.

## Revision example

Editing `reports/summary.docx` creates:

```text
reports/summary_r001.md
```

Editing it again moves that result to:

```text
98_archive/reports/summary_r001.md
```

and creates:

```text
reports/summary_r002.md
```
