# Virtual Group Sharemarket

A standalone fictional stock market for chat bots: Python market/accounting service, private Unix socket RPC, and an optional JavaScript bot/news SDK. All companies, funds, prices and news are game simulations. This is not financial advice or a real market data service.

See the [Chinese README](README.md) for commands and the [documentation index](README.md#文档).

## Install and run

Requires Linux, Python 3.11+, and optionally Node.js 24.15+ for the SDK and SQLite-backed news cache. Install a CJK font for Chinese charts.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install -r requirements-lock.txt
python -m pip install --no-build-isolation --no-deps -e .
sharemarket serve --state-dir state/shared --market-id shared --config config/market.example.json
```

In another terminal:

```bash
. .venv/bin/activate
sharemarket-rpc --socket state/shared/runtime.sock --request '{"method":"health"}'
node examples/bot.mjs '/fx 帮助'
```

The sample bot only prints results; it does not send chat messages. Integrators must supply trusted identities, group bindings, private-message routing, all-page artifact delivery and confirmed platform receipts. No network model is required for trading or charts.

## Boundaries

Run one process and database per market. The socket is owned by the service user and mode 0600; it is a local trust boundary, not an Internet API. Never accept actor IDs or target groups from model output. Preserve operation IDs when recovering failed sends. Private account responses must not enter group model context.

This extraction includes the core, SDK, tests and generic generated help artwork. It excludes production configuration, credentials, chat history, databases, checkpoints, seeds, original character images, and the host's delivery framework. It is not a ready-to-install AstrBot/OpenClaw plugin; the Python import namespace is retained for compatibility.

## Validation

```bash
python -m unittest discover -s src/astrbot_plugin_sharemarket/tests -v
npm test
python scripts/smoke.py
python scripts/audit-public.py
```

MIT; upstream attribution is preserved in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Contributions and private vulnerability reports are described in [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).
