# Hosting SemanticLift on AWS EC2

This guide runs SemanticLift on one EC2 instance. The app runs in Docker, nginx sits in front of it for HTTPS, and all state lives on a dedicated EBS volume. The files it refers to are in [`deploy/aws-ec2/`](../deploy/aws-ec2/). Allow about an hour for a first install.

```
 users ──HTTPS──► nginx :443 ──► (optional) oauth2-proxy :4180 ──► SemanticLift container :8000
                     │                                                   │
                  TLS cert                                    /data/semanticlift  (EBS volume)
                                                              projects, decisions, audit trail, packages
```

SemanticLift only needs metadata exports, never business data. Deployments to Snowflake still run from Git through CI; the instance only writes a Git branch.

## 1. Before you start

| Decision | Recommendation |
| --- | --- |
| Region | The client's data-residency region |
| Instance | `t3.large` (2 vCPU, 8 GiB) for estates of up to a few thousand reports; `m6i.xlarge` (4 vCPU, 16 GiB) for larger estates or several clients running at once |
| OS | Ubuntu Server 24.04 LTS (64-bit x86) |
| Disk | 30 GiB gp3 root volume, plus a separate encrypted **gp3 data volume of 50–100 GiB** mounted at `/data` |
| Network | A private subnet reached over VPN or Direct Connect is best. A public subnet is fine if the security group only admits your corporate IP ranges. |
| DNS name | For example `semanticlift.example.com`, pointing at the instance's Elastic IP or at a load balancer |
| Sign-in | Single sign-on through oauth2-proxy (recommended), or personal tokens |

Run **one instance per deployment**. State is file-based, which is safe for many client projects on a single instance but not for several instances sharing one disk (see the roadmap in [PRODUCT_REVIEW.md](PRODUCT_REVIEW.md)).

## 2. AWS resources

1. **IAM role for the instance.** Attach `AmazonSSMManagedInstanceCore` so you can use Session Manager instead of SSH. Add `CloudWatchAgentServerPolicy` if logs should go to CloudWatch, and `s3:PutObject` on a backup bucket if you will use S3 backups (step 9).
2. **Security group.**
   - Inbound: allow 443 from your corporate ranges or the load balancer. Allow 80 only while Let's Encrypt validates the certificate.
   - Do not open 22 if you use Session Manager.
   - Outbound: allow 443 for package installs, image builds and, if you deploy to Git, your Git host.
3. **Launch the instance.**
   - Choose Ubuntu 24.04, the instance type above, the IAM role and the security group.
   - Under *Advanced details*, set **IMDSv2: required**.
   - Add the second EBS volume (gp3, **encrypted**, KMS key of your choice).
4. **Elastic IP** (public subnet only): allocate one, associate it with the instance, and point the DNS name at it.

## 3. Prepare the instance

Connect with Session Manager (EC2 console › Connect › Session Manager) or SSH, then:

```bash
sudo apt-get update && sudo apt-get -y upgrade
sudo apt-get install -y docker.io docker-compose-v2 git nginx certbot python3-certbot-nginx
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
sudo mkdir -p /data/semanticlift/config
sudo cp config/*.yaml /data/semanticlift/config/     # estate configurations offered in the UI; add client ones here
cd deploy/aws-ec2
cp semanticlift.env.example semanticlift.env
docker compose build                                 # builds the UI and the API image (a few minutes)
```

The container runs as an unprivileged user, so give that user ownership of the data folder:

```bash
docker compose run --rm --entrypoint id semanticlift  # e.g. uid=1000(semlift)
sudo chown -R 1000:1000 /data/semanticlift           # use the uid printed above
```

## 5. Sign-in

Never run a shared deployment in open mode, where everyone is an administrator. Choose one option.

### Option A: personal tokens (quickest)

```bash
docker compose run --rm semanticlift semlift token    # prints a token and its hash; repeat per user
sudo nano /data/semanticlift/users.yaml
```

