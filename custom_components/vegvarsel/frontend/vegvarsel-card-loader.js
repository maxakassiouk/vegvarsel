/**
 * Loads the Vegvarsel card, and keeps trying until it has.
 *
 * Home Assistant makes one bare import() of an extra module per page, and
 * never another: a single fetch that fails (a restart in that moment, a phone
 * losing the network) would leave the card missing until a reload. This
 * file is what Home Assistant imports; it is tiny, and it fetches the card
 * itself, as often as it takes - each attempt under its own URL, because a
 * failed dynamic import is remembered per URL.
 *
 * It also stays in the page: after every reconnect it asks which card
 * version is served now, and imports the newer file when it changed, so an
 * update shows up without a reload. After the TomTom integration's loader.
 */
(() => {
  const RUNNING = "__vegvarsel-card-loader";
  if (window[RUNNING]) return;
  window[RUNNING] = true;

  const HERE = new URL(import.meta.url);
  const CARD = "vegvarsel-card.js";
  const DELAYS = [1, 2, 5, 10, 30]; // seconds; the last repeats
  let version = HERE.searchParams.get("v") || "0";
  let attempt = 0;

  function cardUrl(v, retry) {
    const url = new URL(CARD, HERE);
    url.searchParams.set("v", v);
    if (retry) url.searchParams.set("retry", String(retry));
    return url.href;
  }

  function load() {
    import(cardUrl(version, attempt)).then(
      () => {
        attempt = 0;
      },
      (err) => {
        const wait = DELAYS[Math.min(attempt, DELAYS.length - 1)];
        attempt += 1;
        console.warn(`Vegvarsel card did not load (${err && err.message}); trying again in ${wait} s`);
        setTimeout(load, wait * 1000);
      },
    );
  }
  load();

  // After a reconnect (Home Assistant restarted, maybe updated): load the
  // newer card if the version changed.
  function hass() {
    const root = document.querySelector("home-assistant");
    return root && root.hass;
  }
  let watched = null;
  async function check() {
    const h = hass();
    if (!h || !h.connection) return;
    try {
      const result = await h.connection.sendMessagePromise({ type: "vegvarsel/card_version" });
      const now = String(result && result.version);
      if (now && now !== "0" && now !== version) {
        version = now;
        attempt = 0;
        load();
      }
    } catch (_err) {
      /* the integration may not be loaded yet; the next reconnect asks again */
    }
  }
  function watch() {
    const h = hass();
    if (h && h.connection && h.connection !== watched) {
      watched = h.connection;
      watched.addEventListener("ready", check);
    }
  }
  setInterval(watch, 5000);
  watch();
})();
