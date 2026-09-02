# OpenTrack

_Replace the heading above with the project's name, and this line with one sentence describing what this app does for users._

## Run & Operate

- `pnpm --filter @workspace/api-server run dev` — run the API server (port 5000)
- `pnpm --filter @workspace/opentrack-mobile run dev` — run the native mobile app (Expo); open in Expo Go on a phone via the QR code, no Xcode/App Store/sideloading needed
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- Required env: `DATABASE_URL` — Postgres connection string

## Stack

- pnpm workspaces, Node.js 24, TypeScript 5.9
- API: Express 5
- DB: PostgreSQL + Drizzle ORM
- Validation: Zod (`zod/v4`), `drizzle-zod`
- API codegen: Orval (from OpenAPI spec)
- Build: esbuild (CJS bundle)
- Mobile: Expo + React Native (`artifacts/opentrack-mobile`)

## Where things live

- `artifacts/opentrack` — the web app (Vite/React), OpenTrack Ballistic Visualizer
- `artifacts/opentrack-mobile` — the native iOS/Android app (Expo Router, single screen). Same launch-monitor workflow as the web app — video import, calibration, launch/apex/landing click-marking, physics trajectory fit, tracking ring, stat tiles — built with `react-native-svg` for the overlay and `expo-av` for video. The trajectory math (`utils/ballTrajectory.ts`) is a straight port of the same physics used by the web/desktop editors: weighted quadratic fit for launch angle, segmented hold-then-ease ascent + gravity-parabola descent for the display path.
- `artifacts/api-server` — Express API
- `lib/db` — Drizzle schema (source of truth for tables)
- `lib/api-spec` — OpenAPI spec (source of truth for the API contract)

## Architecture decisions

- `opentrack-mobile` is intentionally client-side only, no server/DB writes — matches the local-first pattern the other OpenTrack clients use for shot data (nothing here needs to be shared across devices yet).

## Product

_Describe the high-level user-facing capabilities of this app once they exist._

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

_Populate as you build — sharp edges, "always run X before Y" rules._

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
