# Deployment Notes

## Debian Server

Current service:
- Service name: `g-tooling.service`
- App path: `/opt/g-tooling`
- Runtime command: `/usr/bin/python3 /opt/g-tooling/app.py`
- Active DB path: `/data/WOODWORK/DATABASES/tooling.db`

The DB path is currently stored in:
`/opt/g-tooling/data/settings.json`

## First Deploy

Clone repo:

```bash
git clone https://github.com/george-74/g-tooling.git
```

If `/opt/g-tooling` already exists as a non-git deployed copy, update it like this:

```bash
cp /opt/g-tooling/data/settings.json /tmp/g-tooling-settings.json
rsync -av --delete --exclude '.git' --exclude 'data/settings.json' --exclude 'data/*.db' /home/george/g-tooling/ /opt/g-tooling/
cp /tmp/g-tooling-settings.json /opt/g-tooling/data/settings.json
sudo systemctl restart g-tooling.service
systemctl status g-tooling.service --no-pager
```

## Next Updates

After new commits are pushed to GitHub:

```bash
cd ~/g-tooling
git pull
rsync -av --delete --exclude '.git' --exclude 'data/settings.json' --exclude 'data/*.db' ~/g-tooling/ /opt/g-tooling/
sudo systemctl restart g-tooling.service
```

## Notes

- Do not overwrite `/opt/g-tooling/data/settings.json`.
- Do not store the production DB inside the repo.
- Port `8765` is used by the running service.
