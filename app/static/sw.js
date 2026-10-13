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
  '/static/theme-init.js',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];
// artworks.json(~2MB)은 모든 방문자에게 미리 깔지 않고, 온디바이스 패널을 실제로 열 때만
// 받는다 — 받고 나면 아래 fetch 핸들러가 평소대로 캐시에 올려둔다.
// 단, 이 파일은 캐시 이름(ASSET_VERSION) 계산에 들어가지 않아 작품 DB를 다시 수집해도 캐시 이름이 안 바뀐다 →
// 캐시 우선으로 두면 설치된 브라우저가 영영 옛 데이터로 추천한다. 그래서 네트워크 우선으로 받는다:
// 서버에서 받을 수 있으면 새 내용으로 캐시를 갱신하고, 오프라인이면 캐시본을 쓴다.
const NETWORK_FIRST = new Set(['/static/artworks.json']);

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

  // 네트워크 우선 항목은 캐시를 먼저 보지 않는다 — 아래 요청이 성공하면 캐시를 갱신하고, 실패하면 캐시본으로 되돌아간다
  const lookup = NETWORK_FIRST.has(url.pathname) ? Promise.resolve(undefined) : caches.match(request);
  event.respondWith(
    lookup.then((cached) =>
      cached || fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      }).catch((err) => caches.match(request).then((fallback) => {
        if (fallback) return fallback;   // 오프라인: 예전에 받아 둔 작품 데이터로라도 동작한다
        throw err;
      }))
    )
  );
});
