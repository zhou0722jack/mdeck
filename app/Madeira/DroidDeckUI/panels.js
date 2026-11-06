'use strict';
window.DD_PANELS=(key,api)=>{
  const {t,esc,icon,button,setting,state}=api;
  const group=(title,rows)=>`<div class="eyebrow">${esc(t(title))}</div><div class="panel">${rows}</div>`;
  const result=(title,body,footer=button('common_done','close'))=>({title,body,footer,wide:true});
  if(key==='runtime')return result('setup_runtime',group('setup_runtime',setting({kind:'text',key:'Version',value:'DroidDeck 0.6.9'})+setting({kind:'text',key:'storage_used_of',value:'3.0 GB'}))+`<div class="actions">${button('common_update','download-component','Linux runtime','primary','download')}${button('common_uninstall','confirm-runtime-remove','','danger')}${button('comp_title','route','components')}</div>`);
  if(key==='onboarding'){
    const step=state.guideStep||0;
    const pages=[['DroidDeck','Steam · Linux · PC games','sports_esports'],['setup_runtime','setup_runtime_missing','deployed_code'],['setup_limit','setup_limit_on','shield'],['setup_ready','setup_sign_in','check_circle']];
    const [title,detail,glyph]=pages[step];
    return result(title,`<div class="welcome-logo">${icon(glyph)}</div><p class="lede" style="text-align:center">${esc(t(detail))}</p><div class="row" style="justify-content:center;padding:18px">${pages.map((_,i)=>`<span class="stage-dot${i===step?' active':''}"></span>`).join('')}</div>`,button('common_close','close')+button(step===3?'common_done':'common_next','guide-next','','primary'));
  }
  if(key==='storage-overview'){
    const buckets=[['games','storage_games','86.4 GB',40,'#4b9cf5'],['data','storage_game_data','8.6 GB',8,'#8f7cf6'],['tools','storage_tools','12.2 GB',10,'#3fc1c9'],['components','storage_components','3.2 GB',5,'#9bd65b'],['stores','storage_stores','5.1 GB',5,'#f0b44c'],['desktop','storage_desktop','2.4 GB',4,'#e57fb1'],['system','storage_system','4.0 GB',6,'#7d8796'],['app','storage_app_data','1.4 GB',2,'#6fd08c']];
    return result('storage_internal',`<div class="storage-head"><h2>${esc(t('storage_used_of','123.3 GB','256 GB'))}</h2><span class="muted">${esc(t('storage_free','132.7 GB'))}</span></div><div class="storage-bar">${buckets.map(b=>`<span style="width:${b[3]}%;background:${b[4]}"></span>`).join('')}</div><div class="row wrap">${buckets.map(b=>`<span class="storage-key"><i style="background:${b[4]}"></i>${esc(t(b[1]))}</span>`).join('')}</div><div class="actions">${button('storage_clean_up','route','storage-cleanup','primary','cleaning_services')}</div>`+group('storage_where',buckets.map(b=>`<button class="setting-row clickable" data-act="route" data-value="storage-${b[0]}"><div class="row"><span class="storage-dot" style="background:${b[4]}"></span><span>${esc(t(b[1]))}</span></div><span class="setting-value">${b[2]}${icon('chevron_right')}</span></button>`).join('')));
  }
  if(key==='storage-cleanup')return result('storage_clean_up_title',`<p class="lede">${esc(t('storage_clean_up_lede'))}</p>`+group('storage_safe_now',[
    ['storage_item_runtimes','2.4 GB'],['storage_item_leftovers','860 MB'],['storage_item_components','320 MB'],['storage_item_logs','148 MB'],['storage_item_shaders','640 MB']
  ].map(([label,size])=>setting({kind:'toggle',key:label,on:label!=='storage_item_shaders',detail:null})+`<div class="cleanup-size">${size}</div>`).join('')),button('common_cancel','close')+button(t('storage_free_button','3.7 GB'),'clean-preview','','primary'));
  if(key.startsWith('storage-')){
    const type=key.slice(8),titles={games:'storage_games',data:'storage_game_data',tools:'storage_tools',components:'storage_components',stores:'storage_stores',desktop:'storage_desktop',system:'storage_system',app:'storage_app_data'};
    const rows=type==='games'?state.games.filter(g=>g.installed).map(g=>`<button class="setting-row clickable" data-act="game" data-value="${g.id}"><span>${esc(g.name)}</span><span class="setting-value">${g.size}${icon('chevron_right')}</span></button>`).join(''):
      (type==='tools'?['Proton Experimental','DroidDeck Proton 11','Steam Linux Runtime']:type==='components'?['FEX','DXVK','VKD3D-Proton']:type==='desktop'?['KDE Plasma','Firefox','Konsole']:type==='app'?['Cache','Logs','Covers']:['Steam','Shader cache','Workshop']).map(name=>setting({kind:'text',key:name,value:'—'})).join('');
    return result(titles[type]||'storage_internal',group(titles[type],rows)+`<div class="actions">${button('storage_back','route','storage-overview')}${button('storage_clean_up','route','storage-cleanup')}</div>`);
  }
  if(key==='install-options'){
    const game=state.selected||state.games[0];
    return result(t('stores_install_title',game.name),group('game_install_location',setting({kind:'choice',key:'game_install_location',options:['stores_target_internal','storage_default_external','mode_choose_folder']}))+group('game_tab_install',setting({kind:'text',key:'game_install_size',value:game.size})+setting({kind:'text',key:'game_install_access',value:'game_install_access_owned'})),button('common_cancel','close')+button('store_install','install-game',game.id,'primary','download'));
  }
  if(key==='notifications')return result('Notifications',state.notifications.length?group('Notifications',state.notifications.slice().reverse().map(text=>`<div class="setting-row">${icon('notifications')}<span>${esc(text)}</span></div>`).join('')):`<div class="empty-state">${icon('notifications_none')}<p>${esc(t('no_notifications'))}</p></div>`);
  if(key==='chat')return result('Chat',`<div class="chat-layout"><div class="chat-list">${['Player One','Player Two','Steam Group'].map((name,i)=>`<button class="choice${i===0?' selected':''}" data-act="chat-person" data-value="${name}"><span class="avatar">${name[0]}</span>${name}<span class="status-light"></span></button>`).join('')}</div><div class="chat-thread"><h3 id="chat-name">Player One</h3><div id="chat-messages"><div class="chat-bubble">${esc(t('chat_hello'))}</div></div><div class="chat-compose"><input class="search-field" id="chat-message" placeholder="${esc(t('chat_message'))}" maxlength="500">${button('Send','chat-send','','primary','send')}</div></div></div>`);
  if(key==='screenshots')return result('Screenshots',`<div class="capture-grid">${state.games.slice(0,6).map(g=>`<button data-act="capture-open" data-value="${g.id}"><img src="assets/game-${g.id}.jpg" alt="${esc(g.name)}"><span>${esc(g.name)}</span></button>`).join('')}</div>`);
  if(key==='telemetry')return result('Performance',`<div class="telemetry-cards">${[['FPS','60'],['Frame time','16.7 ms'],['CPU','18%'],['GPU','32%'],['RAM','2.4 GB'],['Battery','85%']].map(([label,value])=>`<div class="panel"><span class="muted">${label}</span><h2>${value}</h2><svg viewBox="0 0 240 50"><path d="M0 42L15 36L28 39L43 18L58 26L75 20L90 33L106 22L122 25L140 12L155 20L169 18L185 26L203 14L225 21L240 13" fill="none" stroke="var(--primary)" stroke-width="2"/></svg></div>`).join('')}</div>`);
  return null;
};
