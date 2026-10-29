# Operating SemanticLift for multiple clients

## Deployment

For a step-by-step install on a single AWS EC2 instance (Docker, nginx with HTTPS, single sign-on through oauth2-proxy, EBS backups), see [DEPLOY_AWS_EC2.md](DEPLOY_AWS_EC2.md). A read-only showcase with no server can be published to an S3 static website: [DEPLOY_AWS_S3_STATIC.md](DEPLOY_AWS_S3_STATIC.md).

```bash
docker build -t semanticlift .
docker run -p 8000:8000 -v $PWD/data:/data \
  -e SEMLIFT_USERS_FILE=/data/users.yaml semanticlift
```

The container keeps all client projects under `SEMLIFT_HOME` (default `/data/home`). Back up that folder: it holds every project's uploads, decisions, audit trail and generated packages. Deployment to Snowflake always runs from Git through CI, never from the container.

Run one replica. State is file-based with atomic writes. Running several replicas needs the shared store described in the roadmap ([PRODUCT_REVIEW.md](PRODUCT_REVIEW.md)).

| Variable | Purpose |
| --- | --- |
| `SEMLIFT_HOME` | Root for the project registry and all client projects |
| `SEMLIFT_WORKSPACE` | Optional legacy single workspace; shown as project `default` |
| `SEMLIFT_CONFIG_DIR` | Folder of estate configurations offered when creating a project or running |
| `SEMLIFT_USERS_FILE` | Users, personal tokens and group → role mappings (see below) |
| `SEMLIFT_TRUST_PROXY_HEADERS` | `1` to accept identity from an authenticating reverse proxy |
| `SEMLIFT_API_TOKEN` | Legacy shared administrator token |
| `SEMLIFT_MAX_CONCURRENT_RUNS` | Pipeline runs executed at once across projects (default 2; the rest queue) |
| `SEMLIFT_ENV` | Label shown in the UI |

## Sign-in options

Pick one per deployment:

1. **Single sign-on (recommended).** Put the app behind an authenticating proxy such as oauth2-proxy, an API gateway, or an ingress with OIDC or SAML, and set `SEMLIFT_TRUST_PROXY_HEADERS=1`. The proxy must set `X-Forwarded-Email` (or `X-Forwarded-User`) and `X-Forwarded-Groups`. Only enable this when the app cannot be reached except through the proxy, because these headers are trusted as-is.
2. **Personal tokens.** Generate one per user with `semlift token`. Give the token to the user and store only its `token_sha256` in the users file. Users paste the token on the sign-in screen.
3. **Shared token** (`SEMLIFT_API_TOKEN`). One administrator identity; suitable for automation only.
4. **Open mode.** Nothing configured. Everyone is an administrator; the UI shows "open mode". Use for local evaluation only.

The users file is re-read when it changes, so access can be granted or removed without a restart:

```yaml
users:
  - name: Priya Shah
    email: priya@acme.com
    token_sha256: 5e884898da2804...        # omit when signing in through SSO
    roles: [viewer]                        # roles in every project
    projects: {"acme-*": [steward, approver]}
groups:                                    # IdP group -> {project pattern: roles}
  semanticlift-admins: {"*": [admin]}
  acme-data-stewards: {"acme-*": [steward]}
  acme-platform-team: {"acme-*": [approver, deployer]}
```

## Roles

Every role includes `viewer`, and `admin` includes every role. Roles apply per project pattern.

| Role | Can |
| --- | --- |
| viewer | Read every page; download the package, workbook and findings |
| analyst | Upload exports; run and re-run the pipeline |
| steward | Report, KPI and source decisions; finding owner and status; accept LLM suggestions |
| approver | Approve, edit or reject generated objects; bulk-approve |
| deployer | Commit approved objects to Git; run parity checks |
| admin | Create, archive and restore projects; change settings |

For regulated clients, set `governance.four_eyes: true` in the estate configuration. An approver then cannot approve DDL they edited themselves.

## Onboarding a new client

1. Copy `config/template_estate.yaml` to `config/<client>_estate.yaml`. Fill in package affixes, product names, target database and RAW schema routing, KPI concepts and the industry glossary. Check it with `semlift config check config/<client>_estate.yaml`.
2. Create the project as an admin, either on **Client projects** in the UI or with `semlift projects create "Cognos wave 1" --client "Acme" -c config/acme_estate.yaml`. The project id is derived from client and name, e.g. `acme-cognos-wave-1`.
3. Grant access: add the client's people, or their IdP groups, to the users file with the pattern `acme-*`.
4. An analyst uploads the Cognos export on **Upload & run** and starts the run. It runs in the background, and any configuration warnings are shown when it finishes.
5. Stewards and approvers work through pages 1–7 and Design review. Every change is recorded on **Audit trail**, which can be exported as CSV for the client's governance team.
6. When the engagement ends, archive the project. It becomes read-only and is hidden from the default list.

## Monitoring

- `GET /api/health` returns status, version, environment and the sign-in mode. The Docker `HEALTHCHECK` uses it.
- Every API call is logged with method, path, status, duration, user, project and request ID. The request ID is returned as `X-Request-ID`; send it with support requests.
- Failed background runs keep their error on the job (`GET /api/jobs/{id}`) and in the server log.
