# VM Ops Automation Playbook — Alert → Auto-fix

Runbook-style automation flows for Linux VMs (Azure / on-prem).  
Format: **Issue → Alert trigger → Auto-fix**

Flow name pattern: `vm-ops-{tier}-{issue-slug}`  
Example: `vm-ops-t1-disk-full`, `vm-ops-t3-docker-crashloop`

---

## Tier 1 — System resources

| Issue | Alert trigger | Auto-fix |
|-------|---------------|----------|
| Disk full | `/` or `/var` > 85% | Purge rotated logs, `/tmp` + `/var/tmp` clean, `docker system prune -af` (with retention policy) |
| Inode exhaustion | inodes > 90% on any mount | Small-file cleanup, log purge, `/tmp` sweep, audit `find /var/log -type f -size -1k` |
| High CPU | CPU > 90% for 5 min | `top`/`pidstat` → identify process; restart runaway service; scale alert if sustained |
| High memory | RAM > 90% | Check OOM in `dmesg`; drop caches (`sync; echo 3 > /proc/sys/vm/drop_caches` — cautious); restart heavy service |
| Swap full | swap > 80% | Restart memory-heavy services; investigate leak; alert if swap stays high |
| High load average | load1 > CPU cores × 2 for 5 min | Process analysis; kill stuck jobs; restart queue workers |
| High I/O wait | `iowait` > 30% for 5 min | Identify disk-heavy process; check cloud disk throttling; schedule log rotation |
| Disk latency spike | read/write latency > threshold | Check `iostat`; move logs; verify disk not near full |

---

## Tier 2 — Network & connectivity

| Issue | Alert trigger | Auto-fix |
|-------|---------------|----------|
| Port not listening | app port unreachable (TCP probe fail) | `systemctl restart` or `docker compose restart`; verify bind address in config |
| DNS resolution fail | `nslookup` / `dig` fail for known host | Check `/etc/resolv.conf`; restart `systemd-resolved`; fallback to Azure DNS `168.63.129.16` |
| High network errors | RX/TX drops or errors on interface | `ip link` stats; interface down/up; check driver; Azure NIC reset if needed |
| SSL cert expiring | cert expiry < 30 days | `certbot renew`; `nginx -s reload` or container reload |
| SSL cert expired | HTTPS probe fail + cert expired | Emergency renew + reload; alert on-call |
| Default route missing | no default gateway | Restore route; restart networking; check Azure UDR / NSG |
| MTU / fragmentation issues | large packet loss to DB VM | Set MTU 1400 on Azure paths; verify NSG allows return traffic |
| Connection refused spike | SYN → RST ratio high | Service crash or wrong port; restart app; check compose port mapping |
| High established connections | conn count > ulimit threshold | Restart service; tune `somaxconn`; check connection leak |
| Inter-VM connectivity fail | app VM → DB VM port blocked | NSG rule verify (3306/5432/27017/6379); test `nc -zv`; open rule + document |

---

## Tier 3 — Service & process health

| Issue | Alert trigger | Auto-fix |
|-------|---------------|----------|
| systemd service inactive | `systemctl is-active` != active | `systemctl restart`; verify `ExecStart`; check unit file |
| systemd service flapping | restart count > N in 10 min | Collect journal; hold restart; alert Tier 2 |
| Zombie processes | zombie count > threshold | Identify parent PID; restart parent service |
| Process not running | expected PID / container missing | Start service or `docker compose up -d` |
| File descriptor limit | open FDs > 80% of ulimit | Restart service; raise `LimitNOFILE` in unit; investigate leak |
| Core dumps accumulating | `/var/crash` or core files growing | Rotate/delete old cores; fix crashing binary |
| Cron job failed | cron exit non-zero in mail/log | Re-run job; fix script; alert owner |
| Timer unit missed | systemd timer not fired | `systemctl start` timer; check `OnCalendar` |

---

## Tier 4 — Docker & containers

| Issue | Alert trigger | Auto-fix |
|-------|---------------|----------|
| Container crash loop | restart count > 5 in 10 min | `docker logs --tail 200`; fix env/config; `compose up -d`; collect logs to blob |
| Docker daemon down | `docker info` fail | `systemctl restart docker`; verify disk space first |
| Image pull failure | pull exit 401/403/404 | `az acr login`; verify tag exists; retry pull |
| Container unhealthy | healthcheck failing > 3 intervals | Inspect health command; extend `start_period`; restart dependent order |
| Container OOM killed | exit 137 / dmesg OOM on container | Raise memory limit in compose; restart; profile app |
| Volume mount fail | container exit on start, mount error | Verify path exists; permissions; named volume recreate (data risk — alert) |
| Docker disk full | `/var/lib/docker` > 85% | `docker system prune`; remove dangling images; expand disk |
| Compose dependency stuck | service waiting on unhealthy dep | Restart infra first (postgres/redis/mongo), then apps |
| Bridge / DNS in compose | service can't resolve `postgres` | Recreate network: `compose down && up`; check custom network |
| Log driver full | json-file logs huge | Truncate or rotate; set `max-size` / `max-file` in compose logging |

