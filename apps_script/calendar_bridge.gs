// Fuente versionable del puente Calendar de Mástil.
//
// En Apps Script se conserva el TOKEN real ya configurado. Antes de publicar,
// reemplaza el valor de ejemplo por el TOKEN existente del proyecto.

const TOKEN = "SET_EXISTING_TOKEN_IN_APPS_SCRIPT";
const REQUEST_MARKER = "MASTIL_CALENDAR_REQUEST:";

function doGet() {
  return json({ ok: true, service: "mastil-calendar-bridge" });
}

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents || "{}");

    if (body.token !== TOKEN) {
      return json({ ok: false, error: "TOKEN_INVALID" });
    }

    if (body.action === "snapshot_day") return snapshotDay(body);
    if (body.action === "obfuscate") return obfuscate(body);
    if (body.action === "restore") return restore(body);
    if (body.action === "create_event") return createEvent(body);
    if (body.action === "ping") return json({ ok: true, pong: true });

    return json({ ok: false, error: "UNKNOWN_ACTION" });
  } catch (err) {
    return json({ ok: false, error: String(err) });
  }
}

function getCalendar(body) {
  const calendar = CalendarApp.getCalendarById(body.calendar_id || "primary");
  if (!calendar) throw new Error("CALENDAR_NOT_FOUND");
  return calendar;
}

function parseDay(day) {
  const p = day.split("-").map(Number);
  const start = new Date(p[0], p[1] - 1, p[2], 0, 0, 0);
  const end = new Date(p[0], p[1] - 1, p[2] + 1, 0, 0, 0);
  return { start, end };
}

function snapshotDay(body) {
  const cal = getCalendar(body);
  const day = body.day || Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd");
  const range = parseDay(day);
  const events = cal.getEvents(range.start, range.end);

  const snapshot = events.map(ev => ({
    id: ev.getId(),
    title: ev.getTitle(),
    description: ev.getDescription() || ""
  }));

  return json({ ok: true, day, count: snapshot.length, snapshot });
}

function obfuscate(body) {
  const cal = getCalendar(body);
  const snapshot = body.snapshot || [];
  const changed = [];

  snapshot.forEach(item => {
    const ev = cal.getEventById(item.id);
    if (!ev) return;

    ev.setTitle(randomText(18));
    ev.setDescription(randomText(64));
    changed.push(item.id);
  });

  return json({ ok: true, changed_count: changed.length, changed });
}

function restore(body) {
  const cal = getCalendar(body);
  const snapshot = body.snapshot || [];
  const restored = [];

  snapshot.forEach(item => {
    const ev = cal.getEventById(item.id);
    if (!ev) return;

    ev.setTitle(item.title || "");
    ev.setDescription(item.description || "");
    restored.push(item.id);
  });

  return json({ ok: true, restored_count: restored.length, restored });
}

function createEvent(body) {
  const cal = getCalendar(body);
  const title = String(body.title || "").trim();
  const requestId = String(body.request_id || "").trim();
  const start = new Date(body.start_at);
  const end = new Date(body.end_at);

  if (!title) throw new Error("TITLE_REQUIRED");
  if (!requestId) throw new Error("REQUEST_ID_REQUIRED");
  if (isNaN(start.getTime()) || isNaN(end.getTime()) || end <= start) {
    throw new Error("INVALID_EVENT_RANGE");
  }

  const marker = REQUEST_MARKER + requestId;
  const rangeStart = new Date(start.getFullYear(), start.getMonth(), start.getDate(), 0, 0, 0);
  const rangeEnd = new Date(start.getFullYear(), start.getMonth(), start.getDate() + 1, 0, 0, 0);
  const existing = cal.getEvents(rangeStart, rangeEnd)
    .find(event => String(event.getDescription() || "").indexOf(marker) !== -1);

  if (existing) {
    return json({ ok: true, created: false, event: eventData(existing) });
  }

  const event = cal.createEvent(title, start, end, { description: marker });
  return json({ ok: true, created: true, event: eventData(event) });
}

function eventData(event) {
  return {
    id: event.getId(),
    title: event.getTitle(),
    start_at: event.getStartTime().toISOString(),
    end_at: event.getEndTime().toISOString()
  };
}

function randomText(n) {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789#$%&";
  let s = "";
  for (let i = 0; i < n; i++) {
    s += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return s;
}

function json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
