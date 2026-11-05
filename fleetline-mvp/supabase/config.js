// Axiom Fleet Supabase browser configuration.
// By default, Supabase cloud is enabled for both local dev and production.
// To switch to sovereign local Python backend, append ?local=true to URL or set localStorage.setItem('axiom_force_local', 'true').
const forceLocal = typeof window !== 'undefined' && (
  window.location.search.includes('local=true') ||
  localStorage.getItem('axiom_force_local') === 'true'
);

window.AXIOM_SUPABASE_CONFIG = Object.assign({
  enabled: !forceLocal,
  url: 'https://girbtmzictppugunfpoe.supabase.co',
  anonKey: 'sb_publishable_pBBDTJ9P_QUBj2XvdWpBnA_ewhFUZZw'
}, window.AXIOM_SUPABASE_CONFIG || {});
