// SPA mode: every page renders entirely client-side after fetching its data
// from /api/* at runtime. SSR is disabled because the API isn't reachable at
// build time (it depends on the user's local echo.db and lancedb). Prerender
// stays off for the same reason - we ship index.html only and let the client
// router (SvelteKit) hydrate from there.

export const ssr = false;
export const prerender = false;
