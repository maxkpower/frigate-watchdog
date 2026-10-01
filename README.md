# frigate-watchdog

Checks Frigate once a minute and alerts you (Telegram and/or Signal) when the NVR or a camera stops recording. It also fixes the most common hang by itself.

## Why

Frigate can look healthy and be useless. In my case the service showed "active" for 41 hours while the API returned errors and no camera recorded. At startup Frigate probes any camera without explicit `detect: width/height` using `ffprobe`, with no timeout, so one dead stream blocked the whole NVR. Nothing alerted.

## What it does

| Check | Fails when |
|---|---|
| `ct` | the Proxmox LXC running Frigate is not running |
| `api` | `/api/stats` or `/api/config` doesn't return 200 JSON |
| `cam:<name>` | an enabled camera has no recording segment newer than 2 min, or detect is on and fps is 0 |
| `probe` | a startup `ffprobe` has run for more than 2 min |
| `disk:<path>` | a Frigate storage path (recordings, cache, `/dev/shm`) is 90% full |
| `detector:<name>` | the detector process is missing, stuck on one detection, or (optional) slow |
| `skipped:<cam>` | the detector is skipping frames for 3 checks in a row |
| `restart-loop` | Frigate restarted 3 or more times in the last hour |
| `log:<what>` | the Frigate log shows a fatal error, a burst of GPU/timestamp errors, or a camera's ffmpeg crashing over and over |
| `db` | the Frigate SQLite database fails its daily integrity check |
| `mqtt` | Frigate's retained `frigate/available` isn't `online` on the broker (optional) |

Self-healing:
- Kills a hung startup `ffprobe`.
- Restarts Frigate after 5 failed API checks in a row (at most once per 30 min).

Alerting:
- Alerts after 3 bad checks in a row, repeats hourly, sends a recovery message.
- Problems found in one run are sent as one message.
- Every event is also logged to syslog with the tag `frigate-watchdog`.

## Requirements

- Python 3.9+, standard library only.
- Frigate API reachable (default port 5000) and recording enabled.
- A Telegram bot and/or a [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api) instance.
- Frigate in a Proxmox LXC. Run the watchdog on the Proxmox host. For Docker or bare metal, see "Adapting".

## Install

1. Give every camera explicit detect dimensions in the Frigate config (this removes the cause of the hang):
   ```yaml
   cameras:
     front_door:
       detect:
         width: 1920
         height: 1080
   ```
2. Run `sudo ./install.sh`. It installs the script and systemd units and creates `/etc/frigate-watchdog.conf` (mode 600). It does not start the timer.
3. Edit `/etc/frigate-watchdog.conf`. Set `FRIGATE_VMID`, `FRIGATE_API` and at least one channel. Leave a channel's keys out to disable it.
4. Test:
   ```bash
   sudo frigate-watchdog --dry    # runs the checks, sends nothing, writes no state
   sudo frigate-watchdog --test   # sends one test message on every channel
   ```
   A healthy system prints `problems: {}`.
5. Start it:
   ```bash
   sudo systemctl enable --now frigate-watchdog.timer
   ```

To try it for real, stop Frigate (`pct exec <id> -- systemctl stop frigate`). Expect an alert after about 3 min and an automatic restart after about 5.

## Config

Optional keys, defaults shown:

| Key | Default | Meaning |
|---|---|---|
| `CONFIRM_CHECKS` | 3 | bad checks in a row before alerting |
| `REPEAT_SECONDS` | 3600 | re-alert interval while still down |
| `SEGMENT_MAX_AGE` | 120 | max age of the newest recording segment (s) |
| `PROBE_MAX_AGE` | 120 | age at which `ffprobe` counts as hung (s) |
| `API_RESTART_AFTER` | 5 | failed API checks before restarting Frigate |
| `RESTART_COOLDOWN` | 1800 | minimum gap between restarts (s) |
| `DISK_WARN_PCT` | 90 | storage usage that raises `disk:` |
| `DETECTOR_STUCK_SECONDS` | 60 | one detection in flight longer than this = stuck |
| `RESTART_LOOP_COUNT` | 3 | restarts per hour that count as a loop |
| `LOG_FILE` | `/dev/shm/logs/frigate/current` | log inside the container (empty disables the scan) |
| `LOG_BURST` | 30 | noisy log patterns per hour before alerting |
| `CRASH_PER_HOUR` | 30 | ffmpeg crashes per camera per hour before alerting |
| `DB_CHECK`, `DB_PATH`, `DB_CHECK_INTERVAL` | 1, `/config/frigate.db`, 86400 | database check |

## Optional features

Set these in `/etc/frigate-watchdog.conf`:

```ini
IGNORE_CAMERAS=garage,spare_cam        # known-offline cameras: skipped by every check
MQTT_HOST=<broker-ip>                  # enables the MQTT check; also MQTT_PORT, MQTT_USER, MQTT_PASS, MQTT_TOPIC
HEARTBEAT_URL=https://hc-ping.com/<id> # pinged every run; the monitor alerts if the pings stop
DETECTOR_MAX_MS=50                     # alert if inference is slower than this (off by default; set above normal)
```

- A camera that is permanently dead logs ffmpeg crashes all day, so add it to `IGNORE_CAMERAS` or it will keep alerting (this check, and the `cam:` check, both skip ignored cameras).
- The log scan starts at the end of the log on first run, so old errors never alert. It reads only new lines each minute.
- Frigate's `detection_fps` is 0 whenever nothing moves, so it isn't used to detect a hung detector.

## Operating

```bash
journalctl -t frigate-watchdog --since "24 hours ago"
cat /var/lib/frigate-watchdog/state.json
```

Log lines look like `DOWN cam:front_door: camera front_door: not recording`. Levels: `DOWN`, `RECOVERED`, `REMEDIATION`, `ERROR`, `TEST`. An `ERROR delivery:` line means an alert couldn't be sent.

## Adapting

- **Docker:** replace `ct()` with `docker exec <container> sh -c ...`, drop the `pct status` check, restart with `docker restart`.
- **Bare metal:** run the commands locally, without the wrapper.
- **Other cache path:** change `/tmp/cache` in the segment check.
- **Email:** add a `send_email()` beside the other senders and call it from `notify()`.
- **SIEM:** match the syslog tag `frigate-watchdog` and the level words above. If your SIEM also sends chat alerts above some level, keep the DOWN rules below it to avoid double alerts, and the `ERROR delivery:` rule above it so the SIEM is the backup route.

## Limits

- It runs on the machine it protects. If that machine dies, nothing alerts. Add an outside uptime check.
- A persistent fault repeats hourly forever. Disable intentionally offline cameras in Frigate (`enabled: false`) so they're skipped.
- Camera, disk, detector and restart checks don't run while the API is down (log, database and MQTT checks still do).
- A camera whose segments are longer than `SEGMENT_MAX_AGE` will false-alarm. Raise the value.
- It runs as root (it uses `pct exec` and restarts services). Review changes before deploying, and keep the config at mode 600.

## Tests

```bash
python3 -m unittest discover -s tests
```

## License

MIT
