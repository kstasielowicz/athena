from pathlib import Path
root=Path('/mnt/data/athena_ui_final')
css=root/'static/style.css'
append=r'''

/* ATHENA v11.4 final UI consistency hotfix
   - unified skill tree cards
   - stable sidebar scroll memory target
   - cleaner athlete profile hero
   - no broken words in exercise tags
   - dashboard readability pass
*/
:root{--athena-green:#39ff88;--athena-green-soft:rgba(57,255,136,.12);--athena-border:rgba(57,255,136,.16);--athena-card:#07100b;--athena-card-2:#0b1711}

/* Sidebar: keep internal nav scrollable and restorable */
.sidebar{height:100vh!important;overflow:hidden!important;min-height:0!important;}
.side-nav{flex:1 1 auto!important;min-height:0!important;overflow-y:auto!important;overflow-x:hidden!important;padding-right:6px!important;scrollbar-width:thin;scrollbar-color:rgba(57,255,136,.32) transparent;}
.side-nav::-webkit-scrollbar{width:7px!important}.side-nav::-webkit-scrollbar-thumb{background:linear-gradient(180deg,rgba(57,255,136,.42),rgba(57,255,136,.16));border-radius:999px}.side-nav::-webkit-scrollbar-track{background:transparent}
.side-card{flex:0 0 auto!important;margin-top:0!important;}

/* Global text safety: allow paragraphs to wrap, but never split tiny labels/tags letter-by-letter */
.pill,.tone-pill,.btn,.primary,.nav-link,.widget-check em,.widget-check span,.exercise-title-row .pill,.tag-row .pill{white-space:nowrap!important;overflow-wrap:normal!important;word-break:normal!important;hyphens:none!important;line-height:1.15!important;}
.tag-row{gap:8px!important;align-items:center!important;min-width:0!important;}
.exercise-card-v11 .tag-row{display:flex!important;flex-wrap:wrap!important;align-content:flex-start!important;}
.exercise-card-v11 .pill{font-size:11px!important;padding:6px 9px!important;max-width:100%!important;}
.exercise-title-row{display:grid!important;grid-template-columns:minmax(0,1fr) auto!important;align-items:start!important;gap:10px!important;}
.exercise-title-row h3{line-height:1.18!important;margin:0!important;overflow-wrap:break-word!important;word-break:normal!important;}
.exercise-card-body{min-height:210px!important;gap:14px!important;}
.exercise-card-body p{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;min-height:4.2em;}
.exercise-placeholder{background:#092014!important;background-image:none!important;border-bottom:1px solid rgba(57,255,136,.13)!important;min-height:176px!important;}
.exercise-placeholder.large{min-height:280px!important;border-radius:22px!important;border:1px solid rgba(57,255,136,.18)!important;}

/* Athlete Profile 3.0 cleanup */
.athlete-v11-hero{display:grid!important;grid-template-columns:minmax(0,1fr) minmax(340px,520px)!important;gap:26px!important;align-items:center!important;padding:28px 30px!important;overflow:hidden!important;}
.athlete-identity-block{display:grid!important;grid-template-columns:88px minmax(0,1fr)!important;gap:20px!important;align-items:center!important;min-width:0!important;}
.athlete-avatar-large{width:88px!important;height:88px!important;border-radius:28px!important;display:grid!important;place-items:center!important;overflow:hidden!important;background:linear-gradient(135deg,rgba(57,255,136,.20),rgba(7,16,11,.88))!important;border:1px solid rgba(57,255,136,.24)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.05),0 18px 50px rgba(0,0,0,.24)!important;}
.athlete-avatar-large span{display:grid!important;place-items:center!important;width:100%!important;height:100%!important;font-size:34px!important;font-weight:900!important;color:#baffd0!important;line-height:1!important;position:static!important;transform:none!important;margin:0!important;}
.athlete-avatar-large img{display:block!important;width:100%!important;height:100%!important;object-fit:cover!important;border-radius:inherit!important;}
.athlete-identity-block h2{font-size:clamp(26px,3vw,42px)!important;margin:4px 0 8px!important;line-height:1.05!important;letter-spacing:-.04em!important;}
.athlete-identity-block .muted{font-size:15px!important;line-height:1.45!important;overflow-wrap:normal!important;word-break:normal!important;}
.athlete-hero-stats{display:grid!important;grid-template-columns:repeat(3,minmax(120px,1fr))!important;gap:12px!important;align-items:stretch!important;}
.athlete-hero-stats span{display:flex!important;flex-direction:column!important;justify-content:center!important;gap:5px!important;min-height:76px!important;padding:14px 16px!important;border-radius:18px!important;background:rgba(255,255,255,.045)!important;border:1px solid rgba(255,255,255,.09)!important;}
.athlete-hero-stats b{font-size:clamp(26px,2.6vw,40px)!important;line-height:1!important;letter-spacing:-.04em!important;white-space:nowrap!important;}
.athlete-hero-stats small{font-size:12px!important;color:var(--muted)!important;text-transform:uppercase!important;letter-spacing:.08em!important;white-space:nowrap!important;}
.profile-metric-grid span{display:flex!important;flex-direction:column!important;gap:4px!important;}

/* Skills: uniform tree cards and contained edit/evidence controls */
.clean-skill-layout{display:grid!important;grid-template-columns:minmax(280px,360px) minmax(0,1fr)!important;gap:22px!important;align-items:start!important;}
.clean-skill-list{display:grid!important;grid-template-columns:repeat(auto-fit,minmax(420px,1fr))!important;gap:18px!important;align-items:stretch!important;}
.skill-tree-card{display:flex!important;flex-direction:column!important;gap:14px!important;min-height:520px!important;height:100%!important;padding:20px!important;border-radius:24px!important;overflow:hidden!important;}
.skill-card-head{display:grid!important;grid-template-columns:minmax(0,1fr) 88px!important;gap:14px!important;align-items:start!important;min-height:94px!important;}
.skill-card-head h3{font-size:24px!important;line-height:1.08!important;margin:8px 0!important;}
.skill-card-head p{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;line-height:1.45!important;min-height:2.9em!important;}
.skill-score{display:flex!important;flex-direction:column!important;align-items:flex-end!important;justify-content:flex-start!important;gap:2px!important;min-width:80px!important;}
.skill-score b{font-size:26px!important;line-height:1!important;white-space:nowrap!important;}
.skill-tree{flex:1 1 auto!important;display:grid!important;gap:12px!important;align-content:start!important;margin:8px 0 10px!important;}
.skill-node{display:grid!important;grid-template-columns:44px minmax(0,1fr)!important;gap:12px!important;align-items:start!important;min-width:0!important;}
.node-dot{width:40px!important;height:40px!important;border-radius:14px!important;}
.node-card{display:flex!important;flex-direction:column!important;gap:10px!important;min-height:190px!important;padding:14px!important;border-radius:18px!important;overflow:hidden!important;}
.node-card .section-head{display:grid!important;grid-template-columns:minmax(0,1fr) auto!important;gap:10px!important;align-items:start!important;min-height:54px!important;}
.node-card .section-head b{display:block!important;line-height:1.2!important;overflow-wrap:break-word!important;word-break:normal!important;}
.node-card .section-head small{display:-webkit-box!important;-webkit-line-clamp:2!important;-webkit-box-orient:vertical!important;overflow:hidden!important;line-height:1.35!important;}
.node-card .section-head em{font-style:normal!important;font-size:11px!important;padding:5px 8px!important;border-radius:999px!important;background:rgba(255,255,255,.06)!important;color:var(--muted)!important;white-space:nowrap!important;}
.step-actions{display:flex!important;gap:8px!important;flex-wrap:wrap!important;margin-top:auto!important;}
.step-actions form{display:inline-flex!important;margin:0!important;}
.evidence-form{display:grid!important;grid-template-columns:minmax(0,1fr)!important;gap:8px!important;margin-top:0!important;}
.evidence-form .btn,.evidence-form button,.evidence-upload{width:100%!important;min-width:0!important;}
.skill-step-toolbar{display:flex!important;gap:10px!important;flex-wrap:wrap!important;margin-top:auto!important;padding-top:12px!important;border-top:1px solid rgba(57,255,136,.10)!important;}
.skill-step-toolbar .btn{flex:1 1 140px!important;}
.skill-modal-panel,.modal-panel{max-width:calc(100vw - 32px)!important;}
.skill-edit-modal-form .form-grid.two{grid-template-columns:repeat(2,minmax(0,1fr))!important;}
.skill-edit-modal-form input,.skill-edit-modal-form textarea{max-width:100%!important;}
.evidence-thumb{max-height:120px!important;object-fit:cover!important;border-radius:14px!important;border:1px solid rgba(57,255,136,.14)!important;}

/* Dashboard readability and stability */
.v11-command-shell,.v11-dashboard-grid,.v11-pinned-grid,.v11-lower-grid{max-width:1500px!important;}
.v11-hero-card{grid-template-columns:minmax(0,1fr) minmax(240px,300px)!important;padding:26px!important;border-radius:28px!important;}
.v11-hero-copy h2{font-size:clamp(30px,3.4vw,48px)!important;line-height:1.05!important;}
.score-breakdown-card{grid-template-columns:repeat(auto-fit,minmax(170px,1fr))!important;}
.v11-dashboard-grid{display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr))!important;gap:18px!important;align-items:stretch!important;}
.v11-dashboard-grid .card{min-height:0!important;}
.v11-smart-plan,.v11-mission-card,.v11-alerts-card{min-height:220px!important;display:flex!important;flex-direction:column!important;}
.v11-mission-card .mission-list,.v11-alert-list{flex:1!important;}
.v11-pinned-grid{display:grid!important;grid-template-columns:repeat(auto-fill,minmax(190px,1fr))!important;gap:14px!important;align-items:stretch!important;}
.pinned-card{display:flex!important;flex-direction:column!important;gap:6px!important;min-height:124px!important;overflow:hidden!important;}
.pinned-card small,.pinned-card span{overflow:hidden!important;text-overflow:ellipsis!important;white-space:nowrap!important;}
.v11-lower-grid{display:grid!important;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr) minmax(280px,.85fr)!important;gap:18px!important;align-items:start!important;}
.weekly-numbers.stable{grid-template-columns:repeat(auto-fit,minmax(110px,1fr))!important;}
.info-tip-grid.v11-tips{display:grid!important;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))!important;gap:10px!important;}
.info-tip{min-height:74px!important;}
.mini-achievement{grid-template-columns:38px minmax(0,1fr)!important;}
.mini-achievement b,.mini-achievement small{overflow:hidden!important;text-overflow:ellipsis!important;display:block!important;}
.mini-achievement small{display:-webkit-box!important;-webkit-line-clamp:2!important;-webkit-box-orient:vertical!important;white-space:normal!important;}

/* Tables and old program/progression blocks: prevent awkward one-letter wrapping */
th,td{word-break:normal!important;overflow-wrap:normal!important;}
td a,th,td b{white-space:normal!important;word-break:normal!important;overflow-wrap:break-word!important;}

@media(max-width:1280px){
  .athlete-v11-hero{grid-template-columns:1fr!important;}
  .athlete-hero-stats{grid-template-columns:repeat(3,minmax(0,1fr))!important;}
  .clean-skill-list{grid-template-columns:1fr!important;}
  .v11-dashboard-grid,.v11-lower-grid{grid-template-columns:1fr!important;}
}
@media(max-width:900px){
  .sidebar{height:auto!important;overflow:visible!important;}
  .side-nav{max-height:none!important;overflow:visible!important;}
  .athlete-identity-block{grid-template-columns:72px minmax(0,1fr)!important;gap:14px!important;}
  .athlete-avatar-large{width:72px!important;height:72px!important;border-radius:22px!important;}
  .athlete-avatar-large span{font-size:28px!important;}
  .athlete-hero-stats{grid-template-columns:1fr!important;}
  .clean-skill-layout{grid-template-columns:1fr!important;}
  .clean-skill-list{grid-template-columns:1fr!important;}
  .skill-tree-card{min-height:0!important;}
  .skill-card-head{grid-template-columns:1fr!important;min-height:0!important;}
  .skill-score{align-items:flex-start!important;text-align:left!important;}
  .node-card{min-height:0!important;}
  .skill-edit-modal-form .form-grid.two{grid-template-columns:1fr!important;}
  .v11-hero-card{grid-template-columns:1fr!important;}
}
@media(max-width:560px){
  .exercise-card-v11 .pill{font-size:10.5px!important;padding:5px 8px!important;}
  .skill-node{grid-template-columns:34px minmax(0,1fr)!important;gap:9px!important;}
  .node-dot{width:32px!important;height:32px!important;border-radius:11px!important;font-size:12px!important;}
  .athlete-identity-block{grid-template-columns:1fr!important;}
}
'''
css.write_text(css.read_text()+append)

