const encoder = new TextEncoder();
let cachedKeys = null;
let cachedKeysAt = 0;

function json(value, status = 200, headers = {}) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...headers },
  });
}

function decodeBase64Url(value) {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(value.length / 4) * 4, "=");
  return Uint8Array.from(atob(normalized), (character) => character.charCodeAt(0));
}

function parseJwt(token) {
  const parts = token.split(".");
  if (parts.length !== 3) throw new Error("Malformed Access token");
  return {
    header: JSON.parse(new TextDecoder().decode(decodeBase64Url(parts[0]))),
    payload: JSON.parse(new TextDecoder().decode(decodeBase64Url(parts[1]))),
    signature: decodeBase64Url(parts[2]),
    signed: encoder.encode(parts[0] + "." + parts[1]),
  };
}

async function accessKeys(env) {
  if (cachedKeys && Date.now() - cachedKeysAt < 3_600_000) return cachedKeys;
  if (!env.ACCESS_TEAM_DOMAIN) throw new Error("ACCESS_TEAM_DOMAIN is not configured");
  const domain = env.ACCESS_TEAM_DOMAIN.replace(/^https?:\/\//, "").replace(/\/$/, "");
  const response = await fetch(`https://${domain}/cdn-cgi/access/certs`);
  if (!response.ok) throw new Error("Could not load Cloudflare Access signing keys");
  cachedKeys = (await response.json()).keys || [];
  cachedKeysAt = Date.now();
  return cachedKeys;
}

export async function verifyAccess(request, env, { sync = false } = {}) {
  if (env.TEST_BYPASS_ACCESS === "true") return { email: env.ALLOWED_EMAIL || "test@example.test", sub: "test" };
  const token = request.headers.get("CF-Access-Jwt-Assertion");
  if (!token) throw new Response(JSON.stringify({ detail: "Cloudflare Access authentication is required." }), { status: 401 });
  let jwt;
  try { jwt = parseJwt(token); } catch { throw new Response(JSON.stringify({ detail: "Invalid Access token." }), { status: 401 }); }
  if (jwt.header.alg !== "RS256") throw new Response(JSON.stringify({ detail: "Unsupported Access token algorithm." }), { status: 401 });
  const keyData = (await accessKeys(env)).find((candidate) => candidate.kid === jwt.header.kid);
  if (!keyData) throw new Response(JSON.stringify({ detail: "Unknown Access signing key." }), { status: 401 });
  const key = await crypto.subtle.importKey("jwk", keyData, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
  if (!await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, jwt.signature, jwt.signed)) {
    throw new Response(JSON.stringify({ detail: "Invalid Access token signature." }), { status: 401 });
  }
  const audiences = Array.isArray(jwt.payload.aud) ? jwt.payload.aud : [jwt.payload.aud];
  if (!audiences.includes(env.ACCESS_AUD) || Number(jwt.payload.exp || 0) <= Date.now() / 1000) {
    throw new Response(JSON.stringify({ detail: "Expired or wrong-audience Access token." }), { status: 401 });
  }
  if (sync) {
    if (!env.SYNC_SECRET || request.headers.get("X-SavedAgain-Sync-Secret") !== env.SYNC_SECRET) {
      throw new Response(JSON.stringify({ detail: "Sync authentication failed." }), { status: 403 });
    }
  } else if (!jwt.payload.email || jwt.payload.email.toLowerCase() !== String(env.ALLOWED_EMAIL || "").toLowerCase()) {
    throw new Response(JSON.stringify({ detail: "This account is not allowed to open the library." }), { status: 403 });
  }
  return jwt.payload;
}

function safeParse(value, fallback = {}) {
  try { return JSON.parse(value); } catch { return fallback; }
}

function publicItem(row) {
  const data = safeParse(row.data);
  return {
    ...data,
    favourite: row.favourite,
    tried: row.tried,
    dismissed: row.dismissed,
    snoozed_until: row.snoozed_until,
    notes: row.notes,
    manual_category: row.manual_category,
    position: row.position,
    revision: row.revision,
    updated: row.updated,
    thumbnail: row.preview_key ? `/media/${encodeURIComponent(row.id)}.webp?v=${row.preview_hash || row.revision}` : "",
  };
}

async function getCategories(env) {
  const result = await env.DB.prepare("SELECT id,name,art,color,rank FROM categories ORDER BY rank,id").all();
  return result.results || [];
}

async function listItems(url, env) {
  const page = Math.max(1, Number(url.searchParams.get("page") || 1));
  const size = Math.max(1, Math.min(100, Number(url.searchParams.get("size") || 24)));
  const category = url.searchParams.get("category") || "";
  const subcategory = url.searchParams.get("subcategory") || "";
  const query = (url.searchParams.get("q") || "").trim().toLowerCase().slice(0, 200);
  const view = url.searchParams.get("view") || "library";
  const clauses = ["1=1"];
  const bindings = [];
  if (category) { clauses.push("category=?"); bindings.push(category); }
  if (subcategory) { clauses.push("subcategory=?"); bindings.push(subcategory); }
  if (query) { clauses.push("search_text LIKE ? ESCAPE '\\'"); bindings.push(`%${query.replace(/[\\%_]/g, "\\$&")}%`); }
  if (view === "favourites") clauses.push("favourite=1");
  if (view === "tried") clauses.push("tried=1");
  if (view === "revisit") { clauses.push("tried=0", "dismissed=0", "(snoozed_until IS NULL OR snoozed_until<=?)"); bindings.push(new Date().toISOString()); }
  const where = clauses.join(" AND ");
  const count = await env.DB.prepare(`SELECT count(*) AS total FROM posts WHERE ${where}`).bind(...bindings).first();
  const rows = await env.DB.prepare(`SELECT * FROM posts WHERE ${where} ORDER BY favourite DESC,position LIMIT ? OFFSET ?`).bind(...bindings, size, (page - 1) * size).all();
  const total = Number(count?.total || 0);
  return json({ items: (rows.results || []).map(publicItem), total, page, pages: Math.max(1, Math.ceil(total / size)) });
}

async function library(env) {
  const [categories, groups, counts, previews] = await Promise.all([
    getCategories(env),
    env.DB.prepare("SELECT category,subcategory,count(*) AS count FROM posts GROUP BY category,subcategory").all(),
    env.DB.prepare("SELECT count(*) AS total,sum(favourite) AS favourites,sum(tried) AS tried,sum(CASE WHEN category='review' THEN 1 ELSE 0 END) AS needs_review FROM posts").first(),
    env.DB.prepare("SELECT * FROM posts ORDER BY position LIMIT 200").all(),
  ]);
  const rows = previews.results || [];
  const cards = categories.map((category) => {
    const subcategories = (groups.results || []).filter((group) => group.category === category.id).map((group) => ({ name: group.subcategory, count: group.count }));
    const matching = rows.filter((row) => row.category === category.id);
    return { ...category, count: matching.length || subcategories.reduce((sum, item) => sum + Number(item.count), 0), subcategories, preview: matching.slice(0, 2).map(publicItem) };
  }).filter((category) => category.count);
  return json({
    account: "your_saved_library", total: Number(counts?.total || 0), favourites: Number(counts?.favourites || 0), tried: Number(counts?.tried || 0),
    organized: Number(counts?.total || 0) - Number(counts?.needs_review || 0), needs_review: Number(counts?.needs_review || 0), categories: cards,
    category_options: categories, local_thumbnails: rows.filter((row) => row.preview_key).length, incomplete: 0, inaccessible: 0,
    coverage: { status: "complete", message: "Always-on private cloud mirror. Detailed evidence remains on your Mac.", cloud: true },
  });
}

const editable = new Set(["favourite", "tried", "dismissed", "snoozed_until", "notes", "category", "subcategory"]);

async function patchItem(request, env, id) {
  const body = await request.json();
  const patch = Object.fromEntries(Object.entries(body).filter(([key]) => editable.has(key)));
  if (!Object.keys(patch).length) return json({ detail: "No editable fields were supplied." }, 400);
  const current = await env.DB.prepare("SELECT * FROM posts WHERE id=?").bind(id).first();
  if (!current) return json({ detail: "Post not found" }, 404);
  const data = safeParse(current.data);
  if ("category" in patch) {
    const known = await env.DB.prepare("SELECT 1 FROM categories WHERE id=?").bind(String(patch.category)).first();
    if (!known) return json({ detail: "Unknown category" }, 400);
    data.category = String(patch.category);
    data.subcategory = String(patch.subcategory || "General").slice(0, 120);
    data.categories = [{ category: data.category, subcategory: data.subcategory }];
    data.organization_status = data.category === "review" ? "needs_review" : "organized";
  }
  const state = {
    favourite: "favourite" in patch ? Number(Boolean(patch.favourite)) : current.favourite,
    tried: "tried" in patch ? Number(Boolean(patch.tried)) : current.tried,
    dismissed: "dismissed" in patch ? Number(Boolean(patch.dismissed)) : current.dismissed,
    snoozed_until: "snoozed_until" in patch ? patch.snoozed_until || null : current.snoozed_until,
    notes: "notes" in patch ? String(patch.notes || "").slice(0, 20000) : current.notes,
  };
  const mutationId = crypto.randomUUID();
  const updated = new Date().toISOString();
  const revision = Number(current.revision) + 1;
  await env.DB.batch([
    env.DB.prepare("UPDATE posts SET data=?,category=?,subcategory=?,favourite=?,tried=?,dismissed=?,snoozed_until=?,notes=?,manual_category=?,revision=?,updated=? WHERE id=?").bind(
      JSON.stringify(data), data.category || "review", data.subcategory || "Unsorted", state.favourite, state.tried, state.dismissed,
      state.snoozed_until, state.notes, "category" in patch ? 1 : current.manual_category, revision, updated, id,
    ),
    env.DB.prepare("INSERT INTO mutations(id,post_id,patch,created_at) VALUES(?,?,?,?)").bind(mutationId, id, JSON.stringify(patch), updated),
  ]);
  return json(publicItem(await env.DB.prepare("SELECT * FROM posts WHERE id=?").bind(id).first()));
}

export function safeSyncItem(item) {
  const forbidden = ["caption", "transcript", "ocr", "embedding", "frames", "audio", "source_path", "thumbnail_url", "prompt"];
  const serialized = JSON.stringify(item).toLowerCase();
  if (forbidden.some((key) => serialized.includes(`"${key}`))) throw new Error("Private analysis fields are not accepted by cloud sync.");
  const data = {};
  for (const key of ["id", "url", "creator", "title", "summary", "tags", "category", "subcategory", "categories", "classification_confidence", "organization_status", "media_type", "order"]) {
    if (item[key] !== undefined) data[key] = item[key];
  }
  return data;
}

async function syncPush(request, env) {
  const body = await request.json();
  const accepted = [];
  const conflicts = [];
  for (const category of (body.categories || []).slice(0, 200)) {
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(String(category.id || ""))) return json({ detail: "Invalid category id" }, 400);
    await env.DB.prepare(
      "INSERT INTO categories(id,name,art,color,rank) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,art=excluded.art,color=excluded.color,rank=excluded.rank"
    ).bind(category.id, String(category.name || "").slice(0, 80), String(category.art || "neutral.webp"), String(category.color || "#164b35"), Number(category.rank ?? 100)).run();
  }
  for (const item of (body.items || []).slice(0, 250)) {
    let data;
    try { data = safeSyncItem(item); } catch (error) { return json({ detail: error.message }, 400); }
    if (!/^[A-Za-z0-9_-]{3,120}$/.test(String(item.id || ""))) return json({ detail: "Invalid post id" }, 400);
    const syncId = String(item.sync_id || "");
    if (!/^[a-f0-9]{64}$/.test(syncId)) return json({ detail: "Invalid sync id" }, 400);
    const replay = await env.DB.prepare("SELECT revision FROM sync_requests WHERE id=? AND post_id=?").bind(syncId, item.id).first();
    if (replay) { accepted.push({ id: item.id, revision: Number(replay.revision) }); continue; }
    const current = await env.DB.prepare("SELECT * FROM posts WHERE id=?").bind(item.id).first();
    const expected = Number(item.expected_remote_revision || 0);
    if (current && Number(current.revision) !== expected) {
      conflicts.push({ id: item.id, expected, actual: Number(current.revision) });
      continue;
    }
    const revision = Number(current?.revision || 0) + 1;
    const updated = String(item.updated || new Date().toISOString());
    const searchText = [data.title, data.summary, data.creator, data.category, data.subcategory, ...(Array.isArray(data.tags) ? data.tags : [])].filter(Boolean).join(" ").toLowerCase();
    await env.DB.batch([
      env.DB.prepare(
        "INSERT INTO posts(id,data,position,category,subcategory,search_text,favourite,tried,dismissed,snoozed_until,notes,manual_category,revision,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) " +
        "ON CONFLICT(id) DO UPDATE SET data=excluded.data,position=excluded.position,category=excluded.category,subcategory=excluded.subcategory,search_text=excluded.search_text,favourite=excluded.favourite,tried=excluded.tried,dismissed=excluded.dismissed,snoozed_until=excluded.snoozed_until,notes=excluded.notes,manual_category=excluded.manual_category,revision=excluded.revision,updated=excluded.updated"
      ).bind(
        item.id, JSON.stringify(data), Number(item.position || item.order || 0), data.category || "review", data.subcategory || "Unsorted", searchText,
        Number(Boolean(item.favourite)), Number(Boolean(item.tried)), Number(Boolean(item.dismissed)), item.snoozed_until || null,
        String(item.notes || "").slice(0, 20000), Number(Boolean(item.manual_category)), revision, updated,
      ),
      env.DB.prepare("INSERT INTO sync_requests(id,post_id,revision,created_at) VALUES(?,?,?,?)").bind(syncId, item.id, revision, updated),
    ]);
    accepted.push({ id: item.id, revision });
  }
  if (conflicts.length) return json({ accepted, conflicts }, 409);
  return json({ accepted, conflicts: [] });
}

