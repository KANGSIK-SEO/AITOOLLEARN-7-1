// 앱 쉘(정적 자원)만 캐싱한다. /api/*는 로그인·대화 같은 동적 데이터라 항상 네트워크로 보낸다.
const CACHE = 'art-chatbot-shell-v2';
const SHELL = [
  '/',
  '/static/style.css',
  '/static/app.js',
  '/static/ondevice.js',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];
// artworks.json(~2MB)은 모든 방문자에게 미리 깔지 않고, 온디바이스 패널을 실제로 열 때만
// 받는다 — 받고 나면 아래 fetch 핸들러가 평소대로 캐시에 올려둔다.

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET' || new URL(request.url).pathname.startsWith('/api/')) {
    return; // API 요청은 서비스워커가 손대지 않고 그대로 네트워크로
  }
  event.respondWith(
    caches.match(request).then((cached) => {
      const network = fetch(request)
        .then((res) => {
          if (res.ok) caches.open(CACHE).then((cache) => cache.put(request, res.clone()));
          return res;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
