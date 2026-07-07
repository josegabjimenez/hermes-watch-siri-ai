# Fable 5 Review — Baseline real — `hermes-watch-siri-ai`

**Fecha:** 2026-07-07 · **Commit:** `e782c0a` (main, working tree limpio antes de guardar este review) · **Reviewer:** Claude Code / Fable 5

## Evidence

- Esta revisión fue ejecutada vía **Claude Code** con el modelo **`claude-fable-5`** (Fable 5 real), en Linux y en modo reviewer/auditor. Constituye el baseline Fable auténtico; los `docs/FABLE5_REVIEW_00x` previos deben tratarse como reviews de protocolo generadas por otro agente si no hay consumo Fable verificable.
- Verificaciones reportadas por Fable 5:
  - Tests del backend: `python3 -m unittest tests.test_mobile_capture_staging_server` → **9/9 OK**.
  - Vector HMAC del test Swift recalculado independientemente en Python: `HMAC_SHA256("test-secret", "1700000000." + body)` → `e824cb05…251aab`, **idéntico** al esperado en `HermesCoreTests.testHMACV2KnownVector`.
  - Barrido de secretos (dominios reales de tailnet, prefijos comunes de tokens/API keys y claves cloud, e IPs privadas de tailnet) → **sin hallazgos**.
  - `git ls-files` confirma que `backend/data/*.sqlite` y `__pycache__` son artefactos locales no trackeados, cubiertos por `.gitignore`.
  - **No hay Swift ni Xcode en este entorno** — no se afirma ningún resultado de compilación del scaffold Apple; eso queda para macOS.

## Veredicto: **APPROVED WITH CONDITIONS**

- ✅ Autorizado avanzar a la fase Xcode/macOS **manteniendo dry-run/no-write**.
- ⛔ Escrituras reales (Firefly/Notion/Calendar/Home Assistant) **bloqueadas** hasta cerrar los P0.

## 1. Arquitectura Watch-first + iOS configurador/fallback — sólida

`ARCHITECTURE.md` y el `DECISION_LOG.md` (D001–D009) son coherentes y las decisiones están bien fundadas: Watch captura directo por URLSession sin depender del iPhone; iOS es configuración/Keychain/relay; HermesCore concentra contratos, firma y outbox; UX acción-first; dictado del sistema en vez de STT custom; y no exponer el API Server amplio al Watch. El diagnóstico de que el webhook genérico de Hermes (202 async, cache de duplicados efímero) no sirve para UX síncrona de Watch es correcto y justifica el BFF. El scaffold refleja la arquitectura, pero las apps son cascarones: `WatchContentView.swift` no tiene dictado/outbox/envío y iOS no tiene Keychain ni WCSession todavía (documentado como siguiente paso, así que no es un defecto oculto).

## 2. Contrato `mobile_capture.v1`, HMAC, idempotencia, outbox

**Lo que está bien:** formato HMAC `"{ts}.{raw_body}"` idéntico en ambos lados (vector verificado); `hmac.compare_digest`; ventana de replay de 300 s; firma sobre bytes exactos con `JSONEncoder.sortedKeys` (re-encode determinista, cumple la regla "do not reserialize after signing"); ledger por `request_id` + `sha256(raw_body)` con duplicado cacheado y 409 en conflicto de hash; la firma se genera al momento del envío, así que items viejos del outbox no chocan con la ventana de replay.

**Los gaps:**

- **Drift Swift↔contrato (P1):** `CaptureResponseV1.swift` no decodifica `message`, `result_id`, `needs_confirmation` (bool), `next_actions` ni `interpreted_due`. El servidor ya emite `interpreted_due` y la regla de dominio de Aura exige confirmar la fecha interpretada — el Watch la perdería silenciosamente.
- **Outbox incompleto (P1):** `FileOutboxStore` solo tiene primitivas; no existe drainer con retry/backoff ni max-attempts, y un item que quede en `sending` tras un crash no se recupera nunca.
- **Semántica no documentada (P1):** una respuesta `needs_confirmation` queda persistida en el ledger bajo su `request_id`; reenviar la captura corregida con el mismo id da 409. El cliente debe generar un `request_id` nuevo tras `needs_confirmation`, y eso no está en `API_CONTRACT_V1.md`.
- `HermesDomain` en Swift omite `argos.agent_status`, que el contrato lista como canónico (P2).

## 3. Seguridad — postura actual correcta, un gap P0

