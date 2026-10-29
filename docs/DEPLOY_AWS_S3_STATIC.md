# Hosting the SemanticLift showcase on Amazon S3 (static website, no server)

This publishes a **read-only showcase** of SemanticLift as an S3 static website.
- **Pages:** every page works, including Product overview, the narrated demo video, Strategy & approach, the seven migration steps, Design review, Findings and the Audit trail.
- **Data:** a real run of the bundled sample Cognos estate, exported to files. There is no server, nothing to patch and almost nothing to pay.

Use it for a public demo, a sales or marketing site, or a link to share with prospects. For **real client migrations** use the full application ([DEPLOY_AWS_EC2.md](DEPLOY_AWS_EC2.md)): uploads, steward decisions, re-runs, sign-in and roles need its server.

| Works in the showcase | Switched off (shows a "read-only demo" notice) |
| --- | --- |
| All pages, charts, diagrams and filters, with the sample run's figures | Uploading an export, running or re-running the pipeline |
| Demo walkthrough video with chapters | Report, KPI and source decisions; object approval; finding updates |
| Downloads: design package (.zip), design workbook (.xlsx), findings, contracts, lineage | Creating or archiving projects; Git deploy; parity runs |
| Audit trail of the sample run, with its filters | Sign-in and roles; every visitor is a read-only viewer |

S3 website endpoints serve **HTTP only**. Browsers mark the site "Not secure", which is acceptable for a public demo that holds sample data and asks for nothing. For HTTPS you would need CloudFront or another HTTPS front end in front of the bucket. **Never publish a client's estate this way.**

## 1. Build the showcase

On any machine with Python 3.11+, Node 20+ and the repository:

```bash
pip install -e ".[dev]"
cd ui && npm ci && cd ..
python scripts/static/export_static.py            # -> dist-static/  (about 18 MB, most of it the demo video)
```

The script does three things:
1. Runs the sample estate through the real API on a throw-away project.
2. Saves the data for every page under `dist-static/data/`.
3. Builds the UI in static mode next to it.

To check it locally, run `python -m http.server 8080 --directory dist-static` and open http://localhost:8080.

## 2. Create the bucket and turn on website hosting

