# IAT website

Static English-language landing page for Cloudflare Pages. It has no build
step and no server-side runtime.

## Cloudflare Pages configuration

- Production branch: `main`
- Framework preset: `None`
- Build command: leave empty
- Build output directory: `site`
- Root directory: leave empty

After Cloudflare creates the project, add its exact production origin to the
main IAT API on Render:

```text
IAT_PUBLIC_WEB_ORIGINS=https://YOUR-PROJECT.pages.dev
```

Multiple origins can be configured as a comma-separated list. Never include a
path or a trailing slash. Redeploy the API after changing the variable, then
submit one canary application from the website.

## Privacy-first analytics

In the Cloudflare dashboard, open the Pages project, go to **Metrics**, and
select **Enable** under Web Analytics. Cloudflare injects its performance beacon
on the next deployment. The site records no advertising identifiers or cookies.

Because Cloudflare Web Analytics does not expose custom events, the site maps
the anonymous acquisition funnel to virtual routes:

- `/funnel/pilot-open`
- `/funnel/manifest-open`
- `/funnel/form-started`
- `/funnel/application-accepted`
- `/funnel/application-error`

These paths are aggregate milestones, not user identities. `_redirects` makes
every milestone safe to reload or share without returning a 404.