```yaml
users:
  - name: Priya Shah
    email: priya@example.com
    token_sha256: <hash printed above>
    roles: [admin]
  - name: Sam Steward
    token_sha256: <hash>
    projects: {"acme-*": [steward, analyst]}
```

```bash
sudo chown 1000:1000 /data/semanticlift/users.yaml && sudo chmod 600 /data/semanticlift/users.yaml   # readable by the container only
```

Give each person their token through a secure channel; they paste it on the sign-in screen. `semanticlift.env` already sets `SEMLIFT_USERS_FILE=/data/users.yaml`. The file is re-read when it changes, so you can grant or remove access without a restart.

### Option B: single sign-on (recommended for client teams)

1. Register a web application in your identity provider (Microsoft Entra ID, Okta, Amazon Cognito, Google and others) with redirect URI `https://<your-host>/oauth2/callback`, and include group claims.
2. Configure oauth2-proxy: `cp oauth2-proxy.env.example oauth2-proxy.env`, then fill in the issuer, client ID and secret, a cookie secret and your email domain.
3. In `semanticlift.env`, uncomment `SEMLIFT_TRUST_PROXY_HEADERS=1`.
4. Map identity-provider groups to SemanticLift roles in `/data/semanticlift/users.yaml`:

   ```yaml
   groups:
     semanticlift-admins:   {"*": [admin]}
     acme-data-stewards:    {"acme-*": [steward]}
     acme-platform-team:    {"acme-*": [approver, deployer]}
   ```

5. In the nginx site (step 7), point `proxy_pass` at `http://127.0.0.1:4180` instead of `:8000`.
6. Start with the SSO profile: `docker compose --profile sso up -d`.

With header trust on, SemanticLift believes the identity headers it receives. Make sure the app is only reachable through nginx and oauth2-proxy. The compose file binds it to `127.0.0.1`, and the nginx site strips any identity headers a browser sends.

## 6. Start the app

```bash
docker compose up -d                          # or: docker compose --profile sso up -d
docker compose ps                             # STATUS should become "healthy"
curl -s http://127.0.0.1:8000/api/health      # {"status":"ok", ... "auth_mode":"users"}
```

The container restarts by itself after crashes and reboots (`restart: unless-stopped`).

## 7. HTTPS with nginx

```bash
sudo cp nginx-semanticlift.conf /etc/nginx/sites-available/semanticlift
sudo sed -i 's/semanticlift.example.com/<your-host>/' /etc/nginx/sites-available/semanticlift
sudo ln -s /etc/nginx/sites-available/semanticlift /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d <your-host>           # obtains the certificate, adds HTTPS and the redirect, renews automatically
```

The site allows uploads of up to 500 MB and long-running requests; adjust `client_max_body_size` if your exports are larger.

**Private subnet or no public DNS:** Let's Encrypt cannot reach the instance. Use one of these instead:
- an internal certificate from your company's certificate authority, configured in the nginx site
- an **Application Load Balancer** with a certificate from AWS Certificate Manager. Forward HTTPS to the instance on port 80, and allow inbound 80 on the instance only from the load balancer's security group.

The load balancer's built-in OIDC sign-in passes identity in `x-amzn-oidc-*` headers, which SemanticLift does not read. Keep oauth2-proxy for sign-in behind the load balancer.

## 8. First login and check

1. Open `https://<your-host>`. You should see the sign-in screen, or be sent to your identity provider.
2. As an admin, open **Client projects** under Administration, create a project and choose its estate configuration.
3. On **Upload & run**, upload the sample `samples/Cognos Lineage Input.zip` from the repository and run it. It takes a few seconds. Then work through the Strategy page and pages 1–7.
4. Check **Audit trail**: every action should show your name.

## 9. Backups

All state is under `/data/semanticlift`: projects, decisions, audit trails, generated packages and `users.yaml`.

