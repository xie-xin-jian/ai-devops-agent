# ops-service

A small order service used by the operations evaluation suite.

## Runtime

- HTTP health endpoint: `/healthz`
- Business endpoint: `/api/orders`
- Listener: `0.0.0.0:8080`
- Configuration: `config/app.conf`
- Application log: `logs/app.log`

## Known failure modes

- The upstream PostgreSQL connection can time out.
- The `/data` volume has recently crossed the 80% warning threshold.
- Invalid configuration values are rejected at startup.

Do not delete logs or restart the service unless the operator explicitly asks
and approves the operation.
