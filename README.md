# Netora

Netora is a small Windows desktop tool for watching network activity and putting a speed ceiling on a selected process.

It uses PyQt6 for the interface, psutil for process and socket information, pyqtgraph for the live chart, and WinDivert for packet interception. The UI is intentionally close to the dark Windows Task Manager style.

## What it does

- Shows current download and upload activity.
- Lists processes with active network connections.
- Applies separate download and upload limits to the selected process.
- Tracks the selected process and total traffic in a 60-second chart.
- Formats rates using binary units such as `KB/s` and `MB/s`.
- Writes debug output to the console and `netora_debug.log`.

## How limiting works

When a limit is applied, Netora finds the selected PID's local network ports with psutil. WinDivert captures TCP and UDP traffic for those ports. Matching packets are delayed by a token bucket and then sent back into the network stack. Packets that do not match the selected process are passed through without an intentional delay.

The process list is based on Windows socket and process information. The total rate is measured from network interface counters. Per-process telemetry should be treated as an estimate rather than a replacement for ETW-based network accounting.

## Requirements

- Windows 10 or Windows 11, 64-bit
- Python 3.10 or newer
- Administrator privileges
- WinDivert 64-bit binaries

WinDivert needs administrator access to install and open its packet interception driver. The project root should contain:

```text
NETORA/
├── app.py
├── engine.py
├── theme.py
├── WinDivert.dll
└── WinDivert64.sys
```

Use the official WinDivert release for the DLL and driver. Do not replace them with unsigned or modified copies.

## Install

From an elevated PowerShell window:

```powershell
python -m pip install PyQt6 pyqtgraph psutil pydivert
```

Make sure `WinDivert.dll` and `WinDivert64.sys` are beside `app.py`.

## Run

Start the application from an Administrator PowerShell window:

```powershell
python app.py
```

Select a process in the table, choose a download or upload ceiling, and click **Apply Ceiling**. Use **Remove Ceiling** to clear the current limit.

For a simple test, start a sustained download in another elevated PowerShell window:

```powershell
curl.exe -L "https://speed.cloudflare.com/__down?bytes=1000000000" -o NUL
```

Select `curl.exe` while it is running and apply a low download limit such as `500 KB/s`.

## Troubleshooting

### Access denied

Run PowerShell or VS Code as Administrator before starting Netora.

### WinDivert will not open

Check that the DLL and driver match the Python process architecture and came from an official WinDivert release. The exact startup error is shown in the application status area and written to `netora_debug.log`.

### The process list is empty

Some processes and sockets require elevation to inspect. Start Netora as Administrator and wait for the first telemetry update.

## Project files

- `app.py` contains the PyQt6 window and process table.
- `engine.py` contains WinDivert shaping and telemetry collection.
- `theme.py` contains the palette, stylesheet, and rate formatter.

## License

Netora is distributed under the MIT License.

WinDivert is a separate dependency and remains subject to its own LGPL/GPL licensing terms.

