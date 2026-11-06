/* Detailed presentation-only panels corresponding to the Android dialogs. */
'use strict';
window.DD_DETAILS = (route,api) => {
  const {t,esc,icon,button,setting,fromSource,state}=api;
  const row=(key,options)=>setting({kind:'choice',key,options});
  const toggle=(key,on=false,detail)=>setting({kind:'toggle',key,on,detail});
  const slider=(key,min,max,value,unit='')=>setting({kind:'range',key,min,max,value,unit});
  const group=(label,body)=>`<div class="eyebrow">${esc(t(label))}</div><div class="panel">${body}</div>`;
  const link=(label,route)=>setting({kind:'link',key:label,route});
  const result=(title,body,footer=button('common_done','close'))=>({title,body,footer,wide:true});
  if(route==='framegen'){
    return result('frame_gen_title',group('frame_gen_title',row('frame_gen_title',['common_off','DDFG 2×','DDFG 3×','DDFG 4×','LSFG 2×','LSFG 3×','LSFG 4×','LSFG 60 FPS','LSFG 90 FPS','LSFG 120 FPS']))+
      `<div class="actions">${button('lsfg_import','file-import')}</div>`);
  }
  if(route==='gestures'){
    const actions=['gesture_left_click','gesture_right_click','gesture_middle_click','gesture_keyboard','gesture_left_drag','gesture_right_drag','gesture_middle_pan','gesture_scroll','gesture_arrows','WASD','gesture_key_enter','gesture_key_escape'];
    return result('gesture_settings',
      group('gesture_tab_one',row('gesture_tap',actions)+row('gesture_drag',actions)+row('gesture_long_press',actions)+row('gesture_double_tap',actions))+
      group('gesture_tab_two',row('gesture_two_tap',actions)+row('gesture_two_drag',actions)+row('gesture_two_hold',actions)+toggle('gesture_pinch',true))+
      group('gesture_tab_three',row('gesture_three_tap',actions)+row('gesture_three_drag',actions)+row('gesture_three_hold',actions))+
      group('gesture_tab_options',row('gesture_movement',['gesture_direct','gesture_relative'])+slider('gesture_hold_delay',100,1000,350,' ms')+slider('gesture_double_delay',100,500,250,' ms')+toggle('gesture_feedback',true)+toggle('gesture_debug')),
      button('gesture_reset','reset-gestures')+button('gesture_save_changes','close','', 'primary'));
  }
  if(route==='shortcuts'){
    return result('shortcuts_title',fromSource('PhysicalShortcutsDialog')+group('shortcuts_title',[
      'shortcuts_dd_menu','drawer_steam_menu','drawer_quick_access','drawer_keyboard','drawer_hud', 'Screenshot','Volume up','Volume down'
    ].map(label=>row(label,['Unassigned','Select + Start','L1 + R1','L2 + R2','Home','F1','F12'])).join('')));
  }
  if(route==='screen-keys'){
    return result('screen_keys',`<div class="actions">${button('screen_keys_add','route','screen-key-editor','primary','add')}</div>`+
      group('screen_keys', ['Escape','Enter','Tab','Space','F1','F5','F12','Ctrl','Alt','Shift'].map(k=>`<button class="choice" data-act="route" data-value="screen-key-editor">${icon('keyboard')}<span>${k}</span>${icon('edit')}</button>`).join('')));
  }
  if(route==='screen-key-editor'){
    return result('screen_keys_add',group('screen_keys',row('Key',['Escape','Enter','Tab','Space','F1','F5','F12','Ctrl','Alt','Shift','A','B','C'])+slider('ctrl_opacity',10,100,70,'%')+slider('ctrl_size',50,200,100,'%')+toggle('gesture_hold_button'))+
      '<div class="controller-preview"><button class="pad-part" style="left:45%;top:40%">Esc</button></div>',button('common_cancel','close')+button('common_save','close','','primary'));
  }
  if(route==='win-components'){
    return result('wincomp_title',group('comp_profile',row('comp_profile',['comp_scope_general',...state.games.map(g=>g.name)]))+
      group('wincomp_title',['Visual C++ 2015–2022','Visual C++ 2013','Visual C++ 2010','.NET Framework 4.8','DirectX June 2010','XNA 4.0','PhysX','Core Fonts','Media Foundation','OpenAL'].map(key=>toggle(key)).join('')),
      button('common_restore','restore-components')+button('store_install','download-component','','primary'));
  }
  if(route==='game-resources'){
    return result('game_resources_title',group('game_resources_title',[
      ['ProtonDB','game_resource_protondb_detail'],['PCGamingWiki',''],['Steam Community',''],['game_resource_guides',''],['game_resource_steam_cloud','game_resource_steam_cloud_detail'],['game_resource_search','']
    ].map(([key,detail])=>setting({kind:'action',key,detail,event:'resource-preview'})).join('')));
  }
  if(route==='spatial'){
    return result('glasses_spatial_setup',group('glasses_hands_group',toggle('glasses_hands')+toggle('glasses_steady_hand_aim',true)+link('glasses_calibration','calibration'))+
      `<div class="preview-monitor">${icon('view_in_ar')}<div class="monitor-label">Luma Ultra</div></div>`+
      group('glasses_tracking_status',toggle('glasses_head_tracking')+slider('glasses_eye_height',80,220,165,' cm')+setting({kind:'action',key:'glasses_floor_set',event:'recenter'})));
  }
  if(route==='vr-controllers'){
    return result('glasses_joycons',group('glasses_joycons',toggle('ctrl_joycon_vr')+row('Controllers',['Joy-Con','Gamepad','Hand tracking'])+toggle('glasses_hands')+setting({kind:'action',key:'glasses_recenter_joycons_button',event:'recenter'}))+fromSource('GlassesPanel'));
  }
  if(route==='xbox-cloud'){
    return result('Xbox Cloud Gaming',group('mode_display',row('mode_resolution',['720p','1080p'])+row('Frame rate',['30 FPS','60 FPS'])+toggle('setup_fullscreen',true))+group('mode_touch_controls',toggle('mode_touch',true)+row('mode_controller',['Xbox 360','DualSense','Touch'])));
  }
  if(route==='itch-builds'||route==='gamejolt-builds'){
    return result(route==='itch-builds'?'itch.io':'Game Jolt',group('stores_install_title',[
      ['Windows','1.0.0 · 1.2 GB'],['Linux','1.0.0 · 890 MB'],['macOS','1.0.0 · 1.1 GB']
    ].map(([key,value])=>setting({kind:'action',key,value,event:'download-component'})).join('')));
  }
  if(route==='sync'||route==='sync-advanced'){
    return result('game_file_sync',group('game_file_sync',setting({kind:'action',key:'game_file_folder',event:'folder'})+toggle('game_file_sync')));
  }
  if(route==='color-picker'){
    return result('Color',`<div class="themes">${['#1a9fff','#22d3ee','#8b5cf6','#4cd37f','#ffb547','#ff8a80'].map(color=>`<button class="theme-tile" data-act="choose-color" data-value="${color}" style="height:70px;background:${color}"></button>`).join('')}</div><input type="color" data-color="primary" class="color-input" value="#1a9fff">`);
  }
  return null;
};
