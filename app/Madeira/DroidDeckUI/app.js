/* DroidDeck 0.6.9 UI port. GPL-3.0. All actions terminate in local presentation state. */
'use strict';
window.DD = (() => {
  const P=DD_PAGES,C=DD_CATALOG,M=DDMotion,root=document.documentElement;
  const defaults={language:'zh',theme:'graphite',animations:true,labels:true,scale:100,stores:true,showTitles:true,showSizes:true,cardSize:148,layout:'capsule',filter:'all',sort:'recent',showUninstalled:true};
  let prefs={...defaults};try{prefs={...defaults,...JSON.parse(localStorage.getItem('droiddeck.ui.v1')||'{}')};}catch{}
  const state={page:'steam',setupTab:'overview',store:'gog',storeTab:'discover',search:'',layers:[],values:{},games:P.games.map((g,i)=>({...g,lastPlayed:i,added:i,favorite:i<3})),downloads:[],signedIn:{},session:null,detailTab:'about',detailOrigin:'games',selected:null,selectedCollection:'all',notifications:[],inputMode:'touch'};
  try{const saved=JSON.parse(localStorage.getItem('droiddeck.ui.options.v1')||'{}');state.values=saved.values||{};state.environment=saved.environment||{};}catch{}
  function saveOptions(){try{localStorage.setItem('droiddeck.ui.options.v1',JSON.stringify({values:state.values,environment:state.environment||{}}));}catch{}}
  const aliases={common_auto:'自动',common_on:'开启',common_off:'关闭',common_reset:'重置',common_remove:'移除',common_save:'保存',gesture_title:'触摸手势',physical_shortcuts_title:'物理按键快捷方式',screen_keys_title:'屏幕按键',screen_layout_title:'屏幕布局',framegen_title:'帧生成',sync_title:'文件夹同步',sync_advanced:'高级同步设置',win_components_title:'Windows 组件',game_resources_title:'游戏资源',steam_import_title:'导入 Steam 游戏',Brightness:'亮度',Contrast:'对比度',Saturation:'饱和度',Sharpness:'锐度',Color:'颜色',Notifications:'通知',Chat:'聊天',Screenshots:'截图',Performance:'性能'};
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const keyAliases={common_confirm:'common_ok',common_done:'setup_check_done',common_next:'boot_movie_repo_next',common_loading:'store_loading',common_remove:'store_remove',common_save:'game_env_save',common_reset:'ctrl_reset',common_refresh:'stores_refresh',common_on:'game_no_steam_on',common_off:'perf_cap_off',common_about:'game_tab_about',library_all:'stores_tab_all',library_collections:'itch_collections',library_sort:'stores_sort',library_sort_name:'stores_sort_title_asc',library_sort_recent:'stores_sort_last_played',library_view:'stores_view_cards',library_view_grid:'stores_view_capsules',library_view_list:'stores_view_list',games_play:'games_play_steam',keyboard_title:'drawer_keyboard',drawer_menu:'drawer_quick_access',stores_pause:'stores_dl_paused',session_starting_steam:'session_starting_session',session_loading_client:'session_runtime_checking',desktop_starting:'session_starting_desktop',physical_shortcuts_title:'shortcuts_title',screen_keys_title:'screen_keys',framegen_title:'frame_gen_title',hud:'drawer_hud',touchOverlay:'mode_osc',Stop:'drawer_stop',Pause:'stores_dl_paused',Store:'rail_stores',cardSize:'library_display',showTitles:'library_display_title',showSizes:'library_display_size'};
  const extraText={downloads_empty:['暂无下载','No downloads'],updates_release_notes:['更新说明','Release notes'],no_notifications:['暂无通知','No notifications'],chat_hello:['准备好一起玩了吗？','Ready to play?'],chat_message:['消息','Message'],Send:['发送','Send'],Square:['方形卡片','Square cards'],Favorites:['收藏','Favorites'],'Recently played':['最近游玩','Recently played'],'RGB speed':['RGB 变色速度','RGB speed'],'Left click':['左键','Left click'],'Right click':['右键','Right click'],'Key':['按键','Key'],Unassigned:['未分配','Unassigned'],Version:['版本','Version'],Original:['原件','Original'],'Frame rate':['帧率','Frame rate'],Controllers:['控制器','Controllers']};
  function t(key,...args){const original=key;key=keyAliases[key]||key;if(key==='win_components_title')key='wincomp_title';let s=(C.strings[prefs.language]||C.strings.en)[key]??C.strings.en[key]??extraText[original]?.[prefs.language==='zh'?0:1]??(prefs.language==='zh'?aliases[original]:null)??original;let n=0;return s.replace(/%(?:(\d+)\$)?(?:\.[0-9]+)?[dsf]/g,(_,i)=>String(args[i?Number(i)-1:n++]??'—')).replace(/%%/g,'%');}
  const icon=name=>`<span class="icon" aria-hidden="true">${esc(name)}</span>`;
  const attr=(name,value)=>` data-${name}="${esc(value)}"`;
  function button(label,act='close',value='',style='secondary',glyph=''){return `<button class="button ${style}"${attr('act',act)}${attr('value',value)}>${glyph?icon(glyph):''}${esc(t(label))}</button>`;}
  function ib(label,glyph,act,value='',selected=false){return `<button class="icon-button${selected?' selected':''}" title="${esc(t(label))}" aria-label="${esc(t(label))}"${attr('act',act)}${attr('value',value)}>${icon(glyph)}</button>`;}
  const chips=(items,selected,act)=>`<div class="chips" role="tablist">${items.map(([id,label])=>`<button class="chip${id===selected?' active':''}" role="tab" aria-selected="${id===selected}"${attr('act',act)}${attr('value',id)}>${esc(t(label))}</button>`).join('')}</div>`;
  const title=(label,extras='',count='')=>`<header class="page-head"><h1>${esc(t(label))}</h1>${count?`<span class="count">${esc(count)}</span>`:''}${extras}</header>`;
  const storeInfo=id=>P.stores.find(s=>s[0]===id)||P.stores[0];
  const art=g=>`assets/game-${g.id}.jpg`;
  function wordmark(){const w=C.wordmark;return `<svg class="wordmark" viewBox="239.135 120.02 801.565 123.18" role="img" aria-label="DroidDeck"><path fill="currentColor" d="${w.letters}"/><g transform="translate(239.135 123.36) scale(.527445) translate(31.98 0)"><path fill="currentColor" d="${w.left}"/><path fill="currentColor" d="${w.right}"/><circle fill="var(--primary)" cx="63.98" cy="111.86" r="55.98"/></g></svg>`;}
  function save(){try{localStorage.setItem('droiddeck.ui.v1',JSON.stringify(prefs));saveOptions();}catch{}}
  const palettes={
    graphite:['#0a0b0d','#121417','#1a1d22','#262a31','#343a43','#f2f4f7','#9aa3af','#1a9fff','#1487db','#03111f'],
    paper:['#000000','#0f0f10','#191a1c','#262729','#343638','#f9f9f9','#8e9196','#f9f9f9','#d9dadd','#000000'],
    blue:['#050608','#0e1116','#161b23','#1f2630','#2a3340','#f2f4f7','#8a93a0','#136ce0','#0b4fb0','#ffffff'],
    electric:['#070a10','#0f1522','#16203a','#1e2a47','#2a3a5e','#eef3ff','#8b9ab8','#2e86ff','#2684ff','#03111f'],
    inner_gamer:['#090d0a','#101712','#18211b','#28332b','#344538','#f2f7f3','#9cafa1','#50ff1a','#1bdf31','#031f09'],
    gradient:['#0e0b16','#17121f','#211a2f','#30263f','#433657','#f6f2ff','#a69ab8','#8b5cf6','#22d3ee','#ffffff']
  };
  let hueTimer;
  function applyPrefs(){
    const keys=['bg','surface','variant','line','line2','ink','muted','primary','primary2','on-primary'];
    if(prefs.theme==='gradient')palettes.gradient=DDTheme.palette(prefs.primaryColor||'#8b5cf6',prefs.secondaryColor||'#22d3ee');
    (palettes[prefs.theme]||palettes.graphite).forEach((v,i)=>root.style.setProperty(`--${keys[i]}`,v));
    root.style.setProperty('--scale',prefs.scale/100);document.getElementById('pane').style.zoom=prefs.scale/100;document.body.classList.toggle('no-motion',!prefs.animations);
    document.body.classList.toggle('hide-titles',!prefs.showTitles);document.body.classList.toggle('hide-sizes',!prefs.showSizes);
    document.getElementById('rail').classList.toggle('labels-off',!prefs.labels);
    root.style.setProperty('--card-width',`${prefs.cardSize}px`);root.lang=prefs.language==='zh'?'zh-CN':'en';
    clearInterval(hueTimer);
    if(prefs.theme==='inner_gamer'){let h=state.hue||0;const update=()=>{const palette=DDTheme.palette(DDTheme.fromHsv(h,.9,1),DDTheme.fromHsv(h+60,.9,1));palette.forEach((v,i)=>root.style.setProperty(`--${keys[i]}`,v));};update();if(prefs.animations&&!M.reduced())hueTimer=setInterval(()=>{h=(h+3)%360;state.hue=h;update();},Math.max(25,250/(state.values['RGB speed']||3)));}
    save();
  }
  function rail(){
    const selected=state.page==='detail'?state.detailOrigin:state.page;
    const oldGlide=document.querySelector('.rail-glide');const oldPosition=oldGlide?{top:parseFloat(oldGlide.style.top)||0,left:parseFloat(oldGlide.style.left)||0,width:parseFloat(oldGlide.style.width)||0,height:parseFloat(oldGlide.style.height)||0}:null;
    document.getElementById('rail').innerHTML=`<div class="rail-list"><div class="rail-glide"></div>${P.navigation.filter(n=>prefs.stores||n[0]!=='stores').map(([id,glyph,label])=>`<button class="nav-item${id===selected?' selected':''}"${attr('act','navigate')}${attr('value',id)} aria-label="${esc(t(label))}" aria-current="${id===selected?'page':'false'}">${icon(glyph)}<span class="nav-label">${esc(t(label))}</span>${id==='updates'?'<span class="badge"></span>':''}</button>`).join('')}</div>${state.session?`<button class="nav-item resume-rail" data-act="resume">${icon('play_arrow')}<span class="nav-label">${esc(t('stores_resume'))}</span></button>`:''}`;
    requestAnimationFrame(()=>{
      const selectedEl=document.querySelector('.nav-item.selected'),glide=document.querySelector('.rail-glide');if(!selectedEl||!glide)return;
      const horizontal=matchMedia('(orientation:portrait)').matches;
      if(oldPosition)Object.entries(oldPosition).forEach(([k,v])=>glide.style[k]=`${v}px`);
      M.spring(glide,horizontal?{left:selectedEl.offsetLeft,width:selectedEl.offsetWidth,top:0,height:selectedEl.offsetHeight}:{top:selectedEl.offsetTop,height:selectedEl.offsetHeight,left:3,width:selectedEl.offsetWidth-6},{damping:.78,stiffness:360});
    });
  }
  function page(html,cls=''){return `<section class="page ${cls}">${html}</section>`;}
  function render(){
    rail();const pane=document.getElementById('pane');
    const views={steam:home,games:library,stores:stores,desktop:desktop,components:components,setup:setup,updates:updates,'android-apps':apps,detail:detail};
    pane.innerHTML=(views[state.page]||home)();applyPrefs();M.pane(pane.firstElementChild);wireImages();
    if(state.page==='steam')requestAnimationFrame(()=>document.querySelectorAll('canvas.throbber').forEach(c=>M.logo(c)));
  }
  function navigate(key,source){
    if(state.layers.length)state.layers.forEach(l=>l.el.remove());state.layers=[];
    document.getElementById('shell').inert=false;
    if(key==='detail'){const g=state.games.find(g=>String(g.id)===String(source));if(g)state.selected=g;}
    else state.search='';state.page=key;render();
  }
  function wireImages(){document.querySelectorAll('img').forEach(img=>{if(img.parentElement.classList.contains('game-title-art')){img.onload=()=>img.parentElement.classList.add('loaded');img.onerror=()=>img.remove();if(img.complete&&img.naturalWidth)img.parentElement.classList.add('loaded');}else img.onerror=()=>{img.style.opacity='0';};});}
  function home(){
    const pictures=Array.from({length:24},(_,i)=>state.games[i%state.games.length]);
    return page(`<div class="home-wall" aria-hidden="true">${pictures.map(g=>`<img src="${art(g)}" alt="">`).join('')}</div><div class="home-shade"></div><div class="home-brand rise">${wordmark()}<span class="runtime-chip">${esc(t('setup_runtime_current','0.6.9'))}</span></div><div class="home-hint rise" style="--i:1">${esc(t('setup_ready'))}</div><div class="home-actions rise" style="--i:2">${button('games_play_steam','launch','steam','primary large shine','play_arrow')}<button class="home-cog" data-act="mode-sheet" data-value="steam" aria-label="${esc(t('game_settings_card'))}">${icon('settings')}</button></div>`,'bleed home');
  }
  function card(g){const s=storeInfo(g.store);return `<button class="game-card" data-act="game" data-value="${g.id}" aria-label="${esc(g.name)}" style="--store:${s[2]};--hue:${g.id%360}"><div class="game-cover"><img src="${art(g)}" alt="" loading="lazy"><span class="game-badge">${s[1]}</span>${state.downloads.some(d=>d.id===g.id)?'<div class="progress-track" style="position:absolute;bottom:0;width:100%"><div class="progress-fill" style="width:40%"></div></div>':''}</div><div class="game-info"><div class="game-name">${esc(g.name)}</div><div class="game-size">${esc(g.installed?g.size:t('proton_not_installed'))}</div></div></button>`;}
  function library(){
    let games=state.games.filter(g=>(prefs.filter==='all'||g.store===prefs.filter)&&(!state.search||g.name.toLowerCase().includes(state.search.toLowerCase()))&&(prefs.showUninstalled||g.installed)&&(state.selectedCollection!=='favorites'||g.favorite));
    const size=g=>parseFloat(g.size)*(g.size.endsWith('GB')?1024:1);
    if(prefs.sort==='name')games.sort((a,b)=>a.name.localeCompare(b.name));if(prefs.sort==='name-desc')games.sort((a,b)=>b.name.localeCompare(a.name));if(prefs.sort==='size')games.sort((a,b)=>size(b)-size(a));if(prefs.sort==='size-asc')games.sort((a,b)=>size(a)-size(b));if(prefs.sort==='source')games.sort((a,b)=>a.store.localeCompare(b.store));if(prefs.sort==='recent')games.sort((a,b)=>a.lastPlayed-b.lastPlayed);if(prefs.sort==='added')games.sort((a,b)=>b.added-a.added);
    const tools=`${ib('stores_search_open','search','search')}${ib('library_display','visibility','display-menu')}${ib('library_filter','filter_alt','filter-menu')}${ib('library_sort','sort','sort-menu')}${ib('library_view','view_list','layout-menu')}${button('game_frontend_files','frontend-files','','secondary small')}${ib('user_apps_add','add','add-menu')}`;
    const filterChips=`<div class="chips tabs" role="tablist"><button class="chip${prefs.filter==='all'?' active':''}" data-act="filter" data-value="all">${esc(t('library_all',''))}</button>${P.stores.filter(s=>state.games.some(g=>g.store===s[0])).map(([id,name,color])=>`<button class="chip${prefs.filter===id?' active':''}" data-act="filter" data-value="${id}"><span class="dot" style="--store:${color}"></span>${name}</button>`).join('')}${ib('library_collections','folder','collections')}</div>`;
    const installed=games.filter(g=>g.installed),uninstalled=games.filter(g=>!g.installed);
    const grid=list=>`<div class="game-grid ${prefs.layout==='list'?'list':prefs.layout==='square'?'square':''}" style="--card-width:${prefs.cardSize}px">${list.map(card).join('')}</div>`;
    return page(title('rail_games',`<span class="spacer"></span>${tools}`,`${games.length} ${prefs.language==='zh'?'个游戏':'games'}`)+
      (state.search!==''?`<div class="search-wrap" style="max-width:none;margin:0 0 12px">${icon('search')}<input autofocus class="search-field" id="library-search" placeholder="${esc(t('stores_search_open'))}" value="${esc(state.search)}" data-input="search">${ib('common_close','close','clear-search')}</div>`:'')+filterChips+
      (games.length?`${installed.length?`<div class="eyebrow">${esc(t('boot_movie_tab_installed'))}</div>${grid(installed)}`:''}${uninstalled.length?`<div class="eyebrow">${esc(t('proton_not_installed'))}</div>${grid(uninstalled)}`:''}`:`<div class="empty-state">${icon('video_library')}<h2>${esc(t('stores_nothing_matches'))}</h2>${button('user_apps_add','add-menu','','secondary','add')}</div>`));
  }
  function stores(){
    const s=storeInfo(state.store),games=state.games.filter(g=>g.store===state.store);const shelf=games.length?games:state.games.slice(0,5);
    return page(`<div class="page-head">${chips(P.stores.map(s=>[s[0],s[1]]),state.store,'store')}<span class="spacer"></span>${ib('stores_tab_downloads','download','downloads')}${ib('stores_settings','settings','stores-settings')}</div>`+
      `<div class="store-billboard rise" style="--store:${s[2]}"><div class="store-wall" aria-hidden="true">${[...shelf,...shelf].map(g=>`<img src="${art(g)}" alt="">`).join('')}</div><div class="store-content"><h2>${s[1]}</h2>${button(state.signedIn[state.store]?'stores_refresh':'stores_signin',state.signedIn[state.store]?'refresh-store':'sign-in',state.store,'primary','login')}</div></div>`+
      `<div class="row"><input class="search-field" placeholder="${esc(t('stores_search_catalog',s[1]))}" data-input="store-search"><span class="spacer"></span>${ib('stores_refresh','refresh','refresh-store')}</div>`+
      ['stores_shelf_new','stores_shelf_deals','stores_shelf_free','stores_shelf_trending'].map((key,i)=>`<div class="section-title">${esc(t(key))}</div><div class="store-shelf">${[...shelf,...state.games].slice(i,i+7).map(card).join('')}</div>`).join(''));
  }
  const emulators=[['rpcs3','RPCS3','PlayStation 3'],['dolphin','Dolphin','GameCube / Wii'],['pcsx2','PCSX2','PlayStation 2'],['ppsspp','PPSSPP','PSP'],['cemu','Cemu','Wii U'],['duckstation','DuckStation','PlayStation'],['melonds','melonDS','Nintendo DS'],['retroarch','RetroArch','Libretro']];
  function desktop(){return page(title('rail_desktop',`<span class="spacer"></span>${ib('game_settings_card','settings','mode-sheet','desktop')}`)+
    `<div class="preview-monitor rise"><img src="assets/logo.png" alt="DroidDeck"><span class="monitor-label">KDE Plasma · 1920 × 1080</span></div><div class="actions">${button('content_open_desktop','launch','desktop','primary large','desktop_windows')}${button('flathub_name','flathub','','secondary','apps')}${button('user_apps_add','add-menu','','secondary','add')}</div>`+
    `<div class="section-title">${esc(t('user_apps_section'))}</div><div class="app-grid">${emulators.map(([id,name,sub])=>`<button class="app-icon" data-act="emulator" data-value="${id}"><img src="assets/emu_${id}.png" alt=""><span>${name}</span><span class="tiny">${sub}</span></button>`).join('')}</div>`+
    `<div class="panel">${setting({kind:'action',key:'setup_tool_files',detail:'setup_tool_files_hint',event:'files'})}${setting({kind:'action',key:'setup_tool_roms',detail:'setup_tool_roms_hint',event:'roms'})}</div>`);
  }
  function components(){return page(title('comp_title',`<span class="spacer"></span>${ib('comp_check_all','refresh','check-components')}`)+
    `<div class="runtime-chip" style="display:inline-block;margin-bottom:15px">● Adreno 740</div><div class="panel">${setting({kind:'choice',key:'comp_profile',options:['comp_scope_general',...state.games.map(g=>g.name)]})}</div>`+
    `<div class="eyebrow">${esc(t('setup_group_device'))}</div><div class="panel">${setting({kind:'link',key:'mode_gpu_drivers',route:'drivers',value:'Mesa Turnip 25.1.0'})}</div>`+
    `<div class="eyebrow">${esc(t('comp_profile'))}</div><div class="panel">${[['Proton','proton','DroidDeck Proton 11.0'],['DXVK','dxvk','Original'],['VKD3D-Proton','vkd3d','Original'],['FEX','fex','Original']].map(([key,route,value])=>setting({kind:'link',key,route,value})).join('')}</div>`+
    `<div class="actions">${button('game_env_title','route','environment')}${button('win_components_title','route','win-components')}${button('fex_preset_title','route','performance')}${button('comp_import_wcp','file-import')}</div>`);
  }
  const setupTabs=[['overview','setup_tab_overview'],['controller','setup_tab_controller'],['launcher','setup_tab_launcher'],['storage','setup_tab_storage'],['diagnostics','setup_tab_diagnostics'],['glasses','setup_tab_glasses']];
  function setup(){const content=state.setupTab==='overview'?overview():state.setupTab==='controller'?controllerPreview()+schema('controller'):state.setupTab==='storage'?DD_PANELS('storage-overview',{t,esc,icon,button,setting,state}).body+schema('storage'):schema(state.setupTab);return page(title('setup_title',chips(setupTabs,state.setupTab,'setup-tab'))+content);}
  function overview(){return `<div class="readiness rise"><span class="icon">check_circle</span><div class="spacer"><b>${esc(t('setup_all_set'))}</b><p class="tiny muted" style="margin-top:5px">DroidDeck 0.6.9 · Linux runtime</p></div>${button('setup_details','checks','','secondary small')}</div><div class="eyebrow">${esc(t('setup_tools'))}</div><div class="panel">${setting({kind:'link',key:'mode_steam_title',route:'steam-settings'})}${setting({kind:'link',key:'perf_title',route:'performance'})}${setting({kind:'link',key:'comp_title',route:'components'})}${setting({kind:'link',key:'boot_movie',route:'boot-movies'})}${setting({kind:'link',key:'setup_dual_screen',route:'dual-screen'})}${setting({kind:'link',key:'sync_title',route:'sync'})}${setting({kind:'action',key:'setup_adb_pair',event:'wireless-adb'})}</div>`;}
  function updates(){return page(title('rail_updates',`<span class="spacer"></span>${ib('common_refresh','refresh','check-updates')}`)+`<div class="readiness rise">${icon('system_update')}<div><b>DroidDeck 0.6.9</b><p class="muted tiny">${esc(t('setup_runtime_current','0.6.9'))}</p></div></div><div class="section-title">${esc(t('setup_runtime'))}</div><div class="panel">${setting({kind:'text',key:'comp_profile',value:'DroidDeck Proton 11.0'})}${setting({kind:'text',key:'FEX',value:'2605'})}${setting({kind:'text',key:'DXVK',value:'2.7.1'})}${setting({kind:'text',key:'VKD3D-Proton',value:'3.0'})}</div><div class="actions">${button('comp_check_all','check-updates','','primary','refresh')}${button('updates_release_notes','release-notes')}${button('common_about','about')}</div>`);}
  function apps(){const entries=[['calendar_month','Calendar'],['schedule','Clock'],['folder','Files'],['photo_library','Gallery'],['headphones','Music'],['play_circle','YouTube'],['public','Browser'],['settings','Settings']];return page(title('rail_apps',`<span class="spacer"></span>${ib('stores_search_open','search','search')}${ib('library_filter','filter_alt','filter-menu')}${ib('library_sort','sort','sort-menu')}`)+`<div class="search-wrap" style="margin-bottom:15px"><input class="search-field" placeholder="${esc(t('stores_search_open'))}" data-input="apps-search"></div><div class="app-grid">${entries.map(([glyph,name])=>`<button class="app-icon" data-act="local-app" data-value="${name}">${icon(glyph)}<span>${name}</span></button>`).join('')}</div>`);}
  function setting(row){
    const key=row.key,value=state.values[key]??row.value??row.on??(row.options?.[0]);const detail=row.detail?`<div class="setting-detail">${esc(t(row.detail))}</div>`:'';
    const copy=`<div class="setting-copy"><div class="setting-label">${esc(t(key))}</div>${detail}</div>`;
    if(row.kind==='heading')return `<div class="panel-head">${esc(t(key))}</div>`;
    if(row.kind==='toggle')return `<div class="setting-row">${copy}<button class="switch" role="switch" aria-label="${esc(t(key))}" aria-checked="${Boolean(value)}" data-act="toggle" data-value="${esc(key)}" data-default="${Boolean(row.on)}"></button></div>`;
    if(row.kind==='range')return `<div class="setting-row">${copy}<output class="tiny muted">${esc(value??row.value??50)}${row.unit??'%'}</output><input type="range" min="${row.min??0}" max="${row.max??100}" value="${value??50}" aria-label="${esc(t(key))}" data-range="${esc(key)}" data-unit="${esc(row.unit??'%')}"></div>`;
    if(row.kind==='text')return `<div class="setting-row">${copy}<span class="setting-value">${esc(t(String(row.value??'—')))}</span></div>`;
    const act=row.kind==='link'?'route':row.kind==='choice'?'pick':row.event||'action';
    const displayValue=row.kind==='choice'?(typeof value==='number'?row.options[value]:value):row.value;
    return `<button class="setting-row clickable" data-act="${act}" data-value="${esc(row.route||key)}"${row.options?attr('options',JSON.stringify(row.options)):''}>${copy}<span class="setting-value">${displayValue!==undefined?esc(t(String(displayValue))):''}${icon(row.kind==='choice'?'unfold_more':'chevron_right')}</span></button>`;
  }
  function schema(key){return (P.schemas[key]||[]).map((g,i)=>`<section class="rise" style="--i:${Math.min(i,4)}"><div class="eyebrow">${esc(t(g.key))}</div><div class="panel">${g.rows.map(setting).join('')}</div></section>`).join('');}
  function fromSource(name){const rows=C.panels[name]||[];return rows.length?`<div class="panel">${rows.map(r=>setting({...r,options:r.kind==='choice'?['common_auto','common_on','common_off']:undefined,event:'local-option'})).join('')}</div>`:`<div class="panel">${setting({kind:'toggle',key:'common_on'})}${setting({kind:'choice',key:'comp_profile',options:['common_auto','comp_scope_general']})}</div>`;}
  function detail(){
    const g=state.selected||state.games[0],s=storeInfo(g.store);let body='';
    if(state.detailTab==='about')body=`<div class="facts"><div class="fact"><b>${esc(s[1])}</b><span>${esc(t('stores_installed_chip'))}</span></div><div class="fact"><b>${g.size}</b><span>${esc(t('game_install_size'))}</span></div><div class="fact"><b>${esc(t('game_install_access_owned'))}</b><span>${esc(t('game_install_access'))}</span></div></div><div class="section-title">${esc(t('store_about'))}</div><div class="note">${esc(g.name)}</div><div class="actions">${button('PCGamingWiki','resource-preview','PCGamingWiki')}${button('game_resource_guides','resource-preview','game_resource_guides')}${button('ProtonDB','resource-preview','ProtonDB')}${button('game_resource_steam_cloud','resource-preview','game_resource_steam_cloud')}${button('game_resource_search','resource-preview','game_resource_search')}</div>`;
    else if(state.detailTab==='install')body=`<div class="panel">${setting({kind:'text',key:'game_install_folder',value:`C:\\Games\\${g.name}`})}${setting({kind:'text',key:'game_install_size',value:g.size})}${setting({kind:'text',key:'game_install_version',value:'1.0'})}</div><div class="actions">${button('common_remove','remove-game',g.id,'danger','delete')}${button('gog_verify','verify-game',g.id)}${button('setup_tool_files','files')}</div>`;
    else if(state.detailTab==='launch')body=schema('display')+schema('controls')+`<div class="actions">${button('game_env_title','route','environment')}${button('win_components_title','route','win-components')}${button('perf_title','route','performance')}</div>`;
    else if(state.detailTab==='saves')body=`<div class="panel">${setting({kind:'toggle',key:'game_resource_steam_cloud',on:true})}${setting({kind:'action',key:'sync_title',event:'sync'})}${setting({kind:'action',key:'common_restore',event:'restore-saves'})}</div>`;
    else body=`<div class="section-title">${esc(t('achievements_title'))} · 3 / 25</div>${['First steps','Explorer','Against all odds','The journey continues'].map((name,i)=>`<div class="panel achievement"><span class="achievement-icon">${icon(i<3?'emoji_events':'lock')}</span><div><b>${name}</b><p class="tiny muted">${i<3?'✓':'—'}</p></div></div>`).join('')}`;
    const returnLabel=state.detailOrigin==='stores'?'rail_stores':'rail_games';
    const status=[t(g.installed?'stores_installed_chip':'proton_not_installed'),t('stores_target_internal'),g.size].join(' · ');
    const tabs=[['about','game_tab_about'],['achievements','achievements_title'],['launch','game_tab_launch'],['saves','game_tab_saves_cloud'],['install','game_tab_install']];
    return page(`<div class="game-detail-backdrop"><img src="assets/library_hero-${g.id}.jpg" alt=""><div></div></div><div class="detail-content"><div class="detail-top"><button class="page-back" data-act="navigate" data-value="${state.detailOrigin}">${icon('chevron_left')}${esc(t(returnLabel))}</button><span class="spacer"></span>${ib('common_remove','delete','remove-game',g.id)}</div><div class="game-status-row"><span class="source-pill" style="--store:${s[2]}"><i></i>${esc(s[1])}</span><span>${esc(status)}</span></div><div class="game-title-art"><img src="assets/logo-${g.id}.png" alt="${esc(g.name)}"><h1 class="detail-title">${esc(g.name)}</h1></div><div class="game-action-capsule">${button(g.installed?'stores_play':'store_install',g.installed?'launch':'route',g.installed?g.id:'install-options','primary large','play_arrow')}${button('game_more','game-more',g.id,'secondary')}${ib('Favorites',g.favorite?'star':'star_outline','favorite',g.id)}<span class="spacer"></span>${ib('game_settings_card','settings','mode-sheet','game')}</div><div class="game-tab-bar">${ib('drawer_prev_page','keyboard_arrow_left','cycle-detail','-1')}${chips(tabs,state.detailTab,'detail-tab')}${ib('drawer_next_page','keyboard_arrow_right','cycle-detail','1')}</div><div class="detail-body">${body}</div></div>`,'detail-page');
  }
  function controllerPreview(){return `<div class="controller-preview" aria-label="${esc(t('ctrl_layout'))}">${[['L2',8,8,'shoulder'],['R2',78,8,'shoulder'],['L1',8,24,'shoulder'],['R1',78,24,'shoulder'],['L',16,51,'stick'],['R',64,64,'stick'],['↑',29,40,''],['↓',29,72,''],['←',22,57,''],['→',36,57,''],['Y',85,39,''],['A',85,72,''],['X',78,56,''],['B',92,56,''],['☰',52,34,''],['▣',44,34,'']].map(([label,x,y,cls])=>`<button class="pad-part ${cls}" data-pad="${label}" style="left:calc(${x}% - 22px);top:calc(${y}% - 22px)">${label}</button>`).join('')}</div>`;}
  function toast(message){const el=document.getElementById('toast');el.textContent=t(message);el.classList.add('shown');clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.classList.remove('shown'),2600);}
  function layer(html,kind='dialog',wide=false){
    document.getElementById('shell').inert=true;
    if(state.layers.length)state.layers.at(-1).el.inert=true;
    const el=document.createElement('div');el.className=`layer ${kind==='sheet'?'sheet-layer':kind==='popover'?'popover-layer':''}`;
    el.innerHTML=`<div class="scrim" data-act="close"></div>${html}`;document.getElementById('layers').append(el);const previous=document.activeElement;
    const entry={el,previous};state.layers.push(entry);requestAnimationFrame(()=>{el.classList.add('shown');if(kind==='sheet')M.lift(el);el.querySelector('input,button')?.focus({preventScroll:true});});
    M.wireSheet(el);wireImages();return el;
  }
  function closeLayer(){const last=state.layers.pop();if(!last)return;last.el.classList.remove('shown');last.el.inert=true;last.el.style.pointerEvents='none';const duration=M.fold(last.el);document.getElementById('shell').inert=Boolean(state.layers.length||state.session);if(state.layers.length)state.layers.at(-1).el.inert=false;setTimeout(()=>{last.el.remove();last.previous?.isConnected&&last.previous.focus({preventScroll:true});},M.reduced()?0:duration);}
  function dialog(label,body,footer='',wide=false){return layer(`<section class="dialog${wide?' wide':''}" role="dialog" aria-modal="true" aria-label="${esc(t(label))}"><div class="dialog-head"><h2>${esc(t(label))}</h2>${ib('common_close','close','close')}</div><div class="dialog-body">${body}</div>${footer?`<div class="dialog-foot">${footer}</div>`:''}</section>`);}
  function popover(label,body,anchor){
    const el=layer(`<section class="popover" role="dialog" aria-label="${esc(t(label))}"><div class="popover-title">${esc(t(label))}</div>${body}</section>`,'popover');
    const pop=el.querySelector('.popover'),a=anchor?.getBoundingClientRect()||{right:innerWidth/2,bottom:80};
    const width=Math.min(320,innerWidth-24);pop.style.width=`${width}px`;pop.style.left=`${Math.max(12,Math.min(a.right-width,innerWidth-width-12))}px`;pop.style.top=`${Math.max(12,Math.min(a.bottom+5,innerHeight-Math.min(pop.offsetHeight||240,innerHeight*.75)-12))}px`;pop.style.transformOrigin='top right';return el;
  }
  function route(key){
    const api={t,esc,icon,button,setting,fromSource,state};
    const custom=DD_PANELS(key,api)||DD_DETAILS(key,api);
    if(custom){dialog(custom.title,custom.body,custom.footer,custom.wide);return;}
    if(key==='components'){closeLayer();navigate('components');return;}
    if(key==='environment'){environment();return;}if(key==='themes'){themes();return;}if(key==='boot-movies'){bootMovies();return;}
    if(key==='controller-layout'){dialog('ctrl_layout',controllerPreview()+`<div class="actions">${button('ctrl_editor_snap','snap')}${button('ctrl_reset','reset-layout')}</div>`,button('ctrl_editor_save','close'),true);wireController(true);return;}
    if(key==='controller-mapping'){mapping();return;}if(key==='flathub'){flathub();return;}
    if(['proton','dxvk','vkd3d','fex'].includes(key)){componentDetail(key);return;}
    if(key==='wireless-adb'||key==='process-limit'){pairing();return;}if(key==='calibration'){calibration();return;}
    if(key==='bottom-dashboard'){bottomDashboard();return;}if(key==='screen-layout'){screenLayout();return;}
    if(key==='steam-settings'){modeSheet('steam');return;}
    const name=P.routes[key]?.[1]||({display:'mode_display',controls:'mode_touch_controls',audio:'mode_audio',performance:'perf_title',session:'mode_session',library:'mode_storage',controller:'setup_controller',storage:'setup_tab_storage',diagnostics:'setup_tab_diagnostics',launcher:'setup_launcher',glasses:'setup_tab_glasses',drivers:'mode_gpu_drivers',decky:'mode_decky','dual-screen':'setup_dual_screen'}[key])||key;
    dialog(name,(P.schemas[key]?schema(key):fromSource(P.routes[key]?.[0]||key)),button('common_done','close'),true);wireController();
  }
  function modeSheet(mode='steam',tab='steam'){
    state.modeTab=tab;const options=mode==='desktop'?[['display','mode_display'],['controls','mode_touch_controls'],['session','mode_session']]:[['steam','mode_tab_steam'],['display','mode_display'],['controls','drawer_page_controls'],['audio','mode_audio'],['session','mode_session'],['library','stores_tab_library']];
    const el=layer(`<section class="lift-sheet" role="dialog" aria-modal="true" aria-label="${esc(t(mode==='desktop'?'mode_desktop_title':'mode_steam_title'))}" data-mode="${mode}"><div class="handle" aria-label="${esc(t('common_close'))}"></div><div class="sheet-top"><h2>${esc(t(mode==='desktop'?'mode_desktop_title':'mode_steam_title'))}</h2><span class="spacer"></span>${ib('common_close','close','close')}${chips(options,tab,'mode-tab')}</div><div class="sheet-body">${schema(tab)}</div><div class="lift-footer">${button('games_play','launch',mode,'primary fill','play_arrow')}${button('common_close','close')}</div></section>`,'sheet');el.querySelectorAll('.setting-row').forEach((e,i)=>{e.classList.add('sheet-piece');e.style.setProperty('--i',i);});
  }
  function themes(){dialog('setup_theme',`<div class="themes">${Object.entries(palettes).map(([id,colors])=>`<button class="theme-tile${prefs.theme===id?' selected':''}" data-act="theme" data-value="${id}"><span class="swatches">${[colors[0],colors[1],colors[7],colors[8]].map(c=>`<i class="swatch" style="background:${c}"></i>`).join('')}</span>${esc(t({graphite:'theme_graphite',paper:'theme_paper',blue:'theme_icon_blue',electric:'theme_electric',inner_gamer:'theme_inner_gamer',gradient:'theme_gradient'}[id]))}</button>`).join('')}</div><div class="panel">${setting({kind:'range',key:'RGB speed',min:1,max:10,value:3,unit:''})}<div class="setting-row"><span>${prefs.language==='zh'?'主色':'Primary'}</span><input class="color-input" type="color" value="${palettes.gradient[7]}" data-color="primary"></div><div class="setting-row"><span>${prefs.language==='zh'?'辅助色':'Secondary'}</span><input class="color-input" type="color" value="${palettes.gradient[8]}" data-color="primary2"></div></div>`,button('common_done','close'),true);}
  function mapping(){dialog('ctrl_mapping',`<p class="lede">${esc(t('ctrl_mapping_lede'))}</p><div class="panel">${['A','B','X','Y','LB','RB','LT','RT','L3','R3','View','Menu','↑','↓','←','→'].map(k=>setting({kind:'choice',key:k,options:[k,'A','B','X','Y','L3','R3','Space','Enter','Escape','ctrl_target_hidden']})).join('')}</div>`,button('ctrl_reset_mapping','reset-mapping')+button('common_done','close'));}
  function environment(){dialog('game_env_title',`<div class="panel">${setting({kind:'choice',key:'game_env_scope',options:['comp_scope_general',...state.games.map(g=>g.name)]})}</div><div id="environment-rows">${Object.entries(state.environment||{}).map(([k,v])=>`<div class="setting-row"><b>${esc(k)}</b><span>${esc(v)}</span>${ib('common_delete','close','remove-env',k)}</div>`).join('')||`<div class="empty-state" style="min-height:100px">${esc(t('game_env_empty'))}</div>`}</div><div class="actions">${button('game_env_add','add-env','','primary','add')}</div>`,button('common_done','close'),true);}
  function componentDetail(key){const name={proton:'Proton',dxvk:'DXVK',vkd3d:'VKD3D-Proton',fex:'FEX'}[key];dialog(name,`<div class="panel">${['Original',`${name} Stable`,`${name} Nightly`].map((v,i)=>setting({kind:'action',key:v,event:'select-component',value:i?'comp_get':'comp_original'})).join('')}</div><div class="actions">${button('comp_import_wcp','file-import')}${button('comp_check_all','check-components')}${button('comp_restore_original','restore-component')}</div>`,button('common_done','close'),true);}
  function flathub(){dialog('flathub_name',`<p class="lede">${esc(t('flathub_line'))}</p>${chips([['discover','store_tab_discover'],['installed','store_tab_installed'],['updates','store_updates']],state.storeTab,'flathub-tab')}<div class="app-grid">${[['public','Firefox'],['terminal','Konsole'],['brush','Krita'],['movie','VLC'],['code','Visual Studio Code'],['sports_esports','RetroArch']].map(([glyph,name])=>`<button class="app-icon" data-act="flathub-app" data-value="${name}">${icon(glyph)}<span>${name}</span></button>`).join('')}</div>`,button('common_close','close'),true);}
  function bootMovies(){dialog('boot_movie',chips([['installed','boot_movie_tab_installed'],['import','boot_movie_tab_import'],['repo','boot_movie_tab_repo'],['sound','boot_movie_tab_sound']],'installed','boot-tab')+`<div id="boot-content"><div class="preview-monitor" style="background:#000"><img src="assets/logo.png" alt="DroidDeck"></div><div class="actions">${button('boot_movie_repo_preview','boot-preview','','primary','play_arrow')}${button('boot_movie_repo_use','use-boot')}</div><div class="panel">${setting({kind:'range',key:'boot_movie_volume',min:0,max:100,value:70})}${setting({kind:'range',key:'boot_movie_length',min:1,max:30,value:6,unit:' s'})}</div></div>`,button('common_close','close'),true);}
  function pairing(step=0){const texts=['setup_use_wireless','setup_adb_pair','setup_check_again','setup_check_done'];dialog('setup_adb_pair',`<div class="row" style="justify-content:center;padding:15px">${texts.map((_,i)=>`<span class="stage-dot${i===step?' active':''}"></span>`).join('')}</div><h3>${esc(t(texts[step]))}</h3><div class="guide-list">${['setup_dev_options','setup_use_wireless','setup_adb_pair'].map((k,i)=>`<div class="guide-step"><span class="step-number">${i+1}</span><div>${esc(t(k))}</div></div>`).join('')}</div>${step===1?'<input class="search-field" placeholder="192.168.1.2:37000"><input class="search-field" placeholder="000000" inputmode="numeric" style="margin-top:10px">':''}`,button('common_cancel','close')+button(step===3?'common_done':'common_next',step===3?'close':'pair-next',String(step+1),'primary'));}
  function calibration(){dialog('glasses_calibration',`<div class="preview-monitor">${icon('view_in_ar')}</div><p class="lede" style="margin-top:16px">${esc(t('glasses_calibration_turn_over'))}</p>`,button('common_cancel','close')+button('glasses_calibration_start','calibrate','','primary'));}
  function screenLayout(){dialog('screen_layout_title',`<div class="row"><div class="preview-monitor" style="flex:1">1</div><div class="preview-monitor" style="flex:1">2</div></div>${schema('dual-screen')}`,button('common_done','close'),true);}
  function bottomDashboard(){dialog('setup_dual_screen',`<div class="chips tabs">${['dashboard','chat','notifications','downloads','screenshots','telemetry'].map((id,i)=>`<button class="chip${i===0?' active':''}" data-act="dashboard-tab" data-value="${id}">${icon(['dashboard','chat','notifications','download','photo_library','monitoring'][i])}</button>`).join('')}</div><div id="dashboard-content">${controllerPreview()}<div class="actions">${button('keyboard_title','keyboard','','secondary','keyboard')}${button('mode_touch_touchpad','touchpad')}</div></div>`,button('common_close','close'),true);wireController();}
  function keyboard(){const keys=['Esc F1 F2 F3 F4 F5 F6 F7 F8 F9 F10 F11 F12','1 2 3 4 5 6 7 8 9 0 - =','Q W E R T Y U I O P','A S D F G H J K L','Shift Z X C V B N M ←','Ctrl Alt Space Enter'];dialog('keyboard_title',`<input id="keyboard-input" class="keyboard-input" aria-label="${esc(t('keyboard_title'))}"><div class="keyboard">${keys.map(row=>`<div class="key-row">${row.split(' ').map(k=>`<button class="key${k==='Space'?' space':''}" data-act="key" data-value="${k}">${k}</button>`).join('')}</div>`).join('')}</div>`,button('common_done','close'),true);}

  function downloadList(){return state.downloads.length?state.downloads.map(d=>{const g=state.games.find(g=>g.id===d.id);return `<div class="panel download-card" data-download="${d.id}"><img src="${art(g)}" alt=""><div class="download-copy"><b>${esc(g.name)}</b><div class="progress-track"><div class="progress-fill" style="width:${d.progress}%"></div></div><div class="tiny muted"><span class="download-status">${d.paused?t('stores_dl_paused'):`${Math.floor(d.progress)}%`}</span></div></div>${ib(d.paused?'stores_resume':'stores_pause',d.paused?'play_arrow':'pause','pause-download',d.id)}${ib('common_cancel','close','cancel-download',d.id)}</div>`;}).join(''):`<div class="empty-state" style="min-height:180px">${icon('download_done')}<p>${esc(t('downloads_empty'))}</p></div>`;}
  function install(id,source){
    const game=state.games.find(g=>String(g.id)===String(id));if(!game)return;
    if(!state.downloads.some(d=>d.id===game.id))state.downloads.push({id:game.id,progress:0,paused:false});
    M.flight(source,document.querySelector('[data-value="stores"]'));closeLayer();dialog('stores_tab_downloads',downloadList(),button('common_close','close'),true);
  }
  function sessionView(){
    const s=state.session;if(!s)return;
    document.getElementById('session-screen')?.remove();
    const el=document.createElement('section');el.id='session-screen';el.className=`session${s.stage==='running'?' game-placeholder':''}`;
    const game=state.games.find(g=>String(g.id)===String(s.id));const name=game?.name||(s.id==='desktop'?'KDE Plasma':'Steam');
    el.innerHTML=`${game?`<img class="session-art" src="${art(game)}" alt="">`:''}${s.stage==='loading'?`<canvas class="throbber" aria-label="${esc(t('common_loading'))}"></canvas><div class="session-name">${esc(t(s.id==='desktop'?'desktop_starting':'session_starting_steam'))}</div><div class="session-status">${esc(t('session_loading_client'))}</div><div class="progress-track indeterminate"><div class="progress-fill"></div></div>`:`<div class="session-name">${esc(name)}</div>${s.paused?`<p class="paused">${esc(t('stores_dl_paused'))}</p>`:''}<div class="actions">${button('drawer_menu','drawer','','secondary','menu')}${button('mode_touch_touchpad','touchpad')}${button('keyboard_title','keyboard','','secondary','keyboard')}</div>${state.values.touchOverlay?`<div style="position:absolute;inset:auto 25px 80px;width:calc(100% - 50px)">${controllerPreview()}</div>`:''}`}
      ${state.values.hud?'<div class="hud"><span>FPS 60</span><span>CPU 18%</span><span>GPU 32%</span><span>RAM 2.4 GB</span></div>':''}
      <div class="session-bottom"><span>${esc(name)}</span><span class="spacer"></span>${button(s.stage==='loading'?'common_cancel':'drawer_menu',s.stage==='loading'?'stop-session':'drawer','','secondary small',s.stage==='loading'?'close':'menu')}</div>`;
    document.getElementById('layers').before(el);M.pane(el);el.querySelectorAll('.throbber').forEach(c=>M.logo(c));wireController();
  }
  function launch(id){
    while(state.layers.length){const last=state.layers.pop();last.el.remove();}
    document.getElementById('shell').inert=true;
    state.session={id:String(id),stage:'loading',paused:false};sessionView();rail();
    clearTimeout(launch.timer);launch.timer=setTimeout(()=>{if(state.session){state.session.stage='running';sessionView();}},2600);
  }
  const drawerTabs=[['display','drawer_page_display'],['effects','drawer_page_effects'],['controls','drawer_page_controls'],['components','drawer_page_components'],['glasses','drawer_page_glasses'],['session','drawer_page_settings']];
  function drawer(tab='display'){
    let body=tab==='components'?schema('drivers')+`<div class="actions">${button('Proton','route','proton')}${button('DXVK','route','dxvk')}${button('FEX','route','fex')}</div>`:schema(tab);
    const el=layer(`<section class="session-drawer" role="dialog" aria-modal="true" aria-label="${esc(t('drawer_menu'))}"><div class="drawer-head"><b>${esc(state.games.find(g=>String(g.id)===state.session?.id)?.name||'Steam')}</b><span class="spacer"></span>${ib('common_close','close','close')}</div><div class="drawer-tabs">${chips(drawerTabs,tab,'drawer-tab')}</div><div class="drawer-content">${body}<div class="panel">${setting({kind:'toggle',key:'hud',on:false})}${setting({kind:'toggle',key:'touchOverlay',on:false})}</div></div><div class="drawer-footer">${button('stores_resume','resume','','primary','play_arrow')}${button('Pause','pause-session','','secondary','pause')}${button('Stop','stop-confirm','','danger','stop')}</div></section>`);
    el.querySelectorAll('.setting-row').forEach((e,i)=>{e.classList.add('sheet-piece');e.style.setProperty('--i',i);});
  }
  function signIn(store='steam'){
    state.signInStore=storeInfo(store)[0];const name=storeInfo(store)[1];
    dialog(`${name} · ${t('stores_signin')}`,`${chips([['credentials','stores_signin'],['qr','QR Code']],'credentials','signin-tab')}<div id="sign-in-body"><div class="sign-in-fields"><input class="search-field" id="sign-name" placeholder="${prefs.language==='zh'?'用户名':'Username'}" aria-label="Username" autocomplete="off"><input class="search-field" type="password" placeholder="${prefs.language==='zh'?'密码':'Password'}" aria-label="Password" autocomplete="off"></div></div>`,button('common_cancel','close')+button('stores_signin','finish-signin',store,'primary','login'));
  }
  function addMenu(anchor){popover('user_apps_add',[
    ['add-game','folder','user_apps_add'],['file-import','description','Exe'],['steam-import','download','steam_import_title'],['roms','sports_esports','setup_tool_roms']
  ].map(([act,glyph,key])=>`<button class="choice" data-act="${act}">${icon(glyph)}${esc(t(key))}</button>`).join(''),anchor);}
  function options(label,items,action,anchor,current){popover(label,items.map(([value,text])=>`<button class="choice${String(current)===String(value)?' selected':''}" data-act="${action}" data-value="${esc(value)}">${esc(t(text))}${String(current)===String(value)?icon('check'):''}</button>`).join(''),anchor);}
  function confirm(label,detail,act,value=''){dialog(label,`<p class="lede">${esc(t(detail))}</p>`,button('common_cancel','close')+button('common_confirm',act,value,'danger'));}
  function logs(){dialog('setup_logs',`<div class="panel" style="padding:16px"><pre style="white-space:pre-wrap;line-height:1.8;font:12px monospace">DroidDeck UI · 0.6.9\n${esc(state.notifications.slice(-15).join('\n'))}</pre></div>`,button('common_close','close'));}
  function wireController(draggable=false){
    document.querySelectorAll('[data-pad]').forEach(el=>{
      el.onpointerdown=event=>{el.classList.add('pressed');el.setPointerCapture(event.pointerId);if(draggable)el.dataset.origin=`${event.clientX},${event.clientY},${el.offsetLeft},${el.offsetTop}`;};
      el.onpointerup=()=>{el.classList.remove('pressed');delete el.dataset.origin;};el.onpointercancel=el.onpointerup;
      el.onpointermove=event=>{if(!el.dataset.origin)return;const [x,y,left,top]=el.dataset.origin.split(',').map(Number);el.style.left=`${left+event.clientX-x}px`;el.style.top=`${top+event.clientY-y}px`;};
    });
  }
  function setToggle(key,element){
    const value=element.getAttribute('aria-checked')!=='true';state.values[key]=value;element.setAttribute('aria-checked',String(value));
    const map={setup_animations:'animations',setup_rail_labels:'labels',setup_stores:'stores'};
    if(map[key]){prefs[map[key]]=value;applyPrefs();rail();}
    if(key==='hud'||key==='touchOverlay')sessionView();
    saveOptions();
  }
  function pickValue(key,value){
    state.values[key]=value;
    if(key==='setup_language'){prefs.language=value==='English'?'en':'zh';render();}
    closeLayer();
    if(state.layers.length){const current=state.layers.at(-1).el;current.querySelectorAll('[data-act="pick"]').forEach(e=>{if(e.dataset.value===key){const span=e.querySelector('.setting-value');if(span)span.innerHTML=esc(t(value))+icon('unfold_more');}});}
    saveOptions();
  }
  function knownAction(act,value,el){
    switch(act){
      case 'navigate':navigate(value);break;
      case 'close':closeLayer();break;
      case 'route':route(value);break;
      case 'game':{const g=state.games.find(g=>String(g.id)===value);if(!g)break;state.selected=g;state.detailTab='about';state.detailOrigin=state.page==='stores'?'stores':'games';M.flood(el.querySelector('.game-cover')||el,document.getElementById('pane'),()=>navigate('detail',value));break;}
      case 'filter':prefs.filter=value;save();render();break;
      case 'store':state.store=value;render();break;
      case 'setup-tab':state.setupTab=value;render();break;
      case 'detail-tab':state.detailTab=value;render();break;
      case 'cycle-detail':{const tabs=['about','achievements','launch','saves','install'];state.detailTab=tabs[(tabs.indexOf(state.detailTab)+Number(value)+tabs.length)%tabs.length];render();break;}
      case 'search':state.search=state.search||' ';render();requestAnimationFrame(()=>document.getElementById('library-search')?.focus());break;
      case 'clear-search':state.search='';render();break;
      case 'filter-menu':options('library_filter',[['all','library_all'],['installed','boot_movie_tab_installed'],['all-games','proton_not_installed']], 'set-filter',el,prefs.showUninstalled?'all':'installed');break;
      case 'set-filter':prefs.showUninstalled=value!=='installed';prefs.filter='all';closeLayer();render();break;
      case 'sort-menu':options('library_sort',[['recent','stores_sort_last_played'],['added','stores_sort_recently_installed'],['name','stores_sort_title_asc'],['name-desc','stores_sort_title_desc'],['size','stores_sort_size_desc'],['size-asc','stores_sort_size_asc']],'set-sort',el,prefs.sort);break;
      case 'set-sort':prefs.sort=value;closeLayer();save();render();break;
      case 'layout-menu':options('library_view',[['capsule','library_view_grid'],['square','Square'],['list','library_view_list']],'set-layout',el,prefs.layout);break;
      case 'set-layout':prefs.layout=value;closeLayer();save();render();break;
      case 'display-menu':popover('library_display',`${setting({kind:'range',key:'cardSize',min:90,max:250,value:prefs.cardSize,unit:' px'})}${setting({kind:'toggle',key:'showTitles',on:prefs.showTitles})}${setting({kind:'toggle',key:'showSizes',on:prefs.showSizes})}`,el);break;
      case 'collections':options('library_collections',[['all','library_all'],['favorites','Favorites'],['recent','Recently played']],'set-collection',el,state.selectedCollection);break;
      case 'set-collection':state.selectedCollection=value;closeLayer();render();break;
      case 'favorite':{const game=state.games.find(g=>String(g.id)===value);if(game)game.favorite=!game.favorite;render();break;}
      case 'add-menu':addMenu(el);break;
      case 'add-game':closeLayer();dialog('user_apps_add',`<div class="sign-in-fields"><input id="add-title" class="search-field" placeholder="${prefs.language==='zh'?'名称':'Name'}"><input class="search-field" placeholder="C:\\Games\\game.exe"></div>`,button('common_cancel','close')+button('user_apps_add','finish-add','','primary'));break;
      case 'finish-add':{const name=document.getElementById('add-title')?.value.trim();if(name)state.games.push({id:Date.now(),name,store:'steam',installed:true,size:'—'});closeLayer();render();break;}
      case 'toggle':setToggle(value,el);if(value==='showTitles'||value==='showSizes'){prefs[value]=state.values[value];applyPrefs();}break;
      case 'pick':{let opts=[];try{opts=JSON.parse(el.dataset.options);}catch{}const key=value;popover(key,opts.map(v=>`<button class="choice" data-act="pick-value" data-key="${esc(key)}" data-value="${esc(v)}">${esc(t(v))}</button>`).join(''),el);break;}
      case 'pick-value':pickValue(el.dataset.key,value);break;
      case 'mode-sheet':modeSheet(value==='desktop'?'desktop':'steam',value==='desktop'?'display':'steam');break;
      case 'mode-tab':{const sheet=el.closest('.lift-sheet');state.modeTab=value;sheet.querySelectorAll('[role=tab]').forEach(t=>{t.classList.toggle('active',t.dataset.value===value);t.setAttribute('aria-selected',String(t.dataset.value===value));});sheet.querySelector('.sheet-body').innerHTML=schema(value);M.pane(sheet.querySelector('.sheet-body'));break;}
      case 'theme':prefs.theme=value;applyPrefs();document.querySelectorAll('.theme-tile').forEach(t=>t.classList.toggle('selected',t.dataset.value===value));break;
      case 'launch':M.launchFlood(el,()=>launch(value));break;
      case 'resume':closeLayer();sessionView();break;
      case 'drawer':drawer();break;
      case 'drawer-tab':{closeLayer();setTimeout(()=>drawer(value),M.reduced()?0:120);break;}
      case 'pause-session':if(state.session){state.session.paused=!state.session.paused;sessionView();}break;
      case 'stop-confirm':confirm('Stop','Stop this session?','stop-session');break;
      case 'stop-session':while(state.layers.length){state.layers.pop().el.remove();}state.session=null;document.getElementById('shell').inert=false;clearTimeout(launch.timer);document.getElementById('session-screen')?.remove();render();break;
      case 'keyboard':keyboard();break;
      case 'key':{const input=document.getElementById('keyboard-input');if(input){if(value==='←')input.value=input.value.slice(0,-1);else input.value+=value==='Space'?' ':value==='Enter'?'\n':value.length===1?value:'';}break;}
      case 'touchpad':dialog('mode_touch_touchpad',`<div class="touchpad" data-touchpad>${icon('touch_app')}</div><div class="row">${button('Left click','local-option')}${button('Right click','local-option')}</div>`,button('common_done','close'),true);break;
      case 'sign-in':signIn(value||state.store);break;
      case 'signin-tab':if(value==='qr'){document.getElementById('sign-in-body').innerHTML=`<div class="preview-monitor"><span class="icon" style="font-size:150px">qr_code_2</span></div><p class="lede">${esc(t('stores_signin'))}</p>`;}else{closeLayer();signIn(state.signInStore);}break;
      case 'finish-signin':state.signedIn[value||state.store]=document.getElementById('sign-name')?.value||'Player';closeLayer();render();toast('common_done');break;
      case 'sign-out':delete state.signedIn[state.store];toast('stores_signout_go');break;
      case 'downloads':dialog('stores_tab_downloads',downloadList(),button('common_close','close'),true);break;
      case 'install-game':install(value||state.selected?.id,el);break;
      case 'pause-download':{const d=state.downloads.find(d=>String(d.id)===value);if(d)d.paused=!d.paused;closeLayer();dialog('stores_tab_downloads',downloadList(),button('common_close','close'),true);break;}
      case 'cancel-download':state.downloads=state.downloads.filter(d=>String(d.id)!==value);closeLayer();dialog('stores_tab_downloads',downloadList(),button('common_close','close'),true);break;
      case 'remove-game':confirm('common_remove','flathub_remove_note','finish-remove',value);break;
      case 'finish-remove':{const g=state.games.find(g=>String(g.id)===value);if(g)g.installed=false;closeLayer();render();break;}
      case 'game-more':options('game_more',[['game-resources','game_resources_title'],['environment','game_env_title'],['win-components','win_components_title']],'route',el);break;
      case 'emulator':{const e=emulators.find(e=>e[0]===value);dialog(e?.[1]||value,`<div class="row"><img src="assets/emu_${value}.png" alt="" width="75"><div><h2>${esc(e?.[1])}</h2><p class="lede">${esc(e?.[2])}</p></div></div><div class="actions">${button('games_play','launch',value,'primary','play_arrow')}${button('setup_tool_roms','roms')}${button('game_settings_card','mode-sheet','game')}</div>`,button('common_close','close'));break;}
      case 'flathub':flathub();break;
      case 'flathub-tab':state.storeTab=value;closeLayer();flathub();break;
      case 'flathub-app':dialog(value,`<div class="preview-monitor">${icon('apps')}</div><div class="facts"><span class="fact"><b>ARM64</b><span>${esc(t('store_app_id'))}</span></span><span class="fact"><b>Flatpak</b><span>${esc(t('store_runtime'))}</span></span></div>`,button('common_close','close')+button('store_install','download-component',value,'primary'));break;
      case 'boot-preview':dialog('boot_movie',`<video class="boot-video" src="assets/droiddeck-startup.webm" autoplay muted playsinline controls></video>`,button('common_close','close'),true);break;
      case 'boot-tab':{const host=document.getElementById('boot-content');document.querySelectorAll('[data-act="boot-tab"]').forEach(t=>t.classList.toggle('active',t.dataset.value===value));if(value==='import')host.innerHTML=`<div class="actions">${button('boot_movie_import','file-import','','primary','upload')}</div>`;else if(value==='sound')host.innerHTML=`<div class="panel">${setting({kind:'range',key:'boot_movie_volume',min:0,max:100,value:70})}${setting({kind:'toggle',key:'boot_movie_sound',on:true})}</div>`;else host.innerHTML=`<div class="preview-monitor"><img src="assets/logo.png" alt="DroidDeck"></div><div class="actions">${button('boot_movie_repo_preview','boot-preview','','primary')}${button('boot_movie_repo_use','use-boot')}</div>`;break;}
      case 'calibrate':{const body=el.closest('.dialog').querySelector('.dialog-body');body.innerHTML=`<canvas class="throbber" style="margin:20px auto;display:block"></canvas><p>${esc(t('glasses_calibration_collecting'))}</p><div class="progress-track indeterminate"><div class="progress-fill"></div></div>`;M.logo(body.querySelector('canvas'));setTimeout(()=>{if(body.isConnected)body.innerHTML=`<div class="readiness">${icon('check_circle')}<p>${esc(t('glasses_calibration_complete'))}</p></div>`;},2200);break;}
      case 'pair-next':closeLayer();pairing(Math.min(3,Number(value)));break;
      case 'add-env':dialog('game_env_add','<div class="sign-in-fields"><input class="search-field" id="env-key" placeholder="NAME"><input class="search-field" id="env-value" placeholder="VALUE"></div>',button('common_cancel','close')+button('common_save','save-env','','primary'));break;
      case 'save-env':{const key=document.getElementById('env-key').value.trim(),v=document.getElementById('env-value').value;if(/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)){state.environment??={};state.environment[key]=v;saveOptions();closeLayer();closeLayer();environment();}else toast('game_env_invalid');break;}
      case 'remove-env':delete state.environment[value];saveOptions();closeLayer();environment();break;
      case 'dashboard-tab':{document.querySelectorAll('[data-act="dashboard-tab"]').forEach(t=>t.classList.toggle('active',t.dataset.value===value));const host=document.getElementById('dashboard-content');if(value==='dashboard')host.innerHTML=controllerPreview();else if(value==='downloads')host.innerHTML=downloadList();else if(value==='chat')host.innerHTML=`<div class="touchpad">${icon('forum')}</div><input class="search-field" placeholder="${prefs.language==='zh'?'消息':'Message'}">`;else if(value==='telemetry')host.innerHTML='<div class="facts"><span class="fact"><b>60 FPS</b></span><span class="fact"><b>18% CPU</b></span><span class="fact"><b>2.4 GB RAM</b></span></div>';else host.innerHTML=`<div class="empty-state" style="min-height:200px">${icon(value==='screenshots'?'photo_library':'notifications')}<p>${esc(t('stores_nothing_matches'))}</p></div>`;wireController();break;}
      case 'checks':dialog('setup_system_check',`<div class="panel">${['setup_gpu_supported','setup_runtime','setup_limit','setup_account'].map(key=>`<div class="setting-row"><span>${esc(t(key))}</span><span class="good">${icon('check_circle')}</span></div>`).join('')}</div>`,button('common_done','close'));break;
      case 'stores-settings':dialog('stores_settings',`<div class="panel">${P.stores.map(s=>setting({kind:'toggle',key:s[1],on:true})).join('')}</div><div class="actions">${button('mode_storage','route','storage')}${button('setup_stores_speed','pick-speed')}${button('sync_title','route','sync')}</div>`,button('common_done','close'));break;
      case 'frontend-files':dialog('game_frontend_files',`<div class="panel">${setting({kind:'action',key:'game_file_export',event:'export-ui'})}${setting({kind:'action',key:'game_file_sync',event:'folder'})}${setting({kind:'action',key:'game_file_stop_sync',event:'local-option'})}</div>`,button('common_close','close'));break;
      case 'folder':case 'files':case 'file-import':case 'roms':case 'steam-import':dialog(act==='roms'?'setup_tool_roms':'setup_tool_files',`<div class="panel">${['Home','Games','Downloads','Documents'].map(name=>`<button class="choice" data-act="folder-open" data-value="${name}">${icon('folder')}${name}${icon('chevron_right')}</button>`).join('')}</div>`,button('common_cancel','close')+button('setup_choose','choose-folder','','primary'));break;
      case 'folder-open':el.closest('.dialog').querySelector('.dialog-body').innerHTML=`<p class="lede">${esc(value)}</p><div class="empty-state" style="min-height:140px">${icon('folder_open')}</div>`;break;
      case 'choose-folder':closeLayer();toast('common_done');break;
      case 'text-entry':dialog(value,`<input class="search-field" id="text-entry" aria-label="${esc(t(value))}" value="${esc(state.values[value]||'')}">`,button('common_cancel','close')+button('common_save','save-text',value,'primary'));break;
      case 'save-text':state.values[value]=document.getElementById('text-entry')?.value||'';saveOptions();closeLayer();toast('common_done');break;
      case 'check-updates':case 'check-components':case 'refresh-store':toast('common_checking');setTimeout(()=>toast('comp_nothing_new'),900);break;
      case 'local-app':dialog(value,`<div class="empty-state" style="min-height:180px">${icon('apps')}<h2>${esc(value)}</h2></div>`,button('common_close','close'));break;
      case 'logs':logs();break;
      case 'reset-settings':confirm('setup_reset_settings_title','setup_reset_settings_body','finish-reset');break;
      case 'finish-reset':prefs={...defaults};state.values={};while(state.layers.length)state.layers.pop().el.remove();document.getElementById('shell').inert=false;render();saveOptions();break;
      case 'download-component':case 'select-component':{const owned=dialog(value||'comp_get',`<canvas class="throbber" style="display:block;margin:20px auto"></canvas><div class="progress-track indeterminate"><div class="progress-fill"></div></div>`,button('common_cancel','close'));M.logo(owned.querySelector('canvas'));setTimeout(()=>{if(state.layers.at(-1)?.el===owned){closeLayer();toast('common_done');}},1800);break;}
      case 'about':dialog('DroidDeck',`${wordmark()}<p class="lede" style="margin-top:22px">DroidDeck 0.6.9 · mdeck</p><p>GPL-3.0</p>`,button('common_close','close'));break;
      case 'choose-color':prefs.primaryColor=value;prefs.theme='gradient';applyPrefs();closeLayer();break;
      case 'guide-next':state.guideStep=((state.guideStep||0)+1)%4;closeLayer();if(state.guideStep)route('onboarding');break;
      case 'chat-person':{document.getElementById('chat-name').textContent=value;document.querySelectorAll('[data-act="chat-person"]').forEach(b=>b.classList.toggle('selected',b.dataset.value===value));break;}
      case 'chat-send':{const input=document.getElementById('chat-message');if(input?.value.trim()){const bubble=document.createElement('div');bubble.className='chat-bubble own';bubble.textContent=input.value;document.getElementById('chat-messages').append(bubble);input.value='';}break;}
      case 'capture-open':{const game=state.games.find(g=>String(g.id)===value);if(game)dialog('Screenshots',`<img style="max-width:100%;max-height:65vh;object-fit:contain" src="${art(game)}" alt="${esc(game.name)}">`,button('common_close','close'),true);break;}
      case 'clean-preview':closeLayer();toast('common_done');break;
      case 'confirm-runtime-remove':confirm('common_uninstall','desktop_remove_text','close');break;
      case 'resource-preview':dialog(value,`<div class="empty-state" style="min-height:140px">${icon('language')}<h2>${esc(t(value))}</h2></div>`,button('common_close','close'));break;
      case 'release-notes':dialog('DroidDeck 0.6.9',`<div class="section-title">${esc(t('rail_games'))}</div><p class="lede">${esc(t('setup_launcher'))} · ${esc(t('rail_stores'))} · ${esc(t('setup_tab_glasses'))}</p>`,button('common_close','close'));break;
      default:if(P.routes[act])route(act);else {state.notifications.push(`${new Date().toLocaleTimeString()}  ${t(value||act)}`);toast('common_done');}
    }
  }
  document.addEventListener('click',event=>{const button=event.target.closest('[data-act]');if(button&&!button.disabled){const layer=button.closest('.layer');if(layer&&layer!==state.layers.at(-1)?.el)return;const before=button.closest('.chips')?.querySelector('.active')?.getBoundingClientRect();const action=button.dataset.act,value=button.dataset.value||'';knownAction(action,value,button);if(before)requestAnimationFrame(()=>{const after=Array.from(document.querySelectorAll('.chip.active')).find(e=>e.dataset.act===action&&e.dataset.value===value)?.getBoundingClientRect();if(after)M.chip(before,after);});}});
  document.addEventListener('input',event=>{
    const el=event.target;if(el.dataset.range){const value=Number(el.value);state.values[el.dataset.range]=value;el.parentElement.querySelector('output').textContent=value+(el.dataset.unit||'');if(el.dataset.range==='cardSize'){prefs.cardSize=value;root.style.setProperty('--card-width',`${value}px`);document.querySelectorAll('.game-grid').forEach(g=>g.style.setProperty('--card-width',`${value}px`));save();}if(el.dataset.range==='setup_app_scale'){prefs.scale=value;document.getElementById('pane').style.zoom=value/100;save();}if(el.dataset.range==='RGB speed')applyPrefs();saveOptions();}
    if(el.dataset.color){prefs[el.dataset.color==='primary'?'primaryColor':'secondaryColor']=el.value;prefs.theme='gradient';applyPrefs();}
    if(el.dataset.input==='search'){state.search=el.value;const query=el.value.trim().toLowerCase();document.querySelectorAll('.game-card').forEach(card=>card.hidden=!card.getAttribute('aria-label').toLowerCase().includes(query));}
    if(el.dataset.input==='store-search'){const query=el.value.toLowerCase();document.querySelectorAll('.game-card').forEach(card=>card.hidden=!card.getAttribute('aria-label').toLowerCase().includes(query));}
    if(el.dataset.input==='apps-search'){const query=el.value.toLowerCase();document.querySelectorAll('.app-icon').forEach(card=>card.hidden=!card.textContent.toLowerCase().includes(query));}
  });
  const visibleFocusables=()=>Array.from((state.layers.at(-1)?.el||document.getElementById('session-screen')||document.body).querySelectorAll('button:not(:disabled),input,textarea,select')).filter(e=>e.getClientRects().length&&!e.hidden);
  function moveFocus(dx,dy){
    const list=visibleFocusables(),current=document.activeElement;if(!list.includes(current)){list[0]?.focus();return;}
    const a=current.getBoundingClientRect(),ax=a.x+a.width/2,ay=a.y+a.height/2;
    const candidate=list.filter(e=>e!==current).map(e=>{const b=e.getBoundingClientRect(),x=b.x+b.width/2-ax,y=b.y+b.height/2-ay;return {e,x,y,score:Math.hypot(x,y)+Math.abs(dx?y:x)*2};}).filter(v=>dx?v.x*dx>1:v.y*dy>1).sort((a,b)=>a.score-b.score)[0];
    if(candidate){candidate.e.focus({preventScroll:true});candidate.e.scrollIntoView({block:'nearest',inline:'nearest',behavior:M.reduced()?'auto':'smooth'});}
  }
  function back(){if(state.layers.length)closeLayer();else if(state.session)drawer();else if(state.page==='detail')navigate(state.detailOrigin);else navigate('steam');}
  document.addEventListener('keydown',event=>{
    const input=event.target.matches('input,textarea,select');
    if(event.key==='Escape'){event.preventDefault();back();return;}
    if(input)return;const directions={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
    if(directions[event.key]){event.preventDefault();state.inputMode='keyboard';moveFocus(...directions[event.key]);}
    if(event.key==='Tab'){state.inputMode='keyboard';if(state.layers.length){const list=visibleFocusables(),index=list.indexOf(document.activeElement);if((event.shiftKey&&index===0)||(!event.shiftKey&&index===list.length-1)){event.preventDefault();list[event.shiftKey?list.length-1:0]?.focus();}}}
  });
  document.addEventListener('pointerdown',()=>{state.inputMode='touch';document.getElementById('focus-ring').style.opacity=0;});
  document.addEventListener('focusin',event=>{
    if(state.inputMode!=='keyboard')return;const b=event.target.getBoundingClientRect(),ring=document.getElementById('focus-ring');ring.style.opacity=1;M.spring(ring,{left:b.left-3,top:b.top-3,width:b.width+6,height:b.height+6},{damping:.72,stiffness:500});
  });
  let lastButtons=[],lastDirection=0,lastPoll=0;
  function gamepad(now){
    if(!document.hidden&&now-lastPoll>80){lastPoll=now;const pad=Array.from(navigator.getGamepads?.()||[]).find(Boolean);if(pad){const buttons=pad.buttons.map(b=>b.pressed),press=i=>buttons[i]&&!lastButtons[i];const dx=(buttons[15]?1:buttons[14]?-1:Math.abs(pad.axes[0])>.55?Math.sign(pad.axes[0]):0),dy=(buttons[13]?1:buttons[12]?-1:Math.abs(pad.axes[1])>.55?Math.sign(pad.axes[1]):0);if((dx||dy)&&now-lastDirection>180){state.inputMode='keyboard';moveFocus(dx,dy);lastDirection=now;}if(press(0))document.activeElement?.click();if(press(1))back();if(press(3))addMenu(document.activeElement);if(press(9)&&state.session)drawer();if(press(4)||press(5)){const direction=press(5)?1:-1,ids=P.navigation.map(n=>n[0]);navigate(ids[(ids.indexOf(state.page)+direction+ids.length)%ids.length]);}lastButtons=buttons;}}
    requestAnimationFrame(gamepad);
  }
  setInterval(()=>{
    if(document.hidden)return;
    state.downloads.forEach(d=>{if(!d.paused)d.progress=Math.min(100,d.progress+3);});
    document.querySelectorAll('[data-download]').forEach(card=>{const d=state.downloads.find(d=>String(d.id)===card.dataset.download);if(d){card.querySelector('.progress-fill').style.width=`${d.progress}%`;card.querySelector('.download-status').textContent=d.paused?t('stores_dl_paused'):`${Math.floor(d.progress)}%`;}});
    for(const d of state.downloads.filter(d=>d.progress>=100)){const g=state.games.find(g=>g.id===d.id);if(g)g.installed=true;state.notifications.push(`${g?.name} · ${t('common_done')}`);toast(`${g?.name} · ${t('common_done')}`);}
    state.downloads=state.downloads.filter(d=>d.progress<100);
  },300);
  addEventListener('resize',()=>{rail();document.getElementById('focus-ring').style.opacity=0;});
  applyPrefs();render();requestAnimationFrame(gamepad);
  return { state,prefs,render,navigate,route,closeLayer,t,knownAction,visibleFocusables };
})();
