import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	compilerOptions: {
		// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
		runes: ({ filename }) => (filename.split(/[/\\]/).includes('node_modules') ? undefined : true)
	},
	kit: {
		// adapter-static in SPA mode: every route is rendered client-side from a
		// single index.html fallback. The Echo Speaks UI does live agent calls
		// against /api/* at runtime; nothing is prerenderable from the static
		// build, so SPA is the right shape.
		// The build artifacts land in `ui/build/`; the packaging step copies them
		// to `src/echo/ui/dist/` so `echo serve` can mount them via FastAPI's
		// StaticFiles.
		adapter: adapter({
			pages: 'build',
			assets: 'build',
			fallback: 'index.html',
			precompress: false,
			strict: false
		})
	}
};

export default config;
