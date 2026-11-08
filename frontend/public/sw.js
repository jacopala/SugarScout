// SugarScout service worker: shows push alerts about the child on the parent's device.
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))

self.addEventListener('push', (event) => {
  let data = { title: 'SugarScout', body: 'Open the dashboard for details.', tag: 'sugarscout', urgent: false, url: '/parent' }
  try {
    data = { ...data, ...event.data.json() }
  } catch {
    /* plain-text push: keep the defaults */
  }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      tag: data.tag,
      renotify: true,
      requireInteraction: Boolean(data.urgent),
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      data: { url: data.url },
    }),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = (event.notification.data && event.notification.data.url) || '/parent'
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((wins) => {
      const open = wins.find((w) => new URL(w.url).pathname.startsWith(url))
      return open ? open.focus() : self.clients.openWindow(url)
    }),
  )
})