- **EBS snapshots (recommended):** in Amazon Data Lifecycle Manager, create a policy that snapshots the data volume daily and keeps 14–30 copies. Writes are atomic, so snapshots are consistent.
- **S3 copy (optional, in addition):** run this from a nightly cron entry on the host. It needs `awscli` and the S3 permission on the instance role.

  ```bash
  aws s3 sync /data/semanticlift s3://<backup-bucket>/semanticlift/ --sse aws:kms --delete
  ```

- **Restore:** restore the snapshot to a new volume, mount it at `/data`, then run `docker compose up -d`.

## 10. Logs and monitoring

- **Application log:** `docker compose logs -f semanticlift`. Every API call is logged with user, project, status, duration and request ID. Users see the request ID as `X-Request-ID`.
- **CloudWatch Logs:** either install the CloudWatch agent to ship `/var/lib/docker/containers/*/*.log`, or switch the compose logging driver to `awslogs` (with `awslogs-region` and `awslogs-group`). Either way the instance role needs CloudWatch Logs permissions.
- **Health checks:** watch `/api/health`. The container's built-in health check uses it, and you can add a Route 53 health check or CloudWatch Synthetics canary on `https://<your-host>/api/health`.
- **Disk:** add a CloudWatch alarm on `/data` usage above 80%.

## 11. Optional: deploying generated objects to Git

**Deploy & validate** writes approved objects to a Git branch and can push it. To push from the instance:
1. Create a deploy key or a machine-user token for the target repository.
2. Make it available to the container user: mount a `.ssh` folder with the key and `known_hosts` read-only at `/home/semlift/.ssh` by adding a volume in the compose file.
3. Enter the remote (for example `git@github.com:org/semantic-layer.git`) in the **Remote** field on **Deploy & validate**. It is saved for later deployments.

CI in that repository then deploys to Snowflake; the instance never connects to Snowflake to change anything.

Live Snowflake compile checks and parity runs from the UI use the connector's browser-based sign-in, which cannot work on a headless server. Leave `SEMLIFT_SNOWFLAKE_*` unset on EC2 and run those checks in CI.

## 12. Upgrades

```bash
cd ~/SemanticLift && git pull
cd deploy/aws-ec2 && docker compose build && docker compose up -d     # add --profile sso if used
docker image prune -f
```

Data on `/data` is untouched by upgrades. Take a snapshot first if the release notes mention changes to stored data.

## 13. Security checklist

- [ ] Sign-in is personal tokens or SSO. `/api/health` reports `auth_mode` `users` or `proxy`, never `open`.
- [ ] The security group admits 443 only from known ranges or the load balancer. Port 8000 is not open; the app is bound to `127.0.0.1`.
- [ ] IMDSv2 is required; the data volume and snapshots are encrypted.
- [ ] Access is through Session Manager; no SSH key pairs are shared.
- [ ] `semanticlift.env` and `oauth2-proxy.env` are readable only by the admin account (`chmod 600`), `users.yaml` only by the container user. None of them is committed, and `users.yaml` holds token hashes, never tokens.
- [ ] EBS snapshot policy is active, and a restore has been tested once.
- [ ] OS patches: `sudo apt-get update && sudo apt-get -y upgrade` monthly, or enable `unattended-upgrades`.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Browser shows 502 Bad Gateway | `docker compose ps`; whether the container is healthy; `curl http://127.0.0.1:8000/api/health` on the host |
| Container restarts in a loop with `Permission denied` under `/data` | `sudo chown -R <uid>:<uid> /data/semanticlift` (step 4) |
| Upload fails with 413 | Raise `client_max_body_size` in the nginx site, then `sudo systemctl reload nginx` |
| Everyone gets "sign in required" behind SSO | Check `SEMLIFT_TRUST_PROXY_HEADERS=1` is set, that nginx points at `:4180`, and the oauth2-proxy logs |
| SSO users see no projects | Their groups are not in the `groups:` section of `users.yaml`, or the group claim is missing (`OAUTH2_PROXY_OIDC_GROUPS_CLAIM`) |
| An estate configuration is missing from the drop-down | Copy the YAML into `/data/semanticlift/config` and recreate the container (`docker compose up -d --force-recreate`) |