async function handleApi(request, env, url) {
  const sync = url.pathname.startsWith("/api/sync/");
  await verifyAccess(request, env, { sync });
  if (url.pathname === "/api/capabilities" && request.method === "GET") return json({ mode: "cloud", analysis: false, media_upload: false, sync: true, raw_evidence: false });
  if (url.pathname === "/api/library" && request.method === "GET") return library(env);
  if (url.pathname === "/api/categories" && request.method === "GET") return json({ items: await getCategories(env) });
  if (url.pathname === "/api/items" && request.method === "GET") return listItems(url, env);
  if (url.pathname === "/api/digest" && request.method === "GET") {
    const digestUrl = new URL(url); digestUrl.searchParams.set("view", "revisit"); digestUrl.searchParams.set("size", "3");
    const response = await listItems(digestUrl, env); const payload = await response.json(); return json({ items: payload.items });
  }
  const itemMatch = url.pathname.match(/^\/api\/items\/([A-Za-z0-9_-]{3,120})$/);
  if (itemMatch && request.method === "GET") {
    const row = await env.DB.prepare("SELECT * FROM posts WHERE id=?").bind(itemMatch[1]).first();
    return row ? json(publicItem(row)) : json({ detail: "Post not found" }, 404);
  }
  if (itemMatch && request.method === "PATCH") return patchItem(request, env, itemMatch[1]);
  if (url.pathname === "/api/sync/pull" && request.method === "GET") {
    const after = Math.max(0, Number(url.searchParams.get("after") || 0));
    const result = await env.DB.prepare("SELECT m.sequence,m.id,m.post_id,m.patch,m.created_at,p.revision FROM mutations m JOIN posts p ON p.id=m.post_id WHERE m.sequence>? ORDER BY m.sequence LIMIT 500").bind(after).all();
    const mutations = (result.results || []).map((row) => ({ ...row, patch: safeParse(row.patch) }));
    const cursor = mutations.length ? Number(mutations[mutations.length - 1].sequence) : after;
    return json({ mutations, cursor });
  }
  if (url.pathname === "/api/sync/push" && request.method === "POST") return syncPush(request, env);
  const previewMatch = url.pathname.match(/^\/api\/sync\/previews\/([A-Za-z0-9_-]{3,120})$/);
  if (previewMatch && request.method === "PUT") {
    if (request.headers.get("content-type") !== "image/webp") return json({ detail: "Only WebP previews are accepted." }, 415);
    const blob = await request.arrayBuffer();
    if (!blob.byteLength || blob.byteLength > 1_000_000) return json({ detail: "Preview is empty or too large." }, 400);
    const key = `previews/${previewMatch[1]}.webp`;
    const digest = request.headers.get("X-Content-SHA256") || "";
    await env.PREVIEWS.put(key, blob, { httpMetadata: { contentType: "image/webp", cacheControl: "private, max-age=3600" } });
    await env.DB.prepare("UPDATE posts SET preview_key=?,preview_hash=? WHERE id=?").bind(key, digest, previewMatch[1]).run();
    return json({ ok: true });
  }
  if (url.pathname === "/api/sync/ack" && request.method === "POST") {
    const body = await request.json();
    await env.DB.prepare("INSERT INTO sync_clients(id,cursor,updated_at) VALUES('mac',?,?) ON CONFLICT(id) DO UPDATE SET cursor=excluded.cursor,updated_at=excluded.updated_at").bind(Number(body.cursor || 0), new Date().toISOString()).run();
    return json({ ok: true });
  }
  return json({ detail: "Not found" }, 404);
}

async function handlePreview(request, env, url) {
  await verifyAccess(request, env);
  const match = url.pathname.match(/^\/media\/([A-Za-z0-9_-]{3,120})\.webp$/);
  if (!match) return new Response("Not found", { status: 404 });
  const object = await env.PREVIEWS.get(`previews/${match[1]}.webp`);
  if (!object) return new Response("Not found", { status: 404 });
  return new Response(object.body, { headers: { "content-type": "image/webp", "cache-control": "private, max-age=3600", "x-content-type-options": "nosniff" } });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      if (url.pathname.startsWith("/api/")) return await handleApi(request, env, url);
      if (url.pathname.startsWith("/media/")) return await handlePreview(request, env, url);
    } catch (error) {
      if (error instanceof Response) return error;
      return json({ detail: "Cloud dashboard request failed." }, 500);
    }
    const response = await env.ASSETS.fetch(request);
    const acceptsHtml = request.headers.get("accept")?.includes("text/html");
    if (response.status !== 404 || !acceptsHtml || !["GET", "HEAD"].includes(request.method)) return response;
    const indexUrl = new URL(request.url);
    indexUrl.pathname = "/index.html";
    indexUrl.search = "";
    return env.ASSETS.fetch(new Request(indexUrl, request));
  },
};