No hay secretos ni API keys en el repo; el secreto vive en `~/.hermes/` fuera del árbol; bind default `127.0.0.1`; TLS tailnet-only vía Tailscale Serve; el ledger guarda hash y respuesta, no el transcript crudo. Lo más importante: el servidor **ignora** `context.allow_write`/`allow_firefly_write` para autorización (dry-run hard-coded en `plan_capture`), y el prompt del webhook genérico refuerza lo mismo más el tratamiento de `capture.text` como dato no confiable. Firefly/Notion/Calendar quedan server-side only, como debe ser.

El gap: en Swift solo existe `InMemoryRouteSecretStore` — **no hay implementación Keychain ni provisioning iPhone→Watch** (P0 antes de instalar en dispositivos con secreto real). Además el outbox persistirá texto financiero/personal en JSON plano; falta especificar Data Protection (`.completeFileProtection`) y redacción del mini-historial (P1).

## 4. Calidad del scaffold Swift y backend staging

**Swift (no compilado aquí):** código idiomático — actors, `Sendable`, inyección de clock/UUID en `CaptureFactory`, `URLSessioning` inyectable para tests, fallback a `swift-crypto` que habilita CI en Linux a futuro. Faltan tests de outbox, de decoding de respuesta y de `endpointURL`. Riesgo a verificar en Mac: el target `HermesCoreTests` de `project.yml` duplica los tests SPM como bundle iOS con `@testable import` contra el producto del package, lo cual puede no compilar.

**Backend:** apropiado como staging, 9/9 tests. Defectos encontrados:

- **Race de idempotencia (P1):** SELECT-then-INSERT sin lock en `do_POST`; dos POST concurrentes con el mismo `request_id` producen un `IntegrityError` no capturado → respuesta vacía al perdedor. Es justamente el escenario de retry que el ledger existe para cubrir.
- **Parser de monto (P2):** `parse_amount_cop` toma el primer número del texto — `"tc1 45 mil almuerzo"` devuelve monto `1` (los fixtures ponen el monto antes del hint de tarjeta y ocultan el bug). Similar, `parse_spanish_due` convierte cualquier dígito en hora (`"mañana comprar 2 kilos"` → 02:00).
- Menores (P2): body vacío responde 413 en vez de 400; variable `dry_run` muerta en `plan_capture`; flujo confuso en `validate_payload` (texto vacío devuelve el plan completo, texto normal devuelve `{}`); el script `sign_and_post` apunta por default al puerto 8644 (gateway genérico) cuando el BFF es 8650.

## 5. Gaps por hito

- **Gate A — avanzar a Xcode/macOS (autorizado ya, en dry-run):** `xcodegen generate`, compilar iOS+watchOS, `swift test` en `HermesCore`, corregir `project.yml` si el target de tests falla.
- **Gate B — device testing con secreto real:** KeychainRouteSecretStore + provisioning WCSession, drainer del outbox con backoff y recuperación de `sending`, Data Protection del outbox, timeout corto de URLSession para UX Watch.
- **Gate C — escrituras reales:** el BFF hoy es un dead-end que nunca reenvía a Hermes; falta diseñar el puente BFF→Hermes con gates server-side por dominio, ledger durable de producción, fix del race, campos de respuesta completos en Swift, doc del `request_id` post-`needs_confirmation`, y QA en Watch físico. Los parsers heurísticos del staging no deben ser base de writes — la autoridad es el agente con consulta Firefly live, como ya dice el contrato.

## Resumen P0/P1/P2

- **P0:** (1) sin Keychain + provisioning de secreto en Swift; (2) sin camino BFF→Hermes ni flag de write server-side — el write-enable no tiene diseño ejecutable; (3) sin ledger durable de producción.
- **P1:** race SELECT/INSERT del ledger; outbox sin drainer/recovery; drift de `CaptureResponseV1` (sobre todo `interpreted_due`); semántica de `request_id` tras `needs_confirmation` sin documentar; protección/redacción del outbox en dispositivo.
- **P2:** parser de monto (tc1→1) y de hora (dígito suelto→hora); `argos.agent_status` ausente en el enum Swift; 413 para body vacío; puerto default 8644 del script de firma; target de tests duplicado en `project.yml`; código muerto/flujo confuso en `plan_capture`/`validate_payload`; tests Swift faltantes de outbox/decoding.

## Archivo fuente generado por Claude Code

Claude Code también reportó haber guardado el review en:

```text
/root/.claude/plans/eres-fable-5-actuando-floating-hare.md
```
