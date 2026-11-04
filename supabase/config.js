// Axiom Fleet Supabase browser configuration.
// Set enabled: true to route requests through Supabase cloud (requires MFA/TOTP AAL2 & Edge function CORS).
// When on localhost/127.0.0.1, defaults to the sovereign local Python backend.
// When hosted remotely (e.g. on Vercel), automatically routes to Supabase cloud.
const isLocalHost = typeof window !== 'undefined' && (
  window.location.hostname === 'localhost' ||
  window.location.hostname === '127.0.0.1' ||
  window.location.hostname === '0.0.0.0' ||
  window.location.hostname === ''
);

window.AXIOM_SUPABASE_CONFIG = Object.assign({
  enabled: !isLocalHost,
  url: 'https://girbtmzictppugunfpoe.supabase.co',
  anonKey: 'sb_publishable_pBBDTJ9P_QUBj2XvdWpBnA_ewhFUZZw'
}, window.AXIOM_SUPABASE_CONFIG || {});

