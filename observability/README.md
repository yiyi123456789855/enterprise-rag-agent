# Observability assets

This directory contains two Prometheus deployment variants and the validated
Grafana dashboard used by the single-node production pilot.

- `prometheus.yml`: use when the API and Prometheus are on the Compose network.
- `prometheus-systemd.yml`: use when the API runs as a host systemd service on
  `127.0.0.1:8010` and Prometheus uses host networking.
- `alerts.yml`: API availability, error rate, dependency, P95 latency and rate
  limit alerts.
- `grafana-dashboard.json`: importable Grafana dashboard. Its Prometheus data
  source UID is `prometheus`.

The metrics endpoint requires the bearer token stored in
`data/secrets/metrics_token`. This runtime file is intentionally ignored by
Git and must be created with restrictive permissions on the target server.

For host networking, keep Prometheus and Grafana bound to `127.0.0.1` and use
an SSH tunnel or an authenticated reverse proxy to access their web UIs.
