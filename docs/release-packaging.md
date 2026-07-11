# Release Packaging

Use the packaging guide that matches the release artifact you are producing:

- Debian / Ubuntu: `docs/release-packaging-debian.md`
- CentOS Stream 9 / RHEL 9 / Rocky Linux 9 / AlmaLinux 9: `docs/release-packaging-rpm.md`

Both packaging paths preserve the same packaged runtime contract:

- binary: `/usr/local/bin/heka-insights-agent`
- config target: `/etc/heka-insights-agent/.env`
- log target: `/var/log/heka-insights-agent/agent.log`
- setup resume command: `sudo /usr/local/bin/heka-insights-agent setup`
