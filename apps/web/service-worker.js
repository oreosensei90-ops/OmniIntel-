"use strict";
const CACHE = "omniintel-reader-shell-v8";
const SHELL = ["./", "./index.html", "./styles.css", "./app.js", "./manifest.webmanifest"];
self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  const shellPaths = SHELL.map((path) => new URL(path, self.registration.scope).pathname);
  if (request.method !== "GET" || url.origin !== self.location.origin || !shellPaths.includes(url.pathname)) return;
  // Network-first: a new deployment is picked up immediately; the cache is only the offline fallback.
  event.respondWith(fetch(request).then((response) => {
    if (response.ok) {
      const copy = response.clone();
      caches.open(CACHE).then((cache) => cache.put(request, copy));
    }
    return response;
  }).catch(() => caches.match(request)));
});