> Prefer clicking to typing? Steps 2–7 are also written for the AWS Management Console in [Using the AWS console instead of the CLI](#using-the-aws-console-instead-of-the-cli).

The commands use the AWS CLI v2 with credentials that can manage S3. Pick a globally unique bucket name and your region:

```bash
BUCKET=semanticlift-demo-<your-suffix>
REGION=eu-west-2

aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
  --create-bucket-configuration LocationConstraint="$REGION"   # in us-east-1, leave out --create-bucket-configuration

aws s3 website "s3://$BUCKET/" --index-document index.html --error-document index.html
```

## 3. Allow public read

A website bucket must be publicly readable. S3 blocks public access by default, both on the bucket and on the account.

1. Allow a public bucket policy on this bucket only (object ACLs stay blocked):

   ```bash
   aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
     BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=false,RestrictPublicBuckets=false
   ```

2. Check the account-level setting. If it shows `BlockPublicPolicy: true`, an account administrator must relax it, or use a dedicated account for public sites:

   ```bash
   aws s3control get-public-access-block --account-id "$(aws sts get-caller-identity --query Account --output text)"
   ```

3. Apply the read-only policy:

   ```bash
   cat > /tmp/semanticlift-policy.json <<EOF
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Sid": "PublicReadShowcase",
       "Effect": "Allow",
       "Principal": "*",
       "Action": "s3:GetObject",
       "Resource": "arn:aws:s3:::$BUCKET/*"
     }]
   }
   EOF
   aws s3api put-bucket-policy --bucket "$BUCKET" --policy file:///tmp/semanticlift-policy.json
   ```

**Restrict the audience (optional).** To show the showcase only inside your company network, add this condition to the statement. Visitors from other addresses then get 403 Forbidden. There is still no login.

```json
"Condition": { "IpAddress": { "aws:SourceIp": ["203.0.113.0/24", "198.51.100.10/32"] } }
```

## 4. Upload

Long-cache the fingerprinted assets, keep the data briefly cached, and never cache `index.html`, so updates show up immediately:

```bash
aws s3 sync dist-static/assets "s3://$BUCKET/assets" --delete \
  --cache-control "public, max-age=31536000, immutable"
aws s3 sync dist-static "s3://$BUCKET" --delete --exclude "assets/*" --exclude "index.html" \
  --cache-control "public, max-age=300"
aws s3 cp dist-static/index.html "s3://$BUCKET/index.html" \
  --cache-control "no-cache" --content-type "text/html; charset=utf-8"
```

The CLI sets each file's content type from its extension, including `video/mp4` for the demo and `application/json` for the data.

## 5. Open it

The address is the bucket's website endpoint. Depending on the region it is one of these forms:
- `http://<bucket>.s3-website-<region>.amazonaws.com`, for example `us-east-1`
- `http://<bucket>.s3-website.<region>.amazonaws.com`, for example `eu-west-2`

The exact URL is shown in the S3 console under the bucket's **Properties › Static website hosting**.

Check that:
- the Product overview opens, with the blue "Read-only demo" banner on each page
- the Demo walkthrough video plays with sound
- clicking a decision button such as **Keep** on page 1 shows the read-only notice
- **Deploy & validate › Design workbook** downloads a file

## 6. Your own domain (optional, still HTTP)

1. Name the bucket **exactly** after the host name, for example `demo.semanticlift.example.com`, and repeat steps 2–4 for it.
2. Point DNS at the website endpoint:
   - **Route 53:** create an **A record, Alias**, targeting the S3 website endpoint in the bucket's region.
   - **Other DNS providers:** create a **CNAME** from the host name to the endpoint host name, without `http://`.

HTTPS on a custom domain is not possible with S3 alone.

## 7. Update or remove

- **Update** after a new release or a new demo recording: rebuild with step 1, then repeat step 4. `--delete` removes files that no longer exist.
- **Remove:** `aws s3 rb "s3://$BUCKET" --force` deletes every object and the bucket.

## 8. Cost

Storage is about 18 MB, which costs fractions of a cent per month. Requests are cheap. The main cost is **data transfer out**: each full view of the demo video is about 9 MB, so 1,000 video views is about 9 GB of transfer, billed at the standard S3 internet egress rate after the monthly free allowance. Use an AWS Budget alarm if the link may circulate widely.

## Using the AWS console instead of the CLI

The same result, done entirely in the browser at https://console.aws.amazon.com. You still build `dist-static/` once on your machine (step 1); everything after that is clicks.

### A. Create the bucket

1. Open **S3** and choose **Create bucket**.
2. Set these options:
   - **Bucket type:** *General purpose*.
   - **Bucket name:** unique, for example `semanticlift-demo-yourcompany`. For your own domain, use the exact host name, such as `demo.semanticlift.example.com`.
   - **AWS Region:** the region you want, shown at the top right.
   - **Object Ownership:** leave *ACLs disabled (recommended)*.
3. Under **Block Public Access settings for this bucket**:
   - Untick the two **bucket policy** boxes: *Block public access … granted through new public bucket or access point policies* and *… through any public bucket or access point policies*.
   - Leave the two **ACL** boxes ticked.
   - Tick the acknowledgement that the bucket may become public.
4. Leave **Bucket Versioning** off and **Default encryption** on SSE-S3, then choose **Create bucket**.

If you later get *Access denied* while saving the policy, open **Block Public Access settings for this account** in the S3 left menu. Public policies are blocked for the whole account; an administrator must allow them, or use a separate account for public sites.

### B. Upload the files

1. Open the bucket and choose **Upload**.
2. Open `dist-static/` on your computer, select **everything inside it** (`index.html`, `assets`, `data`, `demo`), and drag it onto the upload area.

   Do not drag the `dist-static` folder itself, and do not use **Add folder** on it: either creates a `dist-static/` prefix, and the site would then live at `…/dist-static/index.html`.
3. Check that the list shows about 190 files, then choose **Upload** and wait for *Upload succeeded*. The console sets each file's type from its extension (`video/mp4`, `application/json`, `text/html`).

### C. Turn on static website hosting

1. Open the bucket's **Properties** tab, scroll to **Static website hosting**, and choose **Edit**.
2. Choose **Enable**, then **Host a static website**.
3. Set **Index document** to `index.html` and **Error document** to `index.html`.
4. Choose **Save changes**.
5. Back in **Properties › Static website hosting**, copy the **Bucket website endpoint** (`http://…s3-website…amazonaws.com`). This is the site's address.

### D. Make it readable

1. Open the **Permissions** tab, go to **Bucket policy**, and choose **Edit**.
2. Paste the policy below, replacing `YOUR-BUCKET-NAME`, and choose **Save changes**:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Sid": "PublicReadShowcase",
       "Effect": "Allow",
       "Principal": "*",
       "Action": "s3:GetObject",
       "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/*"
     }]
   }
   ```

   To show it only inside your company network, add `"Condition": { "IpAddress": { "aws:SourceIp": ["203.0.113.0/24"] } }` after `"Resource"`, with your office ranges.
3. The bucket now shows the red **Publicly accessible** label, as expected for a website.

### E. Stop browsers caching the start page (recommended)

1. On the **Objects** tab, tick `index.html` and choose **Actions › Edit metadata**.
2. Choose **Add metadata**: **Type** *System defined*, **Key** `Cache-Control`, **Value** `no-cache`.
3. Choose **Save changes**.

New releases then show up as soon as they are uploaded.

### F. Check it

Open the **Bucket website endpoint** from C5, then run the checks in step 5 above: read-only banner, demo video with sound, read-only notice on **Keep**, and the workbook download.

### G. Your own domain (optional, still HTTP)

1. The bucket must be named exactly as the host name (A2).
2. In **Route 53 › Hosted zones**, open your domain and choose **Create record**.
3. Enter the subdomain in **Record name**, for example `demo.semanticlift`, keep **Record type** *A*, and turn on **Alias**.
4. Under **Route traffic to**, choose **Alias to S3 website endpoint**, then your region, then your bucket.
5. Choose **Create records**.

For DNS outside Route 53, add a **CNAME** to the endpoint host name, without `http://`.

