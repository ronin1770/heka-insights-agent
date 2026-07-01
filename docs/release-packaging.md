# Release Packaging

## Goal

Build a bundled Linux executable and wrap it in a Debian package for Ubuntu `amd64`.

## Output Layout

The package build script produces:

- binary: `/usr/local/bin/heka-insights-agent`
- service: `/lib/systemd/system/heka-insights-agent.service`
- setup resume command: `sudo /usr/local/bin/heka-insights-agent setup`
- config target: `/etc/heka-insights-agent/.env`
- log target: `/var/log/heka-insights-agent/agent.log`

## Build Prerequisites

- `pyinstaller`
- `dpkg-deb`
- `fakeroot`
- `debhelper`
- `adduser`
- `systemd`

## Build Command

Run from repo root:

```bash
./packaging/build_deb.sh <version> "<maintainer>"
```

Example:

```bash
./packaging/build_deb.sh 0.1.0 "Heka Insights Agent <munir.farhan@gmail.com>"
```

## What The Build Script Does

1. Builds a one-file PyInstaller executable from `src/main.py`
2. Stages the Debian package filesystem
3. Installs the service unit and maintainer scripts
4. Copies docs and `.env.example`
5. Builds the `.deb` with `dpkg-deb`

## Install Flow

Install the package:

```bash
sudo dpkg -i heka-insights-agent_<version>_amd64.deb
```

During install:

1. package creates `heka-agent:heka-agent`
2. package prepares `/etc/heka-insights-agent`
3. package prepares `/var/log/heka-insights-agent`
4. package launches interactive setup when a terminal is available
5. successful setup enables and starts `heka-insights-agent.service`

If setup is cancelled:

```bash
sudo /usr/local/bin/heka-insights-agent setup
```

## Service Behavior

- `ExecStart=/usr/local/bin/heka-insights-agent run`
- `Restart=on-failure`
- `StartLimitBurst=3`
- `StartLimitIntervalSec=30`
