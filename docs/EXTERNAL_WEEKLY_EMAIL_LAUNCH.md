# External Weekly Email Launch

This is a separate, opt-in audience path built on top of the existing weekly email renderer. The internal team segment and its Monday workflow remain unchanged.

## Safety model

- Customer contact files live under `data/private/` and are ignored by Git.
- Imports require an auditable consent status, source, and date.
- Invalid, duplicate, unsubscribed, bounced, complained, and unconsented rows are rejected.
- External campaigns require an explicit approval recorded in their manifest.
- External campaigns require `WEEKLY_EMAIL_EXTERNAL_SEGMENT_ID`; they never fall back to the internal team segment.
- Resend Broadcasts supplies the contact-specific unsubscribe URL and maintains suppression state.
- The existing GitHub workflow does not receive the external segment ID and cannot send to customers.

## Input CSV

Required columns:

- `email`
- `consent_status`: `subscribed`, `opted_in`, or `explicit_opt_in`
- `consent_source`: for example `website_newsletter_form` or `event_signup`
- `consent_at`: ISO date such as `2026-10-01`

Optional columns:

- `first_name`
- `company`
- `segment`

Use `data/weekly-email-audience.example.csv` as the schema example.

## Prepare an audience

```bash
bidmatrix-monitor \
  --weekly-email-audience-import data/private/customer-export.csv \
  --weekly-email-audience-output-dir data/private/weekly-email-audience
```

Review all three outputs before any Resend import:

- `accepted.csv`: eligible, normalized contacts
- `rejected.csv`: excluded contacts and the exact reason
- `summary.json`: aggregate counts only

Upload `accepted.csv` to a new Resend segment created only for the external weekly newsletter. Use Resend's upsert mode, but do not overwrite global unsubscribe or suppression state.

## Prepare and approve a campaign

First create the regular weekly preview. Then create a blocked external campaign manifest:

```bash
bidmatrix-monitor \
  --weekly-email-external-prepare reports/weekly-email-preview-YYYY-MM-DD.json \
  --weekly-email-audience-summary data/private/weekly-email-audience/summary.json \
  --weekly-email-external-manifest data/private/weekly-email-audience/external-campaign.json
```

After editorial and audience review, record approval without sending:

```bash
bidmatrix-monitor \
  --weekly-email-external-approve \
  --weekly-email-external-manifest data/private/weekly-email-audience/external-campaign.json \
  --weekly-email-approved-by ksenia@bid-matrix.com
```

Use `--weekly-email-send-test ... --weekly-email-send-dry-run` to inspect the final Resend Broadcast payload. A real send is a separate, deliberate operation.

## Resend and DNS checklist

- SPF verified
- DKIM verified
- DMARC published and reporting monitored
- Custom tracking domain verified
- Open and click tracking enabled as approved by privacy policy
- Broadcast unsubscribe URL visible in HTML and plain text
- Separate internal and external Resend segments
- Suppressions preserved during every import
- Test inboxes cover Gmail, Outlook, and Apple Mail

## Analytics events

Configure a signed Resend webhook for:

- `email.sent`
- `email.delivered`
- `email.delivery_delayed`
- `email.bounced`
- `email.complained`
- `email.opened`
- `email.clicked`
- contact unsubscribe/update events available in the account

Do not expose a webhook endpoint until signature verification, event deduplication, retention, and access controls are implemented. Open rate is directional; clicks, bounces, complaints, and unsubscribes are the operational metrics.

## Launch gates

Do not enable external scheduling until all are true:

1. Legal/consent review is complete for every imported source.
2. DNS authentication and tracking are verified.
3. A seed-list test passes across major mailbox providers.
4. The first audience cohort is intentionally small and engaged.
5. Bounce and complaint stop thresholds are configured.
6. A human approves the content and audience for the initial launches.