# Patch athlete template for safer XP display and fallback name
ath=root/'templates/athlete.html'
s=ath.read_text()
s=s.replace('{{profile.name}}','{{profile.name or "ATHENA Athlete"}}')
s=s.replace('{{level.xp}}</b><small>XP</small>','{{level.xp or 0}}</b><small>XP</small>')
ath.write_text(s)

# Patch base scroll script to target .side-nav as primary and persist before navigation/pageshow
base=root/'templates/base.html'
s=base.read_text()
old="""// Preserve left sidebar scroll between page loads so navigation does not jump to the top.
(function(){
  const sb=document.querySelector('.sidebar');
  if(!sb) return;
  const key='athena_sidebar_scroll_v1';
  const saved=sessionStorage.getItem(key);
  if(saved!==null){requestAnimationFrame(()=>{sb.scrollTop=parseInt(saved||'0',10)||0;});}
  sb.addEventListener('scroll',()=>sessionStorage.setItem(key,String(sb.scrollTop)),{passive:true});
  document.querySelectorAll('a.nav-link').forEach(a=>a.addEventListener('click',()=>sessionStorage.setItem(key,String(sb.scrollTop))));
})();"""
new="""// Preserve left sidebar navigation scroll between page loads so navigation does not jump to the top.
(function(){
  const sb=document.querySelector('.side-nav') || document.querySelector('.sidebar');
  if(!sb) return;
  const key='athena_side_nav_scroll_v2';
  function save(){try{sessionStorage.setItem(key,String(sb.scrollTop||0));}catch(e){}}
  function restore(){
    try{
      const saved=sessionStorage.getItem(key);
      if(saved!==null){sb.scrollTop=parseInt(saved||'0',10)||0;}
    }catch(e){}
  }
  requestAnimationFrame(restore);
  window.addEventListener('pageshow',()=>requestAnimationFrame(restore));
  sb.addEventListener('scroll',save,{passive:true});
  document.querySelectorAll('a.nav-link').forEach(a=>a.addEventListener('mousedown',save));
  document.querySelectorAll('a.nav-link').forEach(a=>a.addEventListener('click',save));
  window.addEventListener('beforeunload',save);
})();"""
if old in s:
    s=s.replace(old,new)
else:
    s=s.replace('</script>\n\n<script>','</script>\n<script>'+new+'</script>\n\n<script>',1)
base.write_text(s)

# Add update note
(root/'ATHENA_V11_4_FINAL_UI_HOTFIX_NOTES.md').write_text('''# ATHENA v11.4 Final UI Hotfix\n\nFixed:\n- Skill tree cards now use consistent sizing and contained action rows.\n- Skill edit/evidence controls no longer overflow cards.\n- Sidebar navigation scroll is persisted on the actual scroll container.\n- Athlete Profile hero/avatar/XP layout cleaned up.\n- Exercise card tags no longer split words like Intermediate into multiple lines.\n- Dashboard layout simplified and stabilized with more readable card grids.\n- General responsive CSS pass for desktop/tablet/mobile.\n''')
