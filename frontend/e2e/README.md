# E2E and visual regression

Run tests only against a dedicated non-production environment:

```sh
E2E_BASE_URL=http://127.0.0.1:3000 E2E_USERNAME=... E2E_PASSWORD=... pnpm test:e2e
```

The suite deliberately does not execute device, incident, threshold, or maintenance mutations unless a dedicated test fixture is introduced. This prevents operational data from being changed by a test run.

`E2E_VISUAL=1` enables approved desktop screenshot baselines. Generate or update those baselines only from the fixture environment. `E2E_ALLOW_MUTATIONS=1` is additionally required for admin workflow coverage.

CI runs the six functional scenarios against a fresh SQLite backend and a production frontend build on Node 22. Fixture credentials are supplied by the workflow; configuration fails if CI credentials or the admin fixture flag are missing, so a skipped suite cannot pass the gate. Approved visual baselines are a separate opt-in suite and are excluded from the functional job. CI uploads Playwright reports, traces on retry, and service logs for diagnosis.
