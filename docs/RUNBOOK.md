# MeshBridge Runbook

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Validate config

```bash
python3 main.py --config config.hjson --check-config
```

## Run manually for testing

```bash
python3 main.py --config config.hjson --log-level DEBUG
```

## Run under systemd

Update the included `systemd/meshbridge.service` file with the correct paths, then:

```bash
sudo cp systemd/meshbridge.service /etc/systemd/system/meshbridge.service
sudo systemctl daemon-reload
sudo systemctl enable meshbridge
sudo systemctl start meshbridge
sudo systemctl status meshbridge
```

## Watch logs

If running manually:

```bash
tail -f meshbridge.log
```

If running under systemd:

```bash
journalctl -u meshbridge -f
```

## First startup checklist

- Config validates successfully
- Bot logs in successfully
- Slash commands appear in the configured guild
- MeshCore connection succeeds
- Discord -> Mesh test message works
- Mesh -> Discord webhook test message works
- `/bridge version` returns status info
- `/neighbors list` returns neighbor entries

## Common issues

### Config parsing error
Cause:
- wrong file path
- old JSON parser still in use
- HJSON comments present but `hjson` not installed

Fix:
- make sure `meshbridge/config.py` imports `hjson`
- make sure `requirements.txt` includes `hjson`
- rerun `pip install -r requirements.txt`

### Slash commands missing
Cause:
- bot not invited with commands scope
- wrong guild ID
- sync delay

Fix:
- verify application ID and guild ID
- restart the bot
- verify command sync logs

### Mesh -> Discord sender shows `unknown`
Cause:
- sender name not present in the payload
- fallback parser not applied
- wrong bridge file still being loaded

Fix:
- verify the current `meshbridge/bridge.py` is the active file
- inspect debug log lines beginning with `Built mesh message:`
- verify webhook sender receives the correct display name

### Neighbor list shows no names
Cause:
- adverts often carry only keys
- names may arrive later via chat or contact lookup

Fix:
- allow time for message traffic/contact lookup to upgrade records
- inspect `Built mesh message:` debug lines