---

## Tier 5 — Application & HTTP (Docker apps)

| Issue | Alert trigger | Auto-fix |
|-------|---------------|----------|
| Health endpoint down | `GET /health` != 200 for 2 min | Restart gateway → backends; verify downstream URLs |
| HTTP 5xx spike | 5xx rate > 5% for 5 min | Tail gateway logs; restart failing microservice |
| High API latency | p95 > SLO for 5 min | Check DB/Redis latency; restart slow service; OTel trace sample |
| HTTP 502 / 503 burst | gateway downstream errors | Verify internal service names (not `localhost` in container) |
| UI loads but API empty | smoke: HTML OK, API fail | Browser-side vs backend triage; rebuild UI if build-time env wrong |
| Database connection pool exhausted | "too many connections" in logs | Restart app; kill idle DB sessions; tune pool size |
| Redis timeout | Redis errors in payments/cache svc | Test `redis-cli -h ... ping`; restart redis or fix NSG |
| MySQL/Postgres unreachable | connection timeout in app logs | `nc -zv` from app VM; NSG + credentials; restart DB VM service |
| Mongo auth fail | auth error in users/analytics logs | Verify `MONGO_URI` authSource; rotate creds if expired |
| Migration / schema mismatch | SQL errors on startup | Run migration job; rollback app tag if breaking |

---

## Tier 6 — Observability & agents

| Issue | Alert trigger | Auto-fix |
|-------|---------------|----------|
| OTEL traces missing | no spans for service > 15 min | Verify `OTEL_EXPORTER_OTLP_ENDPOINT`; `host.docker.internal` + `extra_hosts`; restart collector |
| OTEL collector down | collector health fail | Restart collector container/systemd; check port 4317/4318 |
| Log shipper stopped | agent not sending > 10 min | Restart fluent-bit / filebeat / azure-walinuxagent extension |
| Metrics scrape fail | Prometheus target down | Fix scrape port; restart exporter sidecar |
| Clock / NTP drift | skew > 500 ms | Restart `chronyd` / `systemd-timesyncd`; verify Azure time sync |
| Disk full from logs | `/var/log` growth rate high | logrotate force; reduce debug log level via env |

---

## Tier 7 — Security & access

| Issue | Alert trigger | Auto-fix |
|-------|---------------|----------|
| Failed SSH login spike | auth.log brute force pattern | fail2ban ban; optional temporary NSG deny rule |
| Root login attempt | root SSH in auth.log | Alert only (no auto-unban); tighten sshd_config |
| Unexpected sudo usage | sudo to root by unknown user | Alert + ticket; no auto-fix |
| Kernel OOM events | OOM in `dmesg` | Restart victim service; set memory limits in compose/systemd |
| Mount read-only | filesystem remounted RO | `dmesg` / `journalctl`; schedule fsck; remount RO→RW if safe |
| World-writable sensitive path | audit rule hit | Fix permissions; alert security |
| ACR / cloud token near expiry | token TTL < 7 days | Rotate SP secret; refresh `az acr login` cron |
| TLS weak cipher / protocol | external scan fail | Update nginx/cipher suite; reload |

---

## Tier 8 — Azure VM specific

| Issue | Alert trigger | Auto-fix |
|-------|---------------|----------|
| WALinuxAgent unhealthy | agent status warning | `systemctl restart walinuxagent`; check extension logs |
| Ephemeral disk full | `/mnt` or temp disk > 90% | Move Docker data or logs; don't store state on temp disk |
| Azure planned maintenance | platform scheduled event | Drain: `compose stop`; notify; restart post-maintenance |
| Public IP changed | DNS/probe fail after reboot | Update DNS A record automation; document static IP use |
| NSG misconfiguration | sudden port probe fail from internet | Compare NSG rules; restore inbound for 22/80/443/app ports |
| Managed identity token fail | IMDS 401/403 | Restart VM agent; verify identity assigned to VM |
| Boot diagnostics needed | VM unreachable | Trigger boot diagnostics capture; alert ops (no destructive auto-fix) |
| Disk attach fail | data disk not mounted | `lsblk`; mount via `/etc/fstab`; restart mount unit |

