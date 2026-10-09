# Scheduled off-host backups (Cloudflare R2) and the restore drill

Every night the production host sends the database and the private documents to Cloudflare R2;
once a week a second, longer-kept set. Failures alert on Telegram. A restore drill proves the
newest set restores and runs.

| | |
| --- | --- |
| Daily | 02:30 UTC (`plasma-backup-daily.timer`): `pg_dump` + `/app/private-data` → `r2://<bucket>/plasma/daily/`, newest **14** kept |
| Weekly | Sundays 03:30 UTC (`plasma-backup-weekly.timer`): same → `…/weekly/`, newest **4** kept; tender documents (`/app/data`) only with `BACKUP_WEEKLY_TENDER_DOCUMENTS=1` (**off**) |
| Local copy | the latest dumps stay in `/var/backups/plasma` (7 days, at least 3) as a fast restore point |
| Failure alert | `OnFailure=plasma-notify@%n` → Telegram message with the unit's last journal lines |
| Secrets | `/etc/plasma/ops.env` (root, mode 600); the R2 endpoint, bucket and keys are passed to rclone/aws only through the environment and are masked (`<endpoint>`, `<bucket>`, `<secret>`) in everything the scripts print |

A set is `plasma_prod_<UTC>_<hash>.{dump,private.tar.gz[,tender.tar.gz],sha256,manifest}`; the
manifest is uploaded last and marks the set complete. Every component is hashed while it streams
and its remote size is checked after upload (`BACKUP_VERIFY_DOWNLOAD=1` re-downloads and compares
SHA-256). Retention counts complete sets only; incomplete sets older than a day are deleted.
Manual runs without `--tier` (the deploy runbooks) keep their old behaviour and location.

## Cost (Cloudflare R2, Standard storage, pricing checked 2026-10-09)

| Item | Size | Monthly |
| --- | --- | --- |
| One set (database dump + private documents), local data today | 119.7 MB (dump 118.9 MB, private 0.76 MB) | |
| 14 daily + 4 weekly sets | ≈ 2.2 GB (≈ 3 GB with growth) | **$0**: inside the free 10 GB-month |
| Operations | ≈ 2 sets/day × ~30 requests (multipart chunks, list, head) ≈ 2,000 Class A/month | **$0**: free tier is 1 M Class A, 10 M Class B |
| Restores / drills | downloads | **$0**: no egress fees |
| Weekly **with** tender documents | + ≈ 5 GB per set (local volume today: 4.95 GB) × 4 ≈ 20 GB | ≈ $0.15-0.20 (storage beyond 10 GB at $0.015/GB-month) |

Beyond the free tier: $0.015/GB-month storage, $4.50 per million Class A, $0.36 per million
Class B operations, no egress fee. Tender documents are public and re-acquirable from the
sources, which is why they are off by default.

## Setup (owner, once)

1. **R2 bucket** (Cloudflare dashboard → R2): create a bucket, e.g. `plasma-backups`
   (location hint: Eastern Europe), no public access. Optionally an object lifecycle rule
   "delete after 60 days" as a safety net (the scripts already keep 14 + 4).
2. **API token** (R2 → Manage API tokens → Create): *Object Read & Write*, **only this bucket**.
   Note the Access Key ID, the Secret Access Key and the S3 endpoint
   `https://<account id>.r2.cloudflarestorage.com`. Create a second token with *Object Read only*
   for the restore drill on the laptop.
3. **Tool** on the host: `sudo apt-get install -y rclone` (or the aws CLI; `BACKUP_S3_TOOL=aws`).
4. **Settings**: `sudo install -d -m 700 /etc/plasma && sudo install -m 600 deploy/systemd/ops.env.example /etc/plasma/ops.env`,
   then edit `/etc/plasma/ops.env`: `BACKUP_REMOTE=r2://plasma-backups/plasma`, `BACKUP_S3_ENDPOINT`,
   `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY` (and the Telegram lines, docs/ops/HOST_SETUP.md).
5. **Units**: see docs/ops/HOST_SETUP.md "Install the timers". First run by hand:
   ```
   prod$ sudo systemctl start plasma-backup-daily.service; journalctl -u plasma-backup-daily -n 20 -o cat
   ```
   Expect `BACKUP_RESULT set=plasma_prod_… tier=daily … remote=r2:<bucket>/plasma/daily via rclone …`.
6. **Prove a failure alerts**: `sudo systemctl start plasma-notify@plasma-backup-daily.service` sends a test alert.

## Restore drill (laptop or spare host, monthly and after every backup change)

`scripts/ops/restore_drill.sh` finds the newest complete set, downloads it to
`backups/drill/<set>`, checks every component against the manifest and the `.sha256`, restores it
into the isolated `plasma_staging` stack (`restore_to_staging.sh`: refuses any other project, reads
only `.env.staging`), waits for `/health/ready` and runs `smoke.sh --target staging`. It never
contacts production. It needs `.env.staging` and ~2.7 GB of free RAM for the staging stack.
```
laptop$ export BACKUP_REMOTE=r2://plasma-backups/plasma BACKUP_S3_ENDPOINT=… BACKUP_S3_ACCESS_KEY_ID=<read-only> BACKUP_S3_SECRET_ACCESS_KEY=<read-only>
laptop$ scripts/ops/restore_drill.sh --tier daily --images <release SHA> --yes [--migrate] [--stop-after]
```
Expect `DRILL_RESULT set=… age_hours=<26 or less> … smoke=pass`. `--images` starts staging from the
release images already on the machine (no build); `--migrate` also rehearses the next release's
migrations on the restored data.

## Restore on production (data loss)

Use the deploy runbook's Rollback C with the newest set: pre-stop gate, stop the app, drop/create
the database, `pg_restore` the dump, replace `/app/private-data` from the archive. Fetch the set
from R2 first if the local copy is gone:
```
prod$ set -a; . /etc/plasma/ops.env; set +a
prod$ bash -c 'source scripts/ops/lib.sh; source scripts/ops/remote_lib.sh; remote_setup "$BACKUP_REMOTE"; remote_subdir daily; S=$(remote_latest_set prod); for f in dump private.tar.gz sha256; do remote_get "$S.$f" > /var/backups/plasma/$S.$f; done; cd /var/backups/plasma && sha256sum -c $S.sha256'
```

## Proof (R3, local)

Against an S3-compatible endpoint (`rclone serve s3`) with the local stack's real database and
private documents, `BACKUP_REMOTE=r2://plasma-backups-test/plasma`:

| Run | Tool | Result |
| --- | --- | --- |
| `--tier daily` | rclone | set of 119,697,619 bytes in 45 s, remote sizes verified |
| `--tier weekly` | aws CLI | 119,697,619 bytes in 38 s; tender documents skipped (default) |
| `--tier daily`, `BACKUP_DAILY_KEEP=1`, `BACKUP_VERIFY_DOWNLOAD=1` | rclone | 47 s, remote SHA-256 verified by download; the older daily set removed, the weekly set untouched |
| wrong secret key | aws CLI | exit 1, `SignatureDoesNotMatch`, the failed object removed |

In all four runs the output contained none of the endpoint, bucket name, key id or secret
(`grep -c` = 0); errors read `s3://<bucket>/plasma/daily/…`. Known limit: the aws CLI v1
download to stdout stalled against the local test endpoint, so `BACKUP_VERIFY_DOWNLOAD=1` was
proven with rclone (the default tool). Tier, retention and tender-document rules are also covered
by `backend/test_r3_ops.py` against a `file://` remote.
