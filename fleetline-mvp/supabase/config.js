// Axiom Fleet Supabase browser configuration.
// Set enabled: true to route requests through Supabase cloud (requires MFA/TOTP AAL2 & Edge function CORS).
// Default enabled: false routes to the sovereign local Python backend on 127.0.0.1.
window.AXIOM_SUPABASE_CONFIG = Object.assign({
  enabled: false,
  url: 'https://girbtmzictppugunfpoe.supabase.co',
  anonKey: 'sb_publishable_pBBDTJ9P_QUBj2XvdWpBnA_ewhFUZZw'
}, window.AXIOM_SUPABASE_CONFIG || {});