### H. Update, budget and removal

- **Update:**
  1. Rebuild with step 1.
  2. In the bucket, tick the `assets` folder and choose **Delete**, so old script files do not pile up.
  3. Upload the new contents of `dist-static/` as in B. Files with the same name are replaced.
  4. Repeat E for the new `index.html`.
- **Budget alarm:**
  1. Open **Billing and Cost Management › Budgets** and choose **Create budget**.
  2. Pick the *Monthly cost budget* template, set an amount such as 10 USD, and enter an email address.
- **Remove:**
  1. In the S3 bucket list, select the bucket and choose **Empty**, then confirm.
  2. Choose **Delete** and type the bucket name.
  3. If you made one, delete the Route 53 record.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `403 Forbidden` on every page | Block Public Access is still on, for the bucket or the account (step 3), or the bucket policy is missing or names the wrong bucket |
| `404 Not Found` at the endpoint | Website hosting is not enabled (step 2), or you opened the REST URL (`<bucket>.s3.amazonaws.com`) instead of the **website** endpoint |
| Page loads but a section says "Not available in the demo" | `data/` was not uploaded completely; repeat step 4 |
| Video does not play | Confirm `demo/semanticlift-demo.mp4` exists in the bucket with content type `video/mp4` |
| Old version still showing | The browser cached the data for up to 5 minutes; reload, or lower `max-age` in step 4 |