---

## Tier 9 — Data & backup

| Issue | Alert trigger | Auto-fix |
|-------|---------------|----------|
| Backup job failed | last backup status != success | Retry backup script; check disk space; alert DBA |
| Backup stale | no successful backup > 24 h | Force backup run; escalate if fail twice |
| DB disk growth anomaly | DB volume growth > 2× daily avg | Run purge/archival; expand disk; investigate bulk insert |
| Replication lag (if used) | lag > threshold | Restart replica; check network to primary |
| Snapshot mount fail | restore test fail | Alert only; manual restore drill |

---

## Tier 10 — Performance & capacity (proactive)

| Issue | Alert trigger | Auto-fix |
|-------|---------------|----------|
| Disk will fill in 72 h | linear forecast > 95% | Pre-emptive log prune + docker prune; ticket to expand disk |
| Memory trend upward | RSS slope up 7 days | Schedule restart window; leak investigation ticket |
| CPU credit exhausted (B-series) | CPU credits = 0 sustained | Alert to resize VM; reduce load temporarily |
| Connection count trend | ESTABLISHED rising 24 h | Restart app before hard limit; capacity ticket |
| Certificate expiry 7 days | cert < 7 days | Force renew (stricter than 30-day tier) |

---

## Automation flow names (ready to create)

| Flow name | Tier | Trigger metric |
|-----------|------|----------------|
| `vm-ops-t1-disk-full` | 1 | disk_used_percent |
| `vm-ops-t1-inode-full` | 1 | inode_used_percent |
| `vm-ops-t1-high-cpu` | 1 | cpu_percent_5m |
| `vm-ops-t1-high-memory` | 1 | mem_percent |
| `vm-ops-t1-high-load` | 1 | load1 vs cores |
| `vm-ops-t2-port-down` | 2 | tcp_probe_fail |
| `vm-ops-t2-dns-fail` | 2 | dns_check_fail |
| `vm-ops-t2-cert-expiry` | 2 | cert_days_left |
| `vm-ops-t2-intervm-blocked` | 2 | nc_db_port_fail |
| `vm-ops-t3-service-down` | 3 | systemd_inactive |
| `vm-ops-t3-zombie-spike` | 3 | zombie_count |
| `vm-ops-t4-docker-crashloop` | 4 | container_restart_rate |
| `vm-ops-t4-docker-daemon` | 4 | docker_info_fail |
| `vm-ops-t4-image-pull-fail` | 4 | acr_pull_fail |
| `vm-ops-t5-health-down` | 5 | http_health_fail |
| `vm-ops-t5-http-5xx` | 5 | http_5xx_rate |
| `vm-ops-t5-db-unreachable` | 5 | db_connect_fail |
| `vm-ops-t6-otel-missing` | 6 | otel_span_rate_zero |
| `vm-ops-t6-ntp-drift` | 6 | clock_skew_ms |
| `vm-ops-t7-ssh-bruteforce` | 7 | ssh_fail_rate |
| `vm-ops-t7-kernel-oom` | 7 | oom_events |
| `vm-ops-t8-nsg-block` | 8 | external_probe_fail |
| `vm-ops-t8-agent-down` | 8 | walinuxagent_status |
| `vm-ops-t9-backup-fail` | 9 | backup_job_fail |
| `vm-ops-t10-disk-forecast` | 10 | disk_forecast_72h |

---

## Auto-fix safety rules (all tiers)

1. **Never auto-prune Docker volumes** without explicit policy — data loss risk.
2. **Max 3 auto-restarts** per service per hour — then alert human.
3. **Collect logs before restart** on crash loop (last 500 lines → file/blob).
4. **NSG changes** — auto-fix = verify + ticket, not blind open `0.0.0.0/0`.
5. **fsck / remount RW** — alert only, no unattended fsck on production.
6. **Credential rotation** — alert + runbook link, not fully unattended unless vault integrated.

---

## Suggested alert severity

| Severity | Tiers | Response |
|----------|-------|----------|
| P1 Critical | Service down, disk 95%, crash loop, DB unreachable | Auto-fix + page |
| P2 High | CPU/mem sustained, cert 7d, 5xx spike | Auto-fix + Slack |
| P3 Medium | Cert 30d, disk forecast, OTEL gap | Auto-fix or ticket |
| P4 Low | Zombie count, inode trend | Ticket only |

---

*Generic Linux/Azure VM playbook — wire triggers to your monitoring (Datadog, Azure Monitor, Prometheus, etc.).*
