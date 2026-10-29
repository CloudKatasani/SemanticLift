# Hosting SemanticLift on AWS EC2

This guide runs SemanticLift on one EC2 instance with **no sign-in** and **automatic HTTPS**:
- **Caddy** in front of the app obtains and renews a Let's Encrypt certificate by itself.
- **sslip.io** gives you a free host name that points at your instance's IP. For example, Elastic IP `3.121.45.67` becomes `https://3-121-45-67.sslip.io`, with no domain to buy and no DNS to set up.

Everything runs in Docker, and all state lives on a dedicated EBS volume. The files it refers to are in [`deploy/aws-ec2/`](../deploy/aws-ec2/). Allow about 45 minutes.

```
 browser ──HTTPS──► Caddy :443 (Let's Encrypt cert for <ip>.sslip.io) ──► SemanticLift container :8000
                       │                                                       │
                 /data/caddy (certificates)                     /data/semanticlift (EBS volume)
                                                                projects, decisions, audit trail, packages
```

> **Read this first: no sign-in means anyone can use it.**
> - **No credentials:** every visitor is an administrator. They can see every project, upload, run, change decisions, archive projects and download packages. The audit trail shows every user as `local`.
> - **The address is not secret.** sslip.io names are derived from the IP address, and every certificate is published in public certificate-transparency logs within minutes. Scanners will find the site.
> - **Use it only for demos, pilots and sample or non-confidential exports.** Do not upload a client's real estate to an open instance.
> - **Recommended:** limit who can reach it with the network allowlist in step 8. It needs no credentials. Stop the instance when nobody is using it.
> - For client work, turn sign-in on ([step 12](#12-adding-sign-in-later)). Caddy and sslip.io keep working unchanged.

SemanticLift only needs metadata exports, never business data. Deployments to Snowflake still run from Git through CI; the instance only writes a Git branch.

## 1. Before you start

| Decision | Recommendation |
| --- | --- |
| Region | Your nearest region, or the client's data-residency region |
| Instance | `t3.large` (2 vCPU, 8 GiB) for estates of up to a few thousand reports; `m6i.xlarge` (4 vCPU, 16 GiB) for larger ones |
| OS | Ubuntu Server 24.04 LTS (64-bit x86) |
| Disk | 30 GiB gp3 root volume, plus a separate encrypted **gp3 data volume of 20–100 GiB** mounted at `/data` |
| Network | A **public** subnet with an **Elastic IP**. Let's Encrypt must reach ports 80 and 443 to issue the certificate. |
| Host name | `<elastic-ip-with-dashes>.sslip.io`. It needs no setup; sslip.io answers DNS for any IP written this way. |
| Sign-in | None (open access). Add it later if needed. |

Run **one instance per deployment**. State is file-based, which is safe for many projects on one instance but not for several instances sharing one disk.

## 2. AWS resources

1. **IAM role for the instance.** Attach `AmazonSSMManagedInstanceCore` so you can connect with Session Manager instead of SSH. Add `CloudWatchAgentServerPolicy` for CloudWatch logs, and `s3:PutObject` on a backup bucket for S3 backups (step 9).
2. **Security group:**

   | Direction | Port | Source | Why |
   | --- | --- | --- | --- |
   | Inbound | 80/tcp | `0.0.0.0/0` | Let's Encrypt validation and the HTTP → HTTPS redirect |
   | Inbound | 443/tcp | `0.0.0.0/0` | The site |
   | Inbound | 443/udp | `0.0.0.0/0` | HTTP/3 (optional) |
   | Outbound | 443 | `0.0.0.0/0` | Package installs, image builds, certificate requests |

   Do not open 22 if you use Session Manager, and never open 8000.

   Let's Encrypt validates from addresses that are not published, so 80 and 443 must stay open to everyone for issuance and the automatic renewals about every 60 days. To keep strangers out anyway, use the Caddy allowlist in step 8 rather than the security group.
3. **Launch the instance.**
   - Choose Ubuntu 24.04, the instance type above, the IAM role and the security group, in a public subnet.
   - Under *Advanced details*, set **IMDSv2: required**.
   - Add the second EBS volume (gp3, **encrypted**).
4. **Elastic IP.** Allocate one and associate it with the instance. The sslip.io name is built from this IP, so it must not change.

## 3. Prepare the instance

Connect with Session Manager (EC2 console › select the instance › **Connect** › **Session Manager**) or SSH, then:

```bash
sudo apt-get update && sudo apt-get -y upgrade
sudo apt-get install -y docker.io docker-compose-v2 git
sudo usermod -aG docker ubuntu && newgrp docker      # run docker without sudo
docker compose version                               # should print v2.x
```

Format and mount the data volume. The device name varies, so check it with `lsblk`; on Nitro instances it is usually `/dev/nvme1n1`.

```bash
lsblk
sudo mkfs.xfs /dev/nvme1n1                           # only the first time - this erases the volume
sudo mkdir -p /data
echo "UUID=$(sudo blkid -s UUID -o value /dev/nvme1n1) /data xfs defaults,nofail 0 2" | sudo tee -a /etc/fstab
sudo mount -a && df -h /data
```

## 4. Get the application

```bash
cd ~ && git clone https://github.com/CloudKatasani/SemanticLift.git && cd SemanticLift
sudo mkdir -p /data/semanticlift/config /data/caddy/data /data/caddy/config
sudo cp config/*.yaml /data/semanticlift/config/     # estate configurations offered in the UI; add client ones here
cd deploy/aws-ec2
cp semanticlift.env.example semanticlift.env          # the default has no sign-in lines = open access
docker compose build                                  # builds the UI and the API image (a few minutes)
```

The app container runs as an unprivileged user, so give that user ownership of its data folder:

```bash
docker compose run --rm --no-deps --entrypoint id semanticlift   # e.g. uid=1000(semlift)
sudo chown -R 1000:1000 /data/semanticlift                       # use the uid printed above
```

Check that `semanticlift.env` sets none of `SEMLIFT_USERS_FILE`, `SEMLIFT_TRUST_PROXY_HEADERS` or `SEMLIFT_API_TOKEN`. With any of them set, SemanticLift asks for credentials.

```bash
grep -E '^(SEMLIFT_USERS_FILE|SEMLIFT_TRUST_PROXY_HEADERS|SEMLIFT_API_TOKEN)=' semanticlift.env || echo "open access: OK"
```

## 5. Your sslip.io address

Build the host name from the instance's public IP (the Elastic IP), replacing dots with dashes:

```bash
TOKEN=$(curl -sX PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
IP=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4)
HOST="${IP//./-}.sslip.io" && echo "$HOST"            # e.g. 3-121-45-67.sslip.io
getent hosts "$HOST"                                  # must print the same IP

cp caddy.env.example caddy.env
sed -i "s/^SITE_HOST=.*/SITE_HOST=$HOST/" caddy.env   # UPSTREAM stays semanticlift:8000
cat caddy.env
```

`3.121.45.67.sslip.io` (with dots) also resolves, but the dashed form gives a cleaner single-label name. Use whichever you put in `SITE_HOST` consistently.

## 6. Start it

```bash
docker compose up -d
docker compose ps                                    # semanticlift "healthy", caddy "running"
curl -s http://127.0.0.1:8000/api/health             # {"status":"ok", ... "auth_mode":"open"}
docker compose logs -f caddy                         # wait for "certificate obtained successfully", then Ctrl+C
```

Caddy requests the certificate on first start. That takes 10–60 seconds, and Caddy renews it automatically. Certificates and keys are kept in `/data/caddy`, so rebuilds and restarts reuse them. Both containers restart by themselves after crashes and reboots.

## 7. Open it

1. Browse to `https://<your-host>`, for example `https://3-121-45-67.sslip.io`. The padlock should show a valid Let's Encrypt certificate. `http://` redirects to `https://`.
2. There is no sign-in screen: you land on **Product overview**. The foot of the menu shows `local` with an **open mode** label.
3. Open **Client projects** under Administration, create a project and choose its estate configuration.
4. On **Upload & run**, upload the sample `samples/Cognos Lineage Input.zip` from the repository and run it. Then work through **Strategy & approach** and pages 1–7.

## 8. Optional: let only your networks in, still without credentials

To stop strangers who find the address, allow only your office, VPN or home IP ranges in Caddy:

1. Edit `deploy/aws-ec2/Caddyfile` and uncomment the two lines starting `@outsiders` and `respond @outsiders`.
2. Replace the example ranges with yours. Separate them with spaces and use CIDR notation, e.g. `203.0.113.0/24 198.51.100.10/32`. To find your current address, open `https://checkip.amazonaws.com` from your own machine.
3. Apply the change:

   ```bash
   docker compose restart caddy
   ```

Everyone else then gets `403`, and certificate renewals keep working. Do this filtering in Caddy rather than in the security group: Let's Encrypt must still reach ports 80 and 443 to renew.

## 9. Backups

All state is under `/data`: projects, decisions, audit trails and generated packages in `/data/semanticlift`, and certificates in `/data/caddy`.

- **EBS snapshots (recommended):** in Amazon Data Lifecycle Manager, create a policy that snapshots the data volume daily and keeps 7–30 copies.
- **S3 copy (optional):** run this from a nightly cron entry. It needs `awscli` and the S3 permission on the instance role.

  ```bash
  aws s3 sync /data/semanticlift s3://<backup-bucket>/semanticlift/ --sse aws:kms --delete
  ```

- **Restore:** restore the snapshot to a new volume, mount it at `/data`, then run `docker compose up -d`.

## 10. Logs, monitoring and cost

- **Logs:** `docker compose logs -f semanticlift` shows every API call with project, status, duration and request ID; `docker compose logs -f caddy` shows certificate and access events. To ship them to CloudWatch, install the CloudWatch agent for `/var/lib/docker/containers/*/*.log`, or switch the compose logging driver to `awslogs`.
- **Health:** watch `https://<your-host>/api/health`, for example with a Route 53 health check or a CloudWatch Synthetics canary.
- **Disk:** add a CloudWatch alarm on `/data` usage above 80%.
- **Cost:** you pay for the instance while it runs, the EBS volumes and the Elastic IP. AWS charges for public IPv4 addresses, including Elastic IPs, whether or not the instance runs. Stop the instance between demos; the address and data stay the same.

## 11. Upgrades

```bash
cd ~/SemanticLift && git pull
cd deploy/aws-ec2 && docker compose build && docker compose up -d
docker image prune -f
```

Data on `/data` is untouched by upgrades. Take a snapshot first if the release notes mention changes to stored data.

## 12. Adding sign-in later

The same Caddy and sslip.io set-up works with sign-in. Choose one option, then run `docker compose up -d` again.

**Personal tokens.**
1. Generate a token and its hash for each user:

   ```bash
   docker compose run --rm --no-deps semanticlift semlift token    # repeat per user
   ```

2. Create `/data/semanticlift/users.yaml`:

   ```yaml
   users:
     - name: Priya Shah
       token_sha256: <hash>
       roles: [admin]
     - name: Sam Steward
       token_sha256: <hash>
       projects: {"acme-*": [steward, analyst]}
   ```

3. Make the file readable by the container only, and turn sign-in on:

   ```bash
   sudo chown 1000:1000 /data/semanticlift/users.yaml && sudo chmod 600 /data/semanticlift/users.yaml
   ```

   Then uncomment `SEMLIFT_USERS_FILE=/data/users.yaml` in `semanticlift.env`.

Each person pastes their token on the sign-in screen. Decisions and the audit trail then carry real names.

**Single sign-on** (Microsoft Entra ID, Okta, Amazon Cognito, Google and others):
1. Register a web application in your identity provider with redirect URI `https://<your-host>/oauth2/callback`, and include group claims.
2. Configure oauth2-proxy: `cp oauth2-proxy.env.example oauth2-proxy.env` and fill it in.
3. In `semanticlift.env`, uncomment `SEMLIFT_TRUST_PROXY_HEADERS=1` and `SEMLIFT_USERS_FILE=/data/users.yaml`.
4. Map identity-provider groups to roles in `users.yaml`:

   ```yaml
   groups:
     semanticlift-admins: {"*": [admin]}
     acme-data-stewards:  {"acme-*": [steward]}
   ```

5. In `caddy.env`, set `UPSTREAM=oauth2-proxy:4180`.
6. Start with the SSO profile: `docker compose --profile sso up -d`.

Caddy strips identity headers sent by browsers, and oauth2-proxy sets them after sign-in. For the full role list see [OPERATIONS.md](OPERATIONS.md).

## 13. Optional: deploying generated objects to Git

**Deploy & validate** writes approved objects to a Git branch and can push it. To push from the instance:
1. Create a deploy key or a machine-user token for the target repository.
2. Add it, with `known_hosts`, to a folder mounted read-only at `/home/semlift/.ssh` (add the volume to the `semanticlift` service).
3. Enter the remote in the **Remote** field on **Deploy & validate**.

CI in that repository deploys to Snowflake.

Live Snowflake compile checks and parity runs from the UI use the connector's browser-based sign-in, which cannot work on a headless server. Leave `SEMLIFT_SNOWFLAKE_*` unset and run those checks in CI.

## 14. Checklist

- [ ] The site shows a valid certificate at `https://<ip-with-dashes>.sslip.io`, and `http://` redirects to it.
- [ ] Only demo, pilot or sample exports are uploaded, because the site is open to anyone who can reach it.
- [ ] The Caddy allowlist (step 8) lists your networks, or you have consciously decided it stays fully public.
- [ ] Ports 22 and 8000 are closed in the security group; 80 and 443 are open for Let's Encrypt.
- [ ] IMDSv2 is required; the data volume and snapshots are encrypted.
- [ ] An EBS snapshot policy is active.
- [ ] The instance is stopped when not in use, and OS patches are applied monthly (`sudo apt-get update && sudo apt-get -y upgrade`).

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Browser warns about the certificate, or Caddy logs show `challenge failed` / `timeout` | Ports 80 **and** 443 must be open to `0.0.0.0/0` in the security group; `SITE_HOST` must match the Elastic IP (`getent hosts $SITE_HOST`); the instance must be in a public subnet with an internet gateway |
| Caddy logs `too many certificates` / `rateLimited` | Let's Encrypt rate limits after repeated failed or duplicate requests. Fix the cause, keep `/data/caddy` (do not delete it), and wait for the period in the message |
| Site worked, then broke after a stop/start | The public IP changed because no Elastic IP is attached. Attach one and update `SITE_HOST` in `caddy.env`, then run `docker compose up -d` |
| `502 Bad Gateway` | `docker compose ps`; the `semanticlift` container must be healthy (`curl http://127.0.0.1:8000/api/health`) |
| A sign-in screen appears although you want open access | One of `SEMLIFT_USERS_FILE`, `SEMLIFT_TRUST_PROXY_HEADERS` or `SEMLIFT_API_TOKEN` is set in `semanticlift.env`. Comment it out, then run `docker compose up -d` |
| You get `403` from your own network | Your IP is not in the Caddy allowlist (step 8); check it at `https://checkip.amazonaws.com` |
| Container restarts in a loop with `Permission denied` under `/data` | `sudo chown -R <uid>:<uid> /data/semanticlift` (step 4) |
| Upload fails with `413` | The Caddyfile allows 500 MB; raise `max_size` and run `docker compose restart caddy` |
| An estate configuration is missing from the drop-down | Copy the YAML into `/data/semanticlift/config` and run `docker compose up -d --force-recreate semanticlift` |
