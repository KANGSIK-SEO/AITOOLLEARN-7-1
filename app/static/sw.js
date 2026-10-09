// 앱 쉘은 미리 캐싱하고, 문서는 네트워크 우선으로 최신 상태를 유지한다.
// /api/*와 외부 요청은 로그인·대화 같은 동적 데이터이므로 서비스워커가 가로채지 않는다.
// __ASSET_VERSION__과 정적 파일 주소의 ?v=는 서버(app/main.py)가 화면 파일 내용으로 채운다 —
// 배포로 파일이 바뀌면 캐시 이름이 바뀌어 activate 단계에서 옛 캐시가 지워진다 (수동으로 v3→v4 올릴 필요 없음).
const CACHE = 'art-chatbot-shell-__ASSET_VERSION__';
const OFFLINE_URL = '/static/offline.html';
const SHELL = [
  '/',
  OFFLINE_URL,
  '/static/style.css',
  '/static/app.js',
  '/static/ondevice.js',
  '/static/boot.js',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];
// artworks.json(~2MB)은 모든 방문자에게 미리 깔지 않고, 온디바이스 패널을 실제로 열 때만
// 받는다 — 받고 나면 아래 fetch 핸들러가 평소대로 캐시에 올려둔다.

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(SHELL))
  );
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
  const url = new URL(request.url);
  if (
    request.method !== 'GET' ||
    url.origin !== self.location.origin ||
    url.pathname.startsWith('/api/')
  ) {
    return;
  }

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
          return response;
        })
        .catch(() => caches.match(request).then((cached) => cached || caches.match(OFFLINE_URL)))
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((cached) =>
      cached || fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      })
    )
  );
});
