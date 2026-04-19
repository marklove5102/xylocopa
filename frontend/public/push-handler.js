/* Xylocopa Service Worker — Web Push notifications */

function sendAck(nid, shown) {
  if (!nid) return Promise.resolve();
  const endpointPromise = self.registration.pushManager
    .getSubscription()
    .then((sub) => (sub && sub.endpoint) || "", () => "");
  return endpointPromise.then((endpoint) =>
    fetch("/api/push/ack", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        nid,
        shown,
        ts: Date.now(),
        ua: (self.navigator && self.navigator.userAgent) || "",
        endpoint,
      }),
      keepalive: true,
    }).catch(() => {}),
  );
}

self.addEventListener("push", (event) => {
  let data = { title: "Xylocopa", body: "An agent finished.", url: "/" };
  try {
    data = Object.assign(data, event.data.json());
  } catch {
    // use defaults
  }

  // Admin reset: clear all caches + unregister this SW. Sent by
  // tools/push_reset.py to recover devices stuck on a stale SW.
  // iOS Web Push requires a visible notification per push, so we show
  // a brief "reset done" toast — user manually closes & reopens the PWA
  // afterwards for a clean fetch (no SW left to intercept).
  if (data.type === "reset") {
    const shownPromise = self.registration
      .showNotification("Xylocopa", {
        body: "Reset done — please re-open the app",
        icon: "/icon-192.png",
        badge: "/icon-192.png",
        data: { nid: data.nid },
      })
      .then(() => true, () => false);

    event.waitUntil(
      shownPromise.then(async (shown) => {
        try {
          const names = await caches.keys();
          await Promise.all(names.map((n) => caches.delete(n)));
        } catch { /* best-effort */ }
        try {
          await self.registration.unregister();
        } catch { /* best-effort */ }
        return sendAck(data.nid, shown);
      }),
    );
    return;
  }

  const shownPromise = self.registration
    .showNotification(data.title, {
      body: data.body,
      icon: "/icon-192.png",
      badge: "/icon-192.png",
      vibrate: [100, 50, 100],
      data: { url: data.url, nid: data.nid },
    })
    .then(() => true, () => false);

  event.waitUntil(
    shownPromise.then((ok) => sendAck(data.nid, ok)),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  const url = event.notification.data?.url || "/";

  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((windowClients) => {
      // Focus existing tab if one is open
      for (const client of windowClients) {
        if (client.url.includes(self.location.origin)) {
          client.focus();
          // Let the app decide how to navigate (split-screen aware)
          client.postMessage({ type: "notification-navigate", url });
          return;
        }
      }
      // Otherwise open a new tab
      return clients.openWindow(url);
    }),
  );
});
