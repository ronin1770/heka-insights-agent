# EL9 RPM Release Packaging

## Goal

Build a bundled Linux executable and wrap it in an RPM package for:

- CentOS Stream 9
- RHEL 9
- Rocky Linux 9
- AlmaLinux 9
- `x86_64`

## Packaging Path

- build script: `packaging/rpm/build_rpm.sh`
- spec file: `packaging/rpm/heka-insights-agent.spec`
- service unit: `packaging/rpm/heka-insights-agent.service`

## Output Layout

The package build script produces:

- binary: `/usr/local/bin/heka-insights-agent`
- service: `/usr/lib/systemd/system/heka-insights-agent.service`
- setup resume command: `sudo /usr/local/bin/heka-insights-agent setup`
- config target: `/etc/heka-insights-agent/.env`
- log target: `/var/log/heka-insights-agent/agent.log`
- package artifact: `heka-insights-agent-<version>-1.el9.x86_64.rpm`

## Build Prerequisites

- `pyinstaller`
- `rpmbuild`
- `systemd-rpm-macros`
- `shadow-utils`
- `findutils`
- EL9 build environment for the PyInstaller binary

## Build Command

Run from repo root on an EL9-compatible build host:

```bash
./packaging/rpm/build_rpm.sh <version> "<packager>"
```

Example:

```bash
./packaging/rpm/build_rpm.sh 0.1.0 "Heka Insights Agent <munir.farhan@gmail.com>"
```

## What The Build Script Does

1. Builds a one-file PyInstaller executable from `src/main.py`
2. Stages RPM sources and spec input under `build/rpmbuild`
3. Installs the service unit and packaged docs into the RPM build root
4. Builds the `.rpm` with `rpmbuild`
5. Writes a `.sha256` file beside the RPM artifact

## Install Flow

Install the package:

```bash
sudo dnf install -y ./heka-insights-agent-<version>-1.el9.x86_64.rpm
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

## Build Environment Note

Build the RPM artifact on an EL9-compatible environment. Do not reuse the
Ubuntu-built PyInstaller binary for the EL9 release artifact.
