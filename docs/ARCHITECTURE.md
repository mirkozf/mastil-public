# Arquitectura de mastil-simple

## El ciclo

```
leer updates -> enrutar -> tick de cada módulo -> vaciar la outbox
```

Eso es todo. `main.py` arma la configuración y la base; `core/runtime.py`
compone los módulos y repite ese ciclo cada `MASTIL_POLL_SECONDS`.

## Las tres reglas que ordenan el proyecto

### 1. Todas las rutas salen de `__file__`

`config.py` calcula `ROOT` y de ahí cuelga todo. **Ningún otro archivo contiene
una ruta absoluta.** Por eso copiar la carpeta produce una instalación
independiente, y por eso montar un ambiente de desarrollo es copiar y editar
`.env`, sin tocar código.

En el legacy los cinco módulos auxiliares tenían `/opt/guardian-telegram`
escrito adentro, así que una copia seguía leyendo y escribiendo producción.

### 2. Los módulos no envían mensajes

Escriben en `outbox` dentro de la misma transacción que el cambio de estado:

```python
with db.transaction():
    self._update(phase="rescue", last_sent=iso(now_local()))
    self._say(random.choice(messages.FRASES_RESCATE))
```

El envío real ocurre en `runtime.flush_outbox()`, después del commit. Si el
proceso muere en el medio, o se guardaron las dos cosas o ninguna: nunca se
insiste dos veces ni se pierde un aviso.

### 3. El tiempo lo decide `core/scheduler.py`

Cuándo insistir, cuándo acelerar el rescate, cuándo vence un plazo. Ninguna IA
participa. Gemini opina sobre fotos y nada más.

## Los módulos

| Módulo | Qué hace |
|---|---|
| `system` | `/admin`, `/estado`, `/suspender`, `/reanudar`, pruebas |
| `timer` | temporizador con razón, avisos, pausa |
| `guardian` | eventos `**`: freno → tregua → chequeo → rescate |
| `pomodoro` | bloques con corte obligatorio |
| `lite` | recordatorios de la usuaria asistida, cifrados |
| `vigia` | eventos `++`: fotos, duración, presencia, código doble |
| `gmail` | consulta de correo bajo demanda |

Cada uno expone `handle_command(command, raw_text) -> bool` y, si lo necesita,
`tick()`. El router los recorre en orden y el primero que devuelve `True` gana.

**El freno no es un módulo.** Es la primera fase de `guardian`. Separarlo
obligaría a cada mitad a tener su propia noción de cuál evento está activo, y
ahí vuelve el `current_event_id` global que hacía que dos compromisos cercanos
se pisaran.

## El router

Prioridad fija y explícita:

1. Mástil Lite ve los mensajes de sus usuarias. Único camino para la usuaria asistida.
2. Desde acá, sólo el propietario.
3. Texto que empieza con `/` → comando. **Vigía nunca lo ve**, así un `/listo`
   no puede leerse como duración ni como código.
4. Foto → Vigía.
5. Texto libre → Vigía.

En el legacy esto estaba repartido entre `read_telegram`, `handle_command` y dos
módulos que parcheaban `urllib.request.urlopen` para interceptar los updates
antes que nadie. El orden real dependía del orden de los imports.

## Interruptores de seguridad

| Variable vacía en `.env` | Efecto |
|---|---|
| `MASTIL_CALENDAR_WEBAPP_URL` / `_TOKEN` | Mástil no puede modificar Calendar |
| `MASTIL_LITE_USERS` | la usuaria asistida no existe para esta instalación |
| `MASTIL_GMAIL_*` | Gmail responde que no está configurado |
| `MASTIL_GEMINI_API_KEY` | Vigía acepta toda foto sin evaluarla |

Un ambiente de desarrollo se define por lo que deja vacío.

## Privacidad de Calendar

Regla que viene de un incidente real: una implementación anterior reemplazó
títulos por texto aleatorio, el respaldo no representaba el estado previo, y la
restauración informó éxito con títulos ya irrecuperables.

- Sólo Base64 reversible, nunca ruido irreversible.
- El ledger con los originales se escribe **antes** de tocar el calendario.
- Al arrancar, si el ledger tiene entradas, se repone antes que nada.

## Lo que no hay

Sin `repository.py` por módulo: cada servicio hace su SQL. Sin migraciones
numeradas: un solo `schema.sql` idempotente hasta que la base tenga datos que
perder. Sin tests, por decisión del dueño — a cambio, el bot de desarrollo pasa
de conveniente a obligatorio.
