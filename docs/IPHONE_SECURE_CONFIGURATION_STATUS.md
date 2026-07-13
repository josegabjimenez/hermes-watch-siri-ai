# iPhone secure configuration phase

**Status:** implemented; iOS simulator validation required.

## Scope

The iPhone companion now provides:

- tailnet BFF base URL input;
- strict HTTPS validation;
- `/health` connection test;
- route-scoped HMAC secret entry;
- Keychain storage using `kSecClassGenericPassword`;
- local indicator showing whether a secret is configured.

## Storage policy

### Endpoint

The endpoint is not a credential and is stored in app-local `UserDefaults` under:

```text
hermes.baseURL
```

The public repository only contains `<TAILSCALE_DNS_NAME>` placeholders.

### Route secret

The route-scoped HMAC secret is stored in Keychain:

```text
service: dev.josegabjimenez.HermesCapture.mobile-capture
account: route-hmac-secret-v1
accessibility: AfterFirstUnlockThisDeviceOnly
```

The secret is never written to:

- source code;
- `UserDefaults`;
- logs;
- documentation;
- the public repository.

The UI clears the secret field immediately after saving.

## Health test

The connection test calls:

```text
GET <BFF_BASE_URL>/health
```

It does not transmit the HMAC secret.

## Deliberate limitation

The iPhone Keychain and Watch Keychain are separate. This phase does **not** sync the secret yet. The next phase will use WatchConnectivity as a user-initiated bootstrap channel, store the received value directly in Watch Keychain, and avoid durable plaintext copies.

## Validation checklist

1. Run `HermesCaptureiOS`.
2. Enter the actual Tailscale Serve base URL locally.
3. Tap **Probar conexión** and confirm `Conectado · dry-run`.
4. Paste the route secret locally; never paste it into chat or screenshots.
5. Tap **Guardar configuración**.
6. Confirm **Secreto configurado** and an empty secret field.
7. Relaunch the app and confirm the configured indicator remains.
