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
