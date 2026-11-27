# Soul-Shard Counter Worker

From `worker/`:

1. Run `npm install` and `npx wrangler login`.
2. Run `npx wrangler d1 create soul-shard-counter`.
3. Put the returned database ID in `wrangler.toml` in place of `REPLACE_WITH_D1_ID`.
4. Run `npm run db:init`.
5. Run `npm run publish:worker`.

Embed in the repository README (replace `SUBDOMAIN` with your Workers subdomain):

```html
<img src="https://soul-shard-counter.SUBDOMAIN.workers.dev/@one-who-reads-aloud" alt="Visitor counter" />
```

Use `npm test` and `npm run typecheck` for checks. For local development, run
`npm run db:init:local` followed by `npm run dev`.

`src/sprites.generated.ts` is written by `python counter/art/build.py`; never edit it by hand.
`npm run preview` renders the static SVGs the README shows before a deployment.
Previews use `?num=4182`; invalid preview numbers render zero
without counting. `digits` (1–10) and `scale` (1–4) clamp integer inputs;
malformed values use defaults of 7 and 2. `bg=dark|light|transparent` and
`caption=0` control presentation. Only allow-listed names increment on GET.
The rolling rate cap is per isolate, not a global limit across Workers instances.
