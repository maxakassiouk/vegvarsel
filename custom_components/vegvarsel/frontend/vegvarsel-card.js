/**
 * Vegvarsel dashboard card: a route on Home Assistant's own map, the traffic
 * messages on it, whether the next trip has a problem - and a route planner
 * in the card for new routes and for changing one.
 *
 * Plain JavaScript, no build step, after the TomTom integration's card: the
 * map is Home Assistant's ha-map, reached through its Leaflet (through
 * 2026.9) or its 2026.10 engine (MapLibre, or Leaflet without WebGL2). Those
 * are not documented interfaces, so every reach is guarded: where none
 * works, the card still shows the status and the list, just no drawing.
 *
 * Data comes over the integration's websocket commands: vegvarsel/routes,
 * vegvarsel/search, vegvarsel/plan and vegvarsel/save_route.
 */
(() => {
  const TAG = "vegvarsel-card";
  const EDITOR_TAG = "vegvarsel-card-editor";

  // ---- text ------------------------------------------------------------------

  const I18N = {
    en: {
      name: "Vegvarsel",
      description: "Your route on the map, the traffic messages on it, and a route planner.",
      loading: "Loading routes…",
      no_routes: "No Vegvarsel routes yet.",
      no_integration: "Vegvarsel is not set up, or still starting.",
      searching: "Searching…",
      starting: "Vegvarsel is starting – reading the traffic feed…",
      clear: "Clear for your next trip",
      problem: "Problem on your next trip",
      watching: "Watching {from}–{until}",
      watching_now: "Watching now, until {until}",
      always: "Watching around the clock",
      next_closure: "Next closure: {when}",
      closure_now: "Closed now (since {when})",
      nothing: "No traffic messages on the route.",
      km: "{km} km",
      from_time: "from {when}",
      until_time: "until {when}",
      edit: "Edit route",
      new_route: "New route",
      google: "Google Maps",
      planner_new: "New route",
      planner_edit: "Edit {name}",
      route_name: "Name",
      from: "From",
      to: "To",
      stop: "Stop {n}",
      add_stop: "Add stop",
      swap: "Swap start and destination",
      remove: "Remove",
      search_hint: "Address, place, zone or person",
      map_centre: "Centre of the map",
      zone: "Zone",
      person: "Person",
      days: "Days",
      windows: "Watch windows",
      add_window: "Add",
      window_hint: "HH:MM-HH:MM, e.g. 06:45-08:15. None: watch around the clock.",
      preview: "Evening preview",
      preview_hint: "Empty: no preview",
      corridor: "Corridor (m)",
      calculate: "Calculate",
      calculating: "Calculating…",
      save: "Save",
      saving: "Saving…",
      discard: "Discard",
      routes_found: "Routes",
      route_option: "{km} km · {min} min · {n} messages",
      route_option_1: "{km} km · {min} min · 1 message",
      route_option_0: "{km} km · {min} min · no messages",
      need_ends: "Choose where the route starts and ends.",
      calculate_first: "Calculate the route first.",
      no_route: "No route found between these places.",
      save_failed: "Could not save: {error}",
      bad_window: "Write each window as HH:MM-HH:MM, e.g. 06:45-08:15.",
      bad_preview: "The evening preview is not a time.",
      no_days: "Pick at least one day.",
      bad_corridor: "The corridor must be 30–1000 m.",
      day_mon: "Mon", day_tue: "Tue", day_wed: "Wed", day_thu: "Thu", day_fri: "Fri", day_sat: "Sat", day_sun: "Sun",
      kind_closed: "Road closed", kind_accident: "Accident", kind_convoy: "Convoy driving", kind_obstruction: "Obstruction",
      kind_traffic: "Queues", kind_restriction: "Restriction", kind_roadworks: "Roadworks", kind_conditions: "Driving conditions",
      kind_info: "Traffic message",
      ed_route: "Route", ed_title: "Title (optional)", ed_height: "Map height (px)", ed_list: "Show the list",
      ed_google: "Show the Google Maps button", ed_landscape: "Map beside the list (wide cards)", ed_first: "First route",
    },
    nb: {
      name: "Vegvarsel",
      description: "Ruten din på kartet, trafikkmeldingene på den, og en ruteplanlegger.",
      loading: "Henter ruter …",
      no_routes: "Ingen Vegvarsel-ruter ennå.",
      no_integration: "Vegvarsel er ikke satt opp, eller starter fortsatt.",
      searching: "Søker …",
      starting: "Vegvarsel starter – leser trafikkmeldingene …",
      clear: "Ingen problemer på neste tur",
      problem: "Problem på neste tur",
      watching: "Overvåker {from}–{until}",
      watching_now: "Overvåker nå, til {until}",
      always: "Overvåker hele døgnet",
      next_closure: "Neste stenging: {when}",
      closure_now: "Stengt nå (siden {when})",
      nothing: "Ingen trafikkmeldinger på ruten.",
      km: "{km} km",
      from_time: "fra {when}",
      until_time: "til {when}",
      edit: "Endre rute",
      new_route: "Ny rute",
      google: "Google Maps",
      planner_new: "Ny rute",
      planner_edit: "Endre {name}",
      route_name: "Navn",
      from: "Fra",
      to: "Til",
      stop: "Stopp {n}",
      add_stop: "Legg til stopp",
      swap: "Bytt start og mål",
      remove: "Fjern",
      search_hint: "Adresse, sted, sone eller person",
      map_centre: "Midten av kartet",
      zone: "Sone",
      person: "Person",
      days: "Dager",
      windows: "Overvåkingsvinduer",
      add_window: "Legg til",
      window_hint: "TT:MM-TT:MM, f.eks. 06:45-08:15. Ingen: overvåk hele døgnet.",
      preview: "Kveldsvarsel",
      preview_hint: "Tomt: ikke noe kveldsvarsel",
      corridor: "Korridor (m)",
      calculate: "Regn ut",
      calculating: "Regner ut …",
      save: "Lagre",
      saving: "Lagrer …",
      discard: "Forkast",
      routes_found: "Ruter",
      route_option: "{km} km · {min} min · {n} meldinger",
      route_option_1: "{km} km · {min} min · 1 melding",
      route_option_0: "{km} km · {min} min · ingen meldinger",
      need_ends: "Velg hvor ruten starter og slutter.",
      calculate_first: "Regn ut ruten først.",
      no_route: "Fant ingen rute mellom disse stedene.",
      save_failed: "Kunne ikke lagre: {error}",
      bad_window: "Skriv hvert vindu som TT:MM-TT:MM, f.eks. 06:45-08:15.",
      bad_preview: "Kveldsvarselet er ikke et klokkeslett.",
      no_days: "Velg minst én dag.",
      bad_corridor: "Korridoren må være 30–1000 m.",
      day_mon: "Man", day_tue: "Tir", day_wed: "Ons", day_thu: "Tor", day_fri: "Fre", day_sat: "Lør", day_sun: "Søn",
      kind_closed: "Stengt veg", kind_accident: "Ulykke", kind_convoy: "Kolonnekjøring", kind_obstruction: "Hindring",
      kind_traffic: "Kø", kind_restriction: "Trafikkregulering", kind_roadworks: "Vegarbeid", kind_conditions: "Føreforhold",
      kind_info: "Trafikkmelding",
      ed_route: "Rute", ed_title: "Tittel (valgfri)", ed_height: "Karthøyde (px)", ed_list: "Vis listen",
      ed_google: "Vis Google Maps-knappen", ed_landscape: "Kartet ved siden av listen (brede kort)", ed_first: "Første rute",
    },
  };
  const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
  const KIND_ICONS = {
    closed: "mdi:road-variant", accident: "mdi:car-emergency", convoy: "mdi:car-multiple", obstruction: "mdi:alert-octagon",
    traffic: "mdi:car-clock", restriction: "mdi:traffic-light", roadworks: "mdi:account-hard-hat",
    conditions: "mdi:snowflake-alert", info: "mdi:information-outline",
  };
  const KIND_COLORS = {
    closed: "#d32f2f", accident: "#d32f2f", convoy: "#f57c00", obstruction: "#f57c00", traffic: "#f57c00",
    restriction: "#fbc02d", roadworks: "#fbc02d", conditions: "#0288d1", info: "#607d8b",
  };
  const ROUTE_COLOR = "#1e88e5";
  const ALT_COLOR = "#90a4ae";

  function lang(hass) {
    const code = String((hass && (hass.locale && hass.locale.language)) || (hass && hass.language) || "en").toLowerCase();
    return code.startsWith("nb") || code.startsWith("nn") || code.startsWith("no") ? "nb" : "en";
  }
  function t(hass, key, vars) {
    const table = I18N[lang(hass)] || I18N.en;
    let text = table[key] !== undefined ? table[key] : I18N.en[key] !== undefined ? I18N.en[key] : key;
    if (vars) for (const [k, v] of Object.entries(vars)) text = text.split(`{${k}}`).join(String(v));
    return text;
  }
  function esc(text) {
    return String(text === undefined || text === null ? "" : text).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }
  function locale(hass) {
    return lang(hass) === "nb" ? "nb-NO" : (hass && hass.locale && hass.locale.language) || "en-GB";
  }
  function when(hass, iso, withDay = true) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return "";
    const today = new Date();
    const sameDay = d.toDateString() === today.toDateString();
    const opts = { hour: "2-digit", minute: "2-digit" };
    if (withDay && !sameDay) opts.weekday = "short";
    return d.toLocaleString(locale(hass), opts);
  }
  function km(meters) {
    return (Math.round((meters || 0) / 100) / 10).toFixed(1);
  }

  // ---- the map -------------------------------------------------------------------

  function ensureHaMap() {
    if (customElements.get("ha-map")) return Promise.resolve();
    // ha-map is loaded on demand; a location selector pulls it in.
    let probe;
    try {
      const ha = document.querySelector("home-assistant");
      probe = document.createElement("ha-selector");
      probe.hass = ha && ha.hass;
      probe.selector = { location: {} };
      probe.value = { latitude: 0, longitude: 0 };
      probe.style.cssText = "position:fixed;left:-9999px;top:0;width:10px;height:10px";
      document.body.appendChild(probe);
    } catch (err) {
      probe = undefined;
    }
    return Promise.race([
      customElements.whenDefined("ha-map"),
      new Promise((resolve) => setTimeout(resolve, 8000)),
    ]).then(() => probe && probe.remove());
  }

  function element(css) {
    const el = document.createElement("div");
    el.style.cssText = css;
    return el;
  }

  /** One small vocabulary for drawing, whatever engine ha-map runs. */
  function mapHandles(haMap) {
    if (!haMap) return null;
    const leaflet = (L, map) => ({
      kind: "leaflet",
      centre: () => {
        const c = map.getCenter();
        return { lat: c.lat, lon: c.lng };
      },
      line: (points, o) => {
        const line = L.polyline(points, { color: o.color, weight: o.width, opacity: o.opacity, interactive: false });
        line.addTo(map);
        return { remove: () => line.remove() };
      },
      marker: (point, html, size) => {
        const m = L.marker(point, {
          interactive: false,
          icon: L.divIcon({ className: "", iconSize: [size, size], iconAnchor: [size / 2, size / 2], html }),
        });
        m.addTo(map);
        return { remove: () => m.remove() };
      },
      fit: (points) => {
        try {
          map.fitBounds(L.latLngBounds(points), { padding: [28, 28], maxZoom: 15 });
        } catch (err) { /* map gone */ }
      },
    });
    if (haMap.leafletMap && haMap.Leaflet && typeof haMap.leafletMap.getBounds === "function") {
      return leaflet(haMap.Leaflet, haMap.leafletMap);
    }
    const engine = haMap._engine;
    if (!engine) return null;
    if (engine.leafletMap && engine.Leaflet && typeof engine.leafletMap.getBounds === "function") {
      return leaflet(engine.Leaflet, engine.leafletMap);
    }
    const inner = engine._map;
    if (!inner || typeof engine.addPath !== "function" || typeof engine.addMarker !== "function" ||
        typeof haMap.fitBounds !== "function") {
      return null;
    }
    return {
      kind: "engine",
      centre: () => {
        const view = typeof haMap.getView === "function" ? haMap.getView() : null;
        if (view && view.center) return { lat: view.center[0], lon: view.center[1] };
        const c = inner.getCenter();
        return { lat: c.lat, lon: c.lng };
      },
      line: (points, o) => {
        const handle = engine.addPath({ color: o.color, segments: [{ points, opacity: o.opacity }], markers: [] });
        const id = Number.isFinite(engine._idCounter) ? "ha-map-path-" + (engine._idCounter - 1) + "-lines" : null;
        const apply = () => {
          if (!id) return;
          try {
            if (inner.getLayer(id) && inner.getPaintProperty(id, "line-width") !== o.width) {
              inner.setPaintProperty(id, "line-width", o.width);
            }
          } catch (err) { /* style loading */ }
        };
        apply();
        inner.on("styledata", apply);
        return {
          remove: () => {
            try { inner.off("styledata", apply); } catch (err) { /* map gone */ }
            try { handle.remove(); } catch (err) { /* map gone */ }
          },
        };
      },
      marker: (point, html, size) => {
        const el = element("pointer-events:none");
        el.innerHTML = html;
        const handle = engine.addMarker(el, point, { size: [size, size], interactive: false });
        return { remove: () => { try { handle.remove(); } catch (err) { /* map gone */ } } };
      },
      fit: (points) => {
        const el = inner.getContainer();
        const small = el && (el.clientWidth < 200 || el.clientHeight < 160);
        try {
          haMap.fitBounds(points, { zoom: 15, pad: 0.05, padding: small ? 8 : { top: 34, right: 34, bottom: 24, left: 34 } });
        } catch (err) { /* map gone */ }
      },
    };
  }

  function pinHtml(label, color) {
    return `<div style="width:26px;height:26px;border-radius:50%;background:${color};color:#fff;border:2px solid #fff;` +
      `box-shadow:0 1px 4px rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;` +
      `font:600 13px/1 system-ui,sans-serif;box-sizing:border-box">${esc(label)}</div>`;
  }
  function incidentHtml(kind) {
    const color = KIND_COLORS[kind] || KIND_COLORS.info;
    const icon = KIND_ICONS[kind] || KIND_ICONS.info;
    return `<div style="width:30px;height:30px;border-radius:50%;background:#fff;border:3px solid ${color};` +
      `box-shadow:0 1px 4px rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;box-sizing:border-box">` +
      `<ha-icon icon="${icon}" style="--mdc-icon-size:17px;color:${color}"></ha-icon></div>`;
  }

  // ---- the card --------------------------------------------------------------------

  const STYLE = `
    :host { display: block; }
    ha-card { overflow: hidden; }
    .head { display: flex; align-items: center; gap: 8px; padding: 12px 16px 4px; }
    .head h2 { flex: 1; margin: 0; font-size: 1.15em; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .head select { max-width: 50%; }
    select, input { font: inherit; color: var(--primary-text-color); background: var(--card-background-color, #fff);
      border: 1px solid var(--divider-color, #ccc); border-radius: 6px; padding: 6px 8px; box-sizing: border-box; }
    .status { margin: 6px 16px 8px; padding: 10px 12px; border-radius: 8px; display: flex; gap: 10px; align-items: flex-start; }
    .status.ok { background: color-mix(in srgb, var(--success-color, #43a047) 14%, transparent); }
    .status.bad { background: color-mix(in srgb, var(--error-color, #db4437) 16%, transparent); }
    .status ha-icon { flex: none; margin-top: 1px; }
    .status.ok ha-icon { color: var(--success-color, #43a047); }
    .status.bad ha-icon { color: var(--error-color, #db4437); }
    .status .main { font-weight: 500; }
    .sub { color: var(--secondary-text-color); font-size: .9em; margin-top: 2px; }
    .body { display: block; }
    .body.landscape { display: grid; grid-template-columns: 3fr 2fr; }
    .map { position: relative; margin: 0 16px; border-radius: 8px; overflow: hidden; background: var(--secondary-background-color, #eee); }
    .map ha-map { display: block; height: 100%; }
    .nomap { padding: 16px; color: var(--secondary-text-color); }
    .list { margin: 8px 16px 4px; }
    .item { display: flex; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--divider-color, #ddd); }
    .item:last-child { border-bottom: none; }
    .item ha-icon { flex: none; margin-top: 2px; }
    .item .what { font-weight: 500; }
    .empty { color: var(--secondary-text-color); padding: 8px 0; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; padding: 8px 16px 14px; }
    button { font: inherit; cursor: pointer; border-radius: 18px; padding: 6px 14px; border: 1px solid var(--divider-color, #ccc);
      background: transparent; color: var(--primary-text-color); }
    button.primary { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
    button:disabled { opacity: .5; cursor: default; }
    button.icon { border-radius: 50%; width: 32px; height: 32px; padding: 0; display: inline-flex; align-items: center; justify-content: center; }
    a.button { text-decoration: none; display: inline-flex; align-items: center; gap: 4px; font: inherit; border-radius: 18px;
      padding: 6px 14px; border: 1px solid var(--divider-color, #ccc); color: var(--primary-text-color); }
    .planner { margin: 10px 16px 4px; padding: 12px; border: 1px solid var(--divider-color, #ccc); border-radius: 10px; }
    .planner h3 { margin: 0 0 10px; font-size: 1.05em; font-weight: 500; }
    .field { margin-bottom: 10px; }
    .field label { display: block; font-size: .85em; color: var(--secondary-text-color); margin-bottom: 3px; }
    .field input[type=text], .field input[type=number], .field input[type=time] { width: 100%; }
    .stop { display: flex; gap: 6px; align-items: center; position: relative; margin-bottom: 6px; }
    .stop .tag { flex: none; width: 46px; font-size: .85em; color: var(--secondary-text-color); }
    .stop input { flex: 1; min-width: 0; }
    .stop.set input { border-color: var(--primary-color); }
    .suggest { position: absolute; z-index: 5; left: 52px; right: 40px; top: 100%; background: var(--card-background-color, #fff);
      border: 1px solid var(--divider-color, #ccc); border-radius: 8px; box-shadow: 0 4px 14px rgba(0,0,0,.25); max-height: 260px; overflow: auto; }
    .suggest div { padding: 7px 10px; cursor: pointer; display: flex; gap: 8px; align-items: center; }
    .suggest div:hover, .suggest div.active { background: color-mix(in srgb, var(--primary-color) 14%, transparent); }
    .suggest small { color: var(--secondary-text-color); }
    .chips { display: flex; flex-wrap: wrap; gap: 6px; }
    .chip { border-radius: 16px; padding: 4px 10px; border: 1px solid var(--divider-color, #ccc); cursor: pointer; user-select: none;
      display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; }
    .chip.on { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
    .chip input { border: none; background: transparent; width: 92px; padding: 0; }
    .row { display: flex; gap: 10px; flex-wrap: wrap; }
    .row .field { flex: 1; min-width: 120px; }
    .hint { font-size: .8em; color: var(--secondary-text-color); margin-top: 3px; }
    .error { color: var(--error-color, #db4437); margin: 6px 0; }
    .options div { padding: 7px 10px; border-radius: 8px; cursor: pointer; display: flex; gap: 8px; align-items: center; }
    .options div.on { background: color-mix(in srgb, var(--primary-color) 14%, transparent); font-weight: 500; }
    .swatch { width: 14px; height: 4px; border-radius: 2px; flex: none; }
  `;

  class VegvarselCard extends HTMLElement {
    static getConfigElement() {
      return document.createElement(EDITOR_TAG);
    }

    static getStubConfig() {
      return {};
    }

    setConfig(config) {
      if (!config) throw new Error("Invalid configuration");
      this._config = { map_height: 320, show_list: true, show_google: true, landscape: false, ...config };
      if (this._built) this._render();
    }

    set hass(hass) {
      const first = !this._hass;
      this._hass = hass;
      if (this._haMap) this._haMap.hass = hass;
      if (first) {
        this._build();
        this._fetch();
        return;
      }
      if (this._changed(hass)) this._scheduleFetch();
    }

    get hass() {
      return this._hass;
    }

    getCardSize() {
      return 6;
    }

    getGridOptions() {
      return { columns: 12, min_columns: 6, rows: "auto" };
    }

    connectedCallback() {
      (window.__vegvarselInstances || (window.__vegvarselInstances = new Set())).add(this);
    }

    disconnectedCallback() {
      if (window.__vegvarselInstances) window.__vegvarselInstances.delete(this);
    }

    // ---- data ----------------------------------------------------------------

    /** Did any of the integration's entities change state since last time? */
    _changed(hass) {
      const ids = this._watchIds(hass);
      let changed = false;
      const seen = this._seen || (this._seen = {});
      for (const id of ids) {
        const s = hass.states[id];
        const stamp = s ? s.last_updated : "";
        if (seen[id] !== stamp) {
          seen[id] = stamp;
          changed = true;
        }
      }
      return changed;
    }

    _watchIds(hass) {
      if (!this._ids || this._idsFor !== hass.entities) {
        this._idsFor = hass.entities;
        this._ids = Object.values(hass.entities || {})
          .filter((e) => e.platform === "vegvarsel")
          .map((e) => e.entity_id);
      }
      return this._ids;
    }

    _scheduleFetch() {
      clearTimeout(this._fetchTimer);
      this._fetchTimer = setTimeout(() => this._fetch(), 1000);
    }

    async _fetch() {
      if (!this._hass) return;
      try {
        const result = await this._hass.connection.sendMessagePromise({ type: "vegvarsel/routes" });
        this._routes = (result && result.routes) || [];
        this._starting = !!(result && result.starting);
        this._error = null;
        clearTimeout(this._startTimer);
        if (this._starting) this._startTimer = setTimeout(() => this._fetch(), 5000);
      } catch (err) {
        this._routes = this._routes || [];
        this._error = (err && (err.code === "unknown_command" ? t(this._hass, "no_integration") : err.message)) || String(err);
      }
      this._loaded = true;
      this._render();
    }

    _route() {
      const routes = this._routes || [];
      const wanted = this._selected || (this._config && this._config.route_id);
      return routes.find((r) => r.route_id === wanted) || routes[0] || null;
    }

    // ---- building --------------------------------------------------------------

    _build() {
      if (this._built) return;
      this._built = true;
      const root = this.attachShadow({ mode: "open" });
      root.innerHTML = `<style>${STYLE}</style><ha-card>
        <div class="head"><h2></h2><select class="pick" hidden></select></div>
        <div class="statusbox"></div>
        <div class="body"><div class="mapcol"><div class="map"></div></div><div class="side">
          <div class="plannerbox"></div><div class="list"></div></div></div>
        <div class="actions cardactions"></div></ha-card>`;
      root.querySelector(".pick").addEventListener("change", (ev) => {
        this._selected = ev.target.value;
        this._closePlanner();
        this._render();
      });
      this._makeMap();
    }

    async _makeMap() {
      const box = this.shadowRoot.querySelector(".map");
      box.style.height = `${(this._config && this._config.map_height) || 320}px`;
      await ensureHaMap();
      if (!customElements.get("ha-map")) {
        box.innerHTML = "";
        return;
      }
      const map = document.createElement("ha-map");
      map.hass = this._hass;
      map.entities = [];
      box.appendChild(map);
      this._haMap = map;
      this._drawn = [];
      this._waitForHandles(0);
    }

    _waitForHandles(attempt) {
      const h = mapHandles(this._haMap);
      if (h) {
        this._handles = h;
        this._draw();
        return;
      }
      if (attempt < 60) setTimeout(() => this._waitForHandles(attempt + 1), 250);
    }

    // ---- rendering ------------------------------------------------------------------

    _render() {
      if (!this._built) return;
      const root = this.shadowRoot;
      const hass = this._hass;
      const cfg = this._config || {};
      const route = this._route();
      const routes = this._routes || [];

      const title = cfg.title || (route ? route.name : t(hass, "name"));
      root.querySelector("h2").textContent = this._planner ? "" : title;
      root.querySelector("h2").hidden = !!this._planner;
      const pick = root.querySelector(".pick");
      pick.hidden = this._planner || routes.length < 2;
      pick.innerHTML = routes.map((r) =>
        `<option value="${esc(r.route_id)}"${route && r.route_id === route.route_id ? " selected" : ""}>${esc(r.name)}</option>`).join("");

      root.querySelector(".body").className = "body" + (cfg.landscape ? " landscape" : "");
      root.querySelector(".map").style.height = `${cfg.map_height || 320}px`;

      // status
      const status = root.querySelector(".statusbox");
      if (!this._loaded) {
        status.innerHTML = `<div class="status"><div class="sub">${esc(t(hass, "loading"))}</div></div>`;
      } else if (this._error) {
        status.innerHTML = `<div class="status bad"><ha-icon icon="mdi:alert"></ha-icon><div>${esc(this._error)}</div></div>`;
      } else if (!route) {
        status.innerHTML = `<div class="status"><div class="sub">${esc(t(hass, this._starting ? "starting" : "no_routes"))}</div></div>`;
      } else if (this._planner) {
        status.innerHTML = "";
      } else {
        status.innerHTML = this._statusHtml(route);
      }

      // list
      const list = root.querySelector(".list");
      if (this._planner) {
        list.innerHTML = this._planner.plans ? this._incidentsHtml(this._chosenPlan().incidents) : "";
      } else if (route && cfg.show_list !== false) {
        list.innerHTML = this._incidentsHtml(route.incidents);
      } else {
        list.innerHTML = "";
      }

      // actions
      const actions = root.querySelector(".cardactions");
      actions.hidden = !!this._planner;
      if (!this._planner) {
        const admin = hass && hass.user && hass.user.is_admin;
        const buttons = [];
        if (route && cfg.show_google !== false) {
          buttons.push(`<a class="button" target="_blank" rel="noopener" href="${esc(googleUrl(route))}">` +
            `<ha-icon icon="mdi:google-maps" style="--mdc-icon-size:18px"></ha-icon>${esc(t(hass, "google"))}</a>`);
        }
        if (admin && route) buttons.push(`<button class="edit">${esc(t(hass, "edit"))}</button>`);
        if (admin && this._loaded && !this._error) buttons.push(`<button class="new">+ ${esc(t(hass, "new_route"))}</button>`);
        actions.innerHTML = buttons.join("");
        const edit = actions.querySelector(".edit");
        if (edit) edit.addEventListener("click", () => this._openPlanner(route));
        const add = actions.querySelector(".new");
        if (add) add.addEventListener("click", () => this._openPlanner(null));
      }
      this._draw();
    }

    _statusHtml(route) {
      const hass = this._hass;
      const worst = [...(route.incidents || [])].sort((a, b) => (b.rank || 0) - (a.rank || 0))[0];
      const lines = [];
      if (!route.windows || !route.windows.length) {
        lines.push(t(hass, "always"));
      } else if (route.in_window) {
        lines.push(t(hass, "watching_now", { until: when(hass, route.watching_until, false) }));
      } else if (route.watching_from) {
        lines.push(t(hass, "watching", { from: when(hass, route.watching_from), until: when(hass, route.watching_until, false) }));
      }
      const closure = route.next_closure;
      if (closure) {
        const place = closure.road || (closure.places && closure.places[0]) || "";
        lines.push(closure.applies_now
          ? `${t(hass, "closure_now", { when: when(hass, closure.start) })}${place ? " · " + place : ""}`
          : `${t(hass, "next_closure", { when: when(hass, closure.start) })}${place ? " · " + place : ""}`);
      }
      const sub = lines.map((l) => `<div class="sub">${esc(l)}</div>`).join("");
      if (route.problem) {
        const what = worst ? `${worst.kind_name || t(hass, "kind_" + worst.kind)}${worst.road ? " · " + worst.road : ""}` : "";
        return `<div class="status bad"><ha-icon icon="mdi:alert-octagon"></ha-icon><div>` +
          `<div class="main">${esc(t(hass, "problem"))}</div>${what ? `<div>${esc(what)}</div>` : ""}${sub}</div></div>`;
      }
      return `<div class="status ok"><ha-icon icon="mdi:check-circle"></ha-icon><div>` +
        `<div class="main">${esc(t(hass, "clear"))}</div>${sub}</div></div>`;
    }

    _incidentsHtml(incidents) {
      const hass = this._hass;
      if (!incidents || !incidents.length) return `<div class="empty">${esc(t(hass, "nothing"))}</div>`;
      return [...incidents].sort((a, b) => (a.distance_km || 0) - (b.distance_km || 0)).map((i) => {
        const color = KIND_COLORS[i.kind] || KIND_COLORS.info;
        const time = i.applies_now
          ? (i.end ? t(hass, "until_time", { when: when(hass, i.end) }) : "")
          : (i.start ? t(hass, "from_time", { when: when(hass, i.start) }) : "");
        const head = [i.kind_name || t(hass, "kind_" + i.kind), i.road, i.distance_km !== undefined && i.distance_km !== ""
          ? t(hass, "km", { km: Number(i.distance_km).toFixed(1) }) : ""].filter(Boolean).join(" · ");
        const place = (i.places && i.places[0]) || "";
        return `<div class="item"><ha-icon icon="${KIND_ICONS[i.kind] || KIND_ICONS.info}" style="color:${color}"></ha-icon><div>` +
          `<div class="what">${esc(head)}</div>` +
          (place ? `<div class="sub">${esc(place)}</div>` : "") +
          (i.description ? `<div class="sub">${esc(i.description)}</div>` : "") +
          (time ? `<div class="sub">${esc(time)}</div>` : "") + `</div></div>`;
      }).join("");
    }

    // ---- drawing --------------------------------------------------------------------------

    _clearDrawn() {
      for (const d of this._drawn || []) {
        try { d.remove(); } catch (err) { /* gone */ }
      }
      this._drawn = [];
    }

    _draw() {
      const h = this._handles;
      if (!h) return;
      const signature = JSON.stringify(this._drawSignature());
      if (signature === this._lastDrawn) return;
      this._lastDrawn = signature;
      this._clearDrawn();
      const add = (d) => d && this._drawn.push(d);
      const toPoints = (pts) => (pts || []).map((p) => [p[0], p[1]]);

      let points = [];
      let ends = [];
      let incidents = [];
      if (this._planner) {
        const p = this._planner;
        if (p.plans) {
          p.plans.forEach((plan, i) => {
            if (i !== p.chosen) add(h.line(toPoints(plan.points), { color: ALT_COLOR, width: 5, opacity: 0.85 }));
          });
          const chosen = this._chosenPlan();
          points = toPoints(chosen.points);
          add(h.line(points, { color: ROUTE_COLOR, width: 6, opacity: 0.95 }));
          incidents = chosen.incidents || [];
          p.plans.forEach((plan) => { points = points.concat(toPoints(plan.points)); });
        } else if (p.saved && p.saved.length > 1) {
          // the route as it is now, until a new one is calculated
          points = toPoints(p.saved);
          add(h.line(points, { color: ROUTE_COLOR, width: 5, opacity: 0.5 }));
        }
        ends = this._plannerStops();
      } else {
        const route = this._route();
        if (route) {
          points = toPoints(route.points);
          if (points.length > 1) add(h.line(points, { color: ROUTE_COLOR, width: 6, opacity: 0.95 }));
          ends = [route.start, ...(route.vias || []), route.destination].filter(Boolean);
          incidents = route.incidents || [];
        }
      }
      ends.forEach((place, i) => {
        if (!place) return;
        const last = i === ends.length - 1;
        const label = i === 0 ? "A" : last ? "B" : String(i);
        const color = i === 0 ? "#2e7d32" : last ? "#c62828" : "#5e35b1";
        add(h.marker([place.latitude, place.longitude], pinHtml(label, color), 26));
        points.push([place.latitude, place.longitude]);
      });
      for (const i of incidents) {
        if (i.latitude === null || i.latitude === undefined) continue;
        add(h.marker([i.latitude, i.longitude], incidentHtml(i.kind), 30));
      }
      if (points.length) {
        const fit = () => h.fit(points);
        fit();
        // ha-map fits itself once more when it has loaded; fit again after.
        setTimeout(fit, 600);
        setTimeout(fit, 1600);
      }
    }

    _drawSignature() {
      if (this._planner) {
        const p = this._planner;
        return ["plan", p.chosen, !!p.saved, (p.plans || []).map((x) => x.points.length + ":" + x.distance_m),
          this._plannerStops().map((s) => s && [s.latitude, s.longitude])];
      }
      const r = this._route();
      return r ? ["route", r.route_id, r.points.length, r.points[0], (r.incidents || []).map((i) => i.id + i.kind),
        [r.start, ...(r.vias || []), r.destination].map((s) => s && [s.latitude, s.longitude])] : ["none"];
    }

    // ---- the planner -----------------------------------------------------------------------

    _openPlanner(route) {
      const hass = this._hass;
      const home = hass.states["zone.home"];
      const homePlace = home && home.attributes.latitude !== undefined
        ? { label: home.attributes.friendly_name || "Home", latitude: home.attributes.latitude, longitude: home.attributes.longitude }
        : null;
      this._planner = route
        ? {
            route_id: route.route_id,
            name: route.name,
            stops: [route.start, ...(route.vias || []), route.destination].map((s) => ({ ...s })),
            saved: route.points,
            savedPlan: { points: route.points, distance_m: route.distance_m, duration_s: route.duration_s },
            dirty: false,
            days: new Set(route.days && route.days.length ? route.days : DAYS.slice(0, 5)),
            windows: [...(route.windows || [])],
            preview: route.preview ? String(route.preview).slice(0, 5) : "",
            corridor: route.corridor_m || 150,
            plans: null,
            chosen: 0,
          }
        : {
            route_id: null,
            name: "",
            stops: [homePlace, null],
            days: new Set(DAYS.slice(0, 5)),
            windows: ["06:30-08:00"],
            preview: "21:00",
            corridor: 150,
            plans: null,
            chosen: 0,
          };
      this._renderPlanner();
      this._render();
      this._nameStops();
    }

    /** Stops picked on a map are only coordinates: ask for the nearest address. */
    async _nameStops() {
      const p = this._planner;
      if (!p) return;
      const bare = /^-?\d+\.\d+, ?-?\d+\.\d+$/;
      for (const stop of p.stops) {
        if (!stop || !bare.test(stop.label || "")) continue;
        try {
          const r = await this._hass.connection.sendMessagePromise({
            type: "vegvarsel/where", latitude: stop.latitude, longitude: stop.longitude,
          });
          if (r && r.label && this._planner === p) {
            stop.label = r.label;
            const input = this.shadowRoot.querySelector(`.plannerbox .stop input[data-i="${p.stops.indexOf(stop)}"]`);
            if (input && this.shadowRoot.activeElement !== input) input.value = r.label;
          }
        } catch (err) {
          /* an older backend without vegvarsel/where: keep the coordinates */
        }
      }
    }

    _closePlanner() {
      if (!this._planner) return;
      this._planner = null;
      this.shadowRoot.querySelector(".plannerbox").innerHTML = "";
      this._lastDrawn = null;
    }

    _plannerStops() {
      return (this._planner && this._planner.stops) || [];
    }

    _chosenPlan() {
      const p = this._planner;
      return p && p.plans ? p.plans[Math.min(p.chosen, p.plans.length - 1)] : null;
    }

    _renderPlanner() {
      const p = this._planner;
      const hass = this._hass;
      const box = this.shadowRoot.querySelector(".plannerbox");
      if (!p) {
        box.innerHTML = "";
        return;
      }
      const n = p.stops.length;
      const stopRows = p.stops.map((s, i) => {
        const tag = i === 0 ? t(hass, "from") : i === n - 1 ? t(hass, "to") : t(hass, "stop", { n: i });
        const tools = i === 0
          ? `<button class="icon swap" title="${esc(t(hass, "swap"))}"><ha-icon icon="mdi:swap-vertical"></ha-icon></button>`
          : i < n - 1
            ? `<button class="icon remove" data-i="${i}" title="${esc(t(hass, "remove"))}"><ha-icon icon="mdi:close"></ha-icon></button>`
            : `<span style="width:32px"></span>`;
        return `<div class="stop${s ? " set" : ""}" data-i="${i}"><span class="tag">${esc(tag)}</span>` +
          `<input type="text" data-i="${i}" placeholder="${esc(t(hass, "search_hint"))}" value="${esc(s ? s.label : "")}" autocomplete="off">` +
          `${tools}</div>`;
      }).join("");
      const dayChips = DAYS.map((d) =>
        `<span class="chip day${p.days.has(d) ? " on" : ""}" data-d="${d}">${esc(t(hass, "day_" + d))}</span>`).join("");
      const windowChips = p.windows.map((w, i) =>
        `<span class="chip"><input type="text" class="window" data-i="${i}" value="${esc(w)}" placeholder="06:45-08:15">` +
        `<ha-icon icon="mdi:close" class="drop" data-i="${i}" style="--mdc-icon-size:16px;cursor:pointer"></ha-icon></span>`).join("");
      box.innerHTML = `<div class="planner">
        <h3>${esc(p.route_id ? t(hass, "planner_edit", { name: p.name }) : t(hass, "planner_new"))}</h3>
        <div class="field"><label>${esc(t(hass, "route_name"))}</label><input type="text" class="name" value="${esc(p.name)}"></div>
        <div class="stops">${stopRows}</div>
        <button class="addstop">+ ${esc(t(hass, "add_stop"))}</button>
        <div class="field" style="margin-top:12px"><label>${esc(t(hass, "days"))}</label><div class="chips">${dayChips}</div></div>
        <div class="field"><label>${esc(t(hass, "windows"))}</label><div class="chips">${windowChips}
          <span class="chip addwin">+ ${esc(t(hass, "add_window"))}</span></div><div class="hint">${esc(t(hass, "window_hint"))}</div></div>
        <div class="row">
          <div class="field"><label>${esc(t(hass, "preview"))}</label><input type="time" class="preview" value="${esc(p.preview)}">
            <div class="hint">${esc(t(hass, "preview_hint"))}</div></div>
          <div class="field"><label>${esc(t(hass, "corridor"))}</label><input type="number" class="corridor" min="30" max="1000" step="10" value="${esc(p.corridor)}"></div>
        </div>
        <div class="options"></div>
        <div class="error" hidden></div>
        <div class="actions" style="padding:8px 0 0">
          <button class="primary calc">${esc(t(hass, "calculate"))}</button>
          <button class="primary save"${this._savePlan() ? "" : " disabled"}>${esc(t(hass, "save"))}</button>
          <button class="discard">${esc(t(hass, "discard"))}</button>
        </div></div>`;

      box.querySelector(".name").addEventListener("input", (ev) => { p.name = ev.target.value; });
      box.querySelectorAll(".stop input").forEach((input) => this._wireStopInput(input));
      const swap = box.querySelector(".swap");
      if (swap) swap.addEventListener("click", () => {
        p.stops.reverse();
        this._invalidate();
      });
      box.querySelectorAll(".remove").forEach((b) => b.addEventListener("click", () => {
        p.stops.splice(Number(b.dataset.i), 1);
        this._invalidate();
      }));
      box.querySelector(".addstop").addEventListener("click", () => {
        p.stops.splice(p.stops.length - 1, 0, null);
        this._renderPlanner();
        const inputs = box.querySelectorAll(".stop input");
        inputs[inputs.length - 2].focus();
      });
      box.querySelectorAll(".day").forEach((c) => c.addEventListener("click", () => {
        const d = c.dataset.d;
        if (p.days.has(d)) p.days.delete(d); else p.days.add(d);
        c.classList.toggle("on", p.days.has(d));
      }));
      box.querySelectorAll(".window").forEach((w) => w.addEventListener("input", () => { p.windows[Number(w.dataset.i)] = w.value; }));
      box.querySelectorAll(".drop").forEach((x) => x.addEventListener("click", () => {
        p.windows.splice(Number(x.dataset.i), 1);
        this._renderPlanner();
      }));
      box.querySelector(".addwin").addEventListener("click", () => {
        p.windows.push("");
        this._renderPlanner();
        const ws = box.querySelectorAll(".window");
        ws[ws.length - 1].focus();
      });
      box.querySelector(".preview").addEventListener("input", (ev) => { p.preview = ev.target.value; });
      box.querySelector(".corridor").addEventListener("input", (ev) => { p.corridor = ev.target.value; });
      box.querySelector(".calc").addEventListener("click", () => this._calculate());
      box.querySelector(".save").addEventListener("click", () => this._save());
      box.querySelector(".discard").addEventListener("click", () => {
        this._closePlanner();
        this._render();
      });
      this._renderOptions();
    }

    /** The line Save would store: the chosen calculation, or - when editing
     * and no place changed - the route's own line, so a change of times or
     * name needs no recalculation. */
    _savePlan() {
      const p = this._planner;
      if (!p) return null;
      return this._chosenPlan() || (!p.dirty && p.savedPlan && p.savedPlan.points && p.savedPlan.points.length > 1 ? p.savedPlan : null);
    }

    /** A stop or the ends changed: what was calculated no longer holds. */
    _invalidate() {
      if (this._planner) {
        this._planner.plans = null;
        this._planner.chosen = 0;
        this._planner.dirty = true;
        this._planner.saved = null;
      }
      this._renderPlanner();
      this._render();
    }

    _renderOptions() {
      const p = this._planner;
      const hass = this._hass;
      const box = this.shadowRoot.querySelector(".plannerbox .options");
      if (!box) return;
      if (!p.plans) {
        box.innerHTML = "";
        return;
      }
      box.innerHTML = `<label style="font-size:.85em;color:var(--secondary-text-color)">${esc(t(hass, "routes_found"))}</label>` +
        p.plans.map((plan, i) => {
          const count = (plan.incidents || []).length;
          const key = count === 0 ? "route_option_0" : count === 1 ? "route_option_1" : "route_option";
          const text = t(hass, key, { km: km(plan.distance_m), min: Math.round((plan.duration_s || 0) / 60), n: count });
          return `<div data-i="${i}" class="${i === p.chosen ? "on" : ""}"><span class="swatch" style="background:${i === p.chosen ? ROUTE_COLOR : ALT_COLOR}"></span>${esc(text)}</div>`;
        }).join("");
      box.querySelectorAll("div[data-i]").forEach((row) => row.addEventListener("click", () => {
        p.chosen = Number(row.dataset.i);
        this._renderOptions();
        this._render();
      }));
    }

    _wireStopInput(input) {
      const p = this._planner;
      const i = Number(input.dataset.i);
      let timer = null;
      let token = 0;
      const row = input.parentElement;
      const close = () => {
        const old = row.querySelector(".suggest");
        if (old) old.remove();
      };
      const show = (items) => {
        close();
        if (!items.length) return;
        const list = document.createElement("div");
        list.className = "suggest";
        list.innerHTML = items.map((it, k) =>
          `<div data-k="${k}"><ha-icon icon="${it.icon}" style="--mdc-icon-size:18px;color:var(--secondary-text-color)"></ha-icon>` +
          `<span>${esc(it.label)}${it.note ? ` <small>${esc(it.note)}</small>` : ""}</span></div>`).join("");
        list.addEventListener("mousedown", (ev) => ev.preventDefault()); // keep focus until chosen
        list.querySelectorAll("div[data-k]").forEach((el) => el.addEventListener("click", () => {
          const it = items[Number(el.dataset.k)];
          choose(it.place());
        }));
        row.appendChild(list);
      };
      const choose = (place) => {
        close();
        if (!place) return;
        p.stops[i] = place;
        this._invalidate();
        this._nameStops();
      };
      const local = (text) => {
        const hass = this._hass;
        const q = text.trim().toLowerCase();
        const out = [];
        out.push({
          icon: "mdi:crosshairs-gps", label: t(hass, "map_centre"), note: "",
          place: () => {
            const c = this._handles && this._handles.centre();
            return c ? { label: `${c.lat.toFixed(5)}, ${c.lon.toFixed(5)}`, latitude: c.lat, longitude: c.lon } : null;
          },
        });
        for (const [id, s] of Object.entries(hass.states)) {
          if (!(id.startsWith("zone.") || id.startsWith("person.")) || s.attributes.latitude === undefined) continue;
          const name = s.attributes.friendly_name || id;
          if (q && !name.toLowerCase().includes(q)) continue;
          out.push({
            icon: id.startsWith("zone.") ? (s.attributes.icon || "mdi:map-marker-radius") : "mdi:account",
            label: name, note: t(hass, id.startsWith("zone.") ? "zone" : "person"),
            place: () => ({ label: name, latitude: s.attributes.latitude, longitude: s.attributes.longitude }),
          });
        }
        return out.slice(0, 8);
      };
      input.addEventListener("focus", () => {
        input.__vvOpen = true;
        show(local(input.value === (p.stops[i] && p.stops[i].label) ? "" : input.value));
      });
      input.addEventListener("blur", () => setTimeout(() => {
        input.__vvOpen = false;
        close();
        if (p.stops[i] && input.value !== p.stops[i].label) input.value = p.stops[i].label;
      }, 150));
      input.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape") close();
        if (ev.key === "Enter") {
          const first = row.querySelector(".suggest div[data-k]");
          if (first) first.click();
        }
      });
      input.addEventListener("input", () => {
        input.__vvOpen = true;
        const text = input.value;
        clearTimeout(timer);
        const zones = local(text).filter((it) => it.note); // zones and persons that match
        if (text.trim().length < 3) {
          show(zones);
          return;
        }
        show(zones.concat([{ icon: "mdi:magnify", label: t(this._hass, "searching"), note: "", place: () => null }]));
        const mine = ++token;
        timer = setTimeout(async () => {
          let places = [];
          try {
            const r = await this._hass.connection.sendMessagePromise({ type: "vegvarsel/search", text });
            places = (r && r.places) || [];
          } catch (err) {
            places = [];
          }
          if (mine !== token || !input.__vvOpen || !input.isConnected) return;
          show(zones.concat(places.map((pl) => ({
            icon: pl.kind === "address" ? "mdi:home-map-marker" : "mdi:map-marker",
            label: pl.label, note: "",
            place: () => ({ label: pl.label, latitude: pl.latitude, longitude: pl.longitude }),
          }))));
        }, 300);
      });
    }

    _showError(text) {
      const el = this.shadowRoot.querySelector(".plannerbox .error");
      if (!el) return;
      el.hidden = !text;
      el.textContent = text || "";
    }

    async _calculate() {
      const p = this._planner;
      const hass = this._hass;
      const stops = p.stops.filter(Boolean);
      if (!p.stops[0] || !p.stops[p.stops.length - 1] || stops.length < 2) {
        this._showError(t(hass, "need_ends"));
        return;
      }
      const button = this.shadowRoot.querySelector(".plannerbox .calc");
      button.disabled = true;
      button.textContent = t(hass, "calculating");
      this._showError("");
      try {
        const corridor = Number(p.corridor) || 150;
        const r = await hass.connection.sendMessagePromise({
          type: "vegvarsel/plan",
          stops: stops.map((s) => ({ latitude: s.latitude, longitude: s.longitude, label: s.label })),
          corridor_m: Math.min(1000, Math.max(30, corridor)),
        });
        p.stops = stops.length === p.stops.length ? p.stops : [...stops];
        p.plans = (r && r.routes) || [];
        p.chosen = 0;
        this._renderPlanner();
        this._render();
      } catch (err) {
        this._showError(err && err.code === "no_route" ? t(hass, "no_route") : (err && err.message) || String(err));
        button.disabled = false;
        button.textContent = t(hass, "calculate");
      }
    }

    async _save() {
      const p = this._planner;
      const hass = this._hass;
      const plan = this._savePlan();
      if (!plan) {
        this._showError(t(hass, "calculate_first"));
        return;
      }
      const windows = p.windows.map((w) => w.trim()).filter(Boolean);
      if (windows.some((w) => !/^\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}$/.test(w))) {
        this._showError(t(hass, "bad_window"));
        return;
      }
      if (!p.days.size) {
        this._showError(t(hass, "no_days"));
        return;
      }
      const corridor = Number(p.corridor);
      if (!(corridor >= 30 && corridor <= 1000)) {
        this._showError(t(hass, "bad_corridor"));
        return;
      }
      const stops = p.stops.filter(Boolean);
      const name = (p.name || "").trim() || `${stops[0].label} – ${stops[stops.length - 1].label}`.slice(0, 80);
      const button = this.shadowRoot.querySelector(".plannerbox .save");
      button.disabled = true;
      button.textContent = t(hass, "saving");
      this._showError("");
      const msg = {
        type: "vegvarsel/save_route",
        name,
        start: stops[0],
        destination: stops[stops.length - 1],
        vias: stops.slice(1, -1),
        points: plan.points,
        distance_m: plan.distance_m,
        duration_s: plan.duration_s,
        corridor_m: corridor,
        days: DAYS.filter((d) => p.days.has(d)),
        windows,
        preview: p.preview ? (p.preview.length === 5 ? p.preview + ":00" : p.preview) : null,
      };
      if (p.route_id) msg.route_id = p.route_id;
      try {
        const r = await hass.connection.sendMessagePromise(msg);
        this._selected = r.route_id;
        this._closePlanner();
        this._loaded = false;
        this._render();
        // the integration reloads with the route; ask until it is back
        for (let k = 0; k < 20; k++) {
          await new Promise((res) => setTimeout(res, k ? 1500 : 800));
          await this._fetch();
          if ((this._routes || []).some((x) => x.route_id === r.route_id)) break;
        }
      } catch (err) {
        const text = err && err.code === "invalid_schedule"
          ? (String(err.message).includes("windows") ? t(hass, "bad_window")
            : String(err.message).includes("preview") ? t(hass, "bad_preview")
              : String(err.message).includes("days") ? t(hass, "no_days") : t(hass, "bad_corridor"))
          : (err && err.message) || String(err);
        this._showError(t(hass, "save_failed", { error: text }));
        button.disabled = false;
        button.textContent = t(hass, "save");
      }
    }

    /** Redraw after a newer copy of this file replaced the class's methods. */
    _refresh() {
      this._lastDrawn = null;
      if (this._planner) this._renderPlanner();
      this._render();
    }
  }

  function googleUrl(route) {
    const ll = (p) => `${p.latitude},${p.longitude}`;
    const params = new URLSearchParams({
      api: "1", origin: ll(route.start), destination: ll(route.destination), travelmode: "driving",
    });
    if (route.vias && route.vias.length) params.set("waypoints", route.vias.map(ll).join("|"));
    return `https://www.google.com/maps/dir/?${params.toString()}`;
  }

  // ---- the editor ------------------------------------------------------------------------

  class VegvarselCardEditor extends HTMLElement {
    setConfig(config) {
      this._config = { ...config };
      this._render();
    }

    set hass(hass) {
      const first = !this._hass;
      this._hass = hass;
      if (this._form) this._form.hass = hass;
      if (first) {
        hass.connection.sendMessagePromise({ type: "vegvarsel/routes" }).then(
          (r) => { this._routes = (r && r.routes) || []; this._render(); },
          () => { this._routes = []; this._render(); },
        );
      }
    }

    _schema() {
      const hass = this._hass;
      const options = [{ value: "", label: t(hass, "ed_first") }]
        .concat((this._routes || []).map((r) => ({ value: r.route_id, label: r.name })));
      return [
        { name: "route_id", selector: { select: { mode: "dropdown", options } } },
        { name: "title", selector: { text: {} } },
        { name: "map_height", selector: { number: { min: 160, max: 900, step: 10, mode: "box", unit_of_measurement: "px" } } },
        { name: "show_list", selector: { boolean: {} } },
        { name: "show_google", selector: { boolean: {} } },
        { name: "landscape", selector: { boolean: {} } },
      ];
    }

    _render() {
      if (!this._hass || !this._config) return;
      const labels = {
        route_id: "ed_route", title: "ed_title", map_height: "ed_height", show_list: "ed_list",
        show_google: "ed_google", landscape: "ed_landscape",
      };
      if (!this._form) {
        this._form = document.createElement("ha-form");
        this._form.computeLabel = (s) => t(this._hass, labels[s.name] || s.name);
        this._form.addEventListener("value-changed", (ev) => {
          const value = { ...ev.detail.value };
          for (const k of Object.keys(value)) if (value[k] === "" || value[k] === undefined) delete value[k];
          this._config = { type: this._config.type, ...value };
          this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
        });
        this.appendChild(this._form);
      }
      this._form.hass = this._hass;
      this._form.schema = this._schema();
      this._form.data = { map_height: 320, show_list: true, show_google: true, landscape: false, route_id: "", ...this._config };
    }
  }

  // ---- registration, and taking over from an older copy -----------------------------------

  const existing = customElements.get(TAG);
  if (existing) {
    // A newer file after an update: hand its methods to the registered class
    // and redraw what is on the page, so no reload is needed.
    for (const name of Object.getOwnPropertyNames(VegvarselCard.prototype)) {
      if (name === "constructor") continue;
      Object.defineProperty(existing.prototype, name, Object.getOwnPropertyDescriptor(VegvarselCard.prototype, name));
    }
    const editor = customElements.get(EDITOR_TAG);
    if (editor) {
      for (const name of Object.getOwnPropertyNames(VegvarselCardEditor.prototype)) {
        if (name === "constructor") continue;
        Object.defineProperty(editor.prototype, name, Object.getOwnPropertyDescriptor(VegvarselCardEditor.prototype, name));
      }
    }
    (window.__vegvarselInstances || new Set()).forEach((card) => {
      try { card._refresh(); } catch (err) { /* stale */ }
    });
  } else {
    customElements.define(TAG, VegvarselCard);
    customElements.define(EDITOR_TAG, VegvarselCardEditor);
  }

  const ha = document.querySelector("home-assistant");
  const h = ha && ha.hass;
  const picker = {
    type: TAG,
    name: t(h, "name"),
    description: t(h, "description"),
    preview: false,
    documentationURL: "https://github.com/maxakassiouk/vegvarsel",
  };
  window.customCards = window.customCards || [];
  if (!window.customCards.some((c) => c.type === TAG)) window.customCards.push(picker);
})();
