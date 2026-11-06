/* DroidDeck 0.6.9 presentation mapping; no store, runtime or device services. */
'use strict';
window.DD_PAGES = (() => {
  const toggle=(key,detail=null,on=false)=>({kind:'toggle',key,detail,on});
  const range=(key,min,max,value,unit='%',detail=null)=>({kind:'range',key,min,max,value,unit,detail});
  const pick=(key,options,value=0,detail=null)=>({kind:'choice',key,options,value,detail});
  const link=(key,route,detail=null)=>({kind:'link',key,route,detail});
  const action=(key,event,detail=null)=>({kind:'action',key,event,detail});
  const text=(key,value,detail=null)=>({kind:'text',key,value,detail});
  const group=(key,rows)=>({key,rows});
  const schemas={
    display:[group('mode_display',[
      pick('mode_resolution',['mode_res_720','mode_res_900','mode_res_1080','mode_res_native','mode_res_custom'],2,'mode_res_note'),
      pick('mode_ratio',['16:9','16:10','4:3','21:9','common_auto'],0,'mode_ratio_auto'),
      toggle('mode_stretch169'),toggle('mode_hdr10','mode_hdr_restart'),
      pick('setup_session_orientation',['setup_orientation_auto','setup_orientation_landscape','setup_orientation_reverse','setup_orientation_portrait']),
      link('mode_gpu_drivers','drivers','mode_gpu_drivers_hint'),link('drawer_page_effects','effects')
    ])],
    controls:[group('mode_touch_controls',[
      pick('mode_touch',['common_auto','mode_touch_touchpad','mode_touch_direct'],0,'mode_touch_note'),
      pick('mode_osc',['common_auto','common_on','common_off','mode_osc_qam'],0,'mode_osc_note'),
      pick('mode_controller',['mode_controller_deck','mode_controller_steam','mode_controller_dualsense','mode_controller_ds4','mode_controller_x360']),
      link('ctrl_layout','controller-layout'),link('ctrl_mapping','controller-mapping'),link('mode_controller','controller'),
      link('gesture_title','gestures'),link('physical_shortcuts_title','shortcuts'),link('screen_keys_title','screen-keys')
    ])],
    audio:[group('mode_audio',[toggle('mode_directaudio','mode_directaudio_hint',true),toggle('mode_mic','mode_mic_hint'),range('glasses_volume',0,100,75),pick('mode_audio',['common_auto','DirectAudio','PulseAudio'])])],
    session:[group('mode_session',[
      pick('mode_suspend',['common_auto','mode_suspend_manual','mode_suspend_native']),
      toggle('mode_background_downloads','mode_background_downloads_hint',true),
      link('perf_title','performance'),link('framegen_title','framegen'),link('mode_mangoapp','hud'),
      toggle('mode_return_after_game',null,true),link('mode_decky','decky')
    ])],
    steam:[group('mode_startup',[toggle('mode_steam_startup','mode_steam_startup_hint'),pick('mode_client_arch',['mode_client_arch_arm64','mode_client_arch_x64'])]),
      group('setup_account',[toggle('setup_offline',null,false),action('stores_signin','sign-in'),action('stores_signout_go','sign-out')]),
      group('mode_client',[toggle('mode_wifi_discovery','mode_wifi_discovery_hint'),action('mode_steam_repair','repair'),link('boot_movie','boot-movies'),link('mode_decky','decky')])],
    library:[group('mode_storage',[
      pick('mode_storage',['mode_storage_auto_short','mode_storage_internal','mode_choose_folder']),
      action('mode_second_library','folder'),link('mode_storage_diagnostics','storage'),
      action('game_frontend_files','frontend-files'),action('steam_import_title','steam-import')
    ])],
    launcher:[group('setup_group_look',[
      link('setup_theme','themes','setup_theme_hint'),range('setup_app_scale',75,150,100,'%','setup_app_scale_hint'),
      pick('setup_launcher_icon',['setup_launcher_icon_dark','setup_launcher_icon_light']),
      toggle('setup_animations',null,true),toggle('setup_rail_labels','setup_rail_labels_hint',true),
      pick('setup_language',['setup_language_system_short','简体中文','English'],1,'setup_language_hint'),
      toggle('setup_stores',null,true)
    ]),group('setup_group_device',[
      toggle('setup_home','setup_home_on'),pick('setup_launcher_orientation',['setup_launcher_orientation_auto','setup_orientation_landscape','setup_orientation_portrait']),
      toggle('setup_fullscreen','setup_fullscreen_on',true),link('setup_dual_screen','dual-screen'),
      action('setup_default_home','choose-home'),link('boot_movie','boot-movies')
    ]),group('setup_group_art',[action('mode_sgdb_key','text-entry'),action('game_file_sync','folder'),action('setup_reset_settings','reset-settings')])],
    controller:[group('setup_controller',[
      range('ctrl_opacity',10,100,65),range('ctrl_size',50,175,100,'%', 'ctrl_size_hint'),
      toggle('ctrl_adaptive','ctrl_adaptive_hint',true),toggle('ctrl_stick_click','ctrl_stick_click_hint',true),toggle('ctrl_rumble',null,true),
      toggle('ctrl_steam_button',null,true),toggle('ctrl_qam_button',null,true),toggle('ctrl_keyboard_button',null,true),
      toggle('ctrl_select_steam','ctrl_select_steam_hint'),link('ctrl_layout','controller-layout'),link('ctrl_mapping','controller-mapping'),
      link('physical_shortcuts_title','shortcuts'),link('gesture_title','gestures'),action('ctrl_reset_all','reset-controller')
    ])],
    performance:[group('perf_client_cores_group',[toggle('perf_override'),pick('perf_client_cores',['common_auto','0, 1, 2, 3','4, 5, 6, 7','0–7'])]),
      group('perf_game_cores_group',[pick('perf_game_cores',['common_auto','0–7','4, 5, 6, 7']),pick('fex_preset_title',['fex_default_label','fex_stability_label','fex_compatibility_label','fex_intermediate_label','fex_performance_label','fex_performance_tso_label','fex_extreme_label','fex_denuvo_label'])]),
      group('perf_client_ui',[toggle('perf_glthread','perf_glthread_hint',true),toggle('perf_zink','perf_zink_hint',true),toggle('perf_noglerror','perf_noglerror_hint'),toggle('perf_gsrealtime')]),
      group('perf_memory',[pick('perf_ram_cap',['perf_cap_off','2048 MB','3072 MB','4096 MB','6144 MB']),pick('perf_vram_cap',['perf_cap_auto','512 MB','1024 MB','2048 MB']),toggle('perf_zram_client'),toggle('perf_gpuclock','perf_gpuclock_hint')]),
      group('perf_fixes',[toggle('perf_sysmem'),toggle('perf_xalia'),toggle('perf_seccomp','perf_seccomp_hint'),toggle('perf_fastpath','perf_fastpath_hint',true)]),
      group('perf_identity',[action('perf_hostname','text-entry','perf_hostname_hint'),link('game_env_title','environment')])],
    storage:[group('mode_storage',[action('mode_choose_folder','folder'),pick('mode_storage',['mode_storage_auto_short','mode_storage_internal']),action('mode_second_library','folder')]),
      group('setup_tools',[action('setup_tool_files','files'),action('setup_tool_roms','roms'),link('sync_title','sync')]),
      group('setup_logs',[action('setup_clear_logs','clear-logs'),action('common_remove','remove-dialog')])],
    diagnostics:[group('setup_session',[toggle('setup_game_debug_logs','setup_game_debug_logs_hint'),link('mode_mangoapp','hud'),link('setup_runtime','runtime'),link('setup_title','onboarding')]),
      group('setup_tools',[action('setup_latest_logs','logs'),action('setup_saved_logs','logs'),action('setup_agent_commands','logs'),action('setup_vac_diag','logs')]),
      group('setup_group_download',[pick('setup_download_source',['setup_download_source_auto','setup_download_source_direct','setup_download_source_mirror','setup_download_source_custom']),action('setup_download_prefix','text-entry'),action('setup_download_proxy','text-entry')])],
    glasses:[group('glasses_display',[toggle('glasses_game_on'),pick('glasses_display_mode',['glasses_output_2d','glasses_output_3d']),pick('glasses_resolution_2d',['glasses_resolution_auto','1920×1080','3840×1080']),pick('glasses_refresh',['60 Hz','90 Hz','120 Hz']),range('glasses_brightness',0,100,75),range('glasses_volume',0,100,65)]),
      group('glasses_picture_group',[pick('glasses_picture',['glasses_picture_auto','glasses_picture_screen','glasses_picture_sbs']),range('glasses_screen_size',50,200,120),range('glasses_screen_distance',1,6,3,' m')]),
      group('glasses_tracking',[toggle('glasses_head_tracking','glasses_head_tracking_hint'),toggle('glasses_6dof'),action('glasses_recenter_button','recenter'),link('glasses_calibration','calibration'),link('glasses_spatial_setup','spatial')]),
      group('glasses_hands_group',[toggle('glasses_hands'),toggle('glasses_steady_hand_aim','glasses_steady_hand_aim_hint'),link('glasses_joycons','vr-controllers')])],
    effects:[group('drawer_page_effects',[toggle('mode_hdr'),range('Brightness',0,200,100),range('Contrast',0,200,100),range('Saturation',0,200,100),range('Sharpness',0,100,20),pick('Scaling filter',['Linear','Nearest','FSR','NIS']),action('common_reset','reset-effects')])],
    'dual-screen':[group('setup_dual_screen',[pick('setup_dual_screen',['setup_dual_screen_auto','setup_dual_screen_on','setup_dual_screen_off']),toggle('setup_dual_screen_controls','setup_dual_screen_controls_hint'),link('setup_dual_screen_menu','bottom-dashboard'),link('screen_layout_title','screen-layout')])],
    'drivers':[group('comp_runtime_driver',[pick('comp_runtime_driver',['Mesa Turnip 25.1.0','Mesa Turnip 26.0.0','System']),action('comp_import_turnip','file-import')]),group('comp_display_driver',[pick('comp_display_driver',['System','AdrenoTools']),action('comp_import_adrenotools','file-import')])],
    'decky':[group('mode_decky',[toggle('mode_decky',null,false),action('mode_decky_install_latest','download-component'),text('mode_decky_loader','3.1.10')]),group('mode_decky_plugins',[action('mode_decky_plugin_install_zip','file-import')])]
  };
  const routes={
    'runtime':['FrontEndSetup','setup_runtime'], 'onboarding':['FrontEndSetup','setup_title'],
    'storage-overview':['StoragePage','storage_internal'],'storage-cleanup':['StoragePage','storage_clean_up_title'],
    'storage-games':['StoragePage','storage_games'],'storage-data':['StoragePage','storage_game_data'],
    'storage-tools':['StoragePage','storage_tools'],'storage-components':['StoragePage','storage_components'],
    'storage-stores':['StoragePage','storage_stores'],'storage-desktop':['StoragePage','storage_desktop'],
    'storage-system':['StoragePage','storage_system'],'storage-app':['StoragePage','storage_app_data'],
    'install-options':['StoresInstallDialog','stores_install_title'],
    'framegen':['FrameGenMenu','framegen_title'], 'hud':['DroidDeckHudSettings','mode_mangoapp'],
    'sync':['SyncPanel','sync_title'], 'sync-advanced':['SyncAdvancedPage','sync_advanced'],
    'gestures':['TouchGestureDialog','gesture_title'], 'shortcuts':['PhysicalShortcutsDialog','physical_shortcuts_title'],
    'screen-keys':['ScreenKeyPicker','screen_keys_title'], 'screen-key-editor':['ScreenKeyEditor','screen_keys_title'],
    'screen-layout':['ScreenLayoutPanel','screen_layout_title'], 'calibration':['GlassesCalibrationControls','glasses_calibration'],
    'spatial':['GlassesSetupPanel','glasses_spatial_setup'], 'vr-controllers':['GlassesPanel','glasses_joycons'],
    'win-components':['WinComponentsEditor','win_components_title'], 'game-resources':['GameResources','game_resources_title'],
    'proton':['ComponentsPage','Proton'], 'dxvk':['ComponentsPage','DXVK'], 'vkd3d':['ComponentsPage','VKD3D-Proton'], 'fex':['ComponentsPage','FEX'],
    'gog-maintenance':['GogMaintenanceUi','GOG'], 'xbox-cloud':['XboxStoreDialogs','Xbox Cloud Gaming'],
    'boot-movies':['BootMovieSection','boot_movie'], 'bottom-dashboard':['BottomDashboard','setup_dual_screen'],
    'wireless-adb':['WirelessAdbFixPage','setup_adb_pair'], 'process-limit':['PhantomProcessGatePage','setup_limit'],
    'roms':['RomsDialog','setup_tool_roms'], 'gamejolt-builds':['GameJoltBuildPicker','Game Jolt'], 'itch-builds':['ItchBuildPicker','itch.io'],
    'notifications':['BottomNotificationsPage','Notifications'], 'chat':['BottomChatPage','Chat'],
    'screenshots':['BottomScreenshotsPage','Screenshots'], 'telemetry':['BottomTelemetryPage','Performance'],
    'gpu-drivers':['GpuDriversPanel','mode_gpu_drivers'], 'color-picker':['ColorPickerDialog','Color']
  };
  const navigation=[['steam','sports_esports','rail_steam'],['games','video_library','rail_games'],['stores','shopping_bag','rail_stores'],['desktop','desktop_windows','rail_desktop'],['components','layers','rail_components'],['android-apps','apps','rail_apps'],['setup','tune','rail_setup'],['updates','system_update','rail_updates']];
  const stores=[['steam','Steam','#1a9fff'],['gog','GOG','#a64ac9'],['epic','Epic Games','#b7bbc1'],['amazon','Amazon','#ffad32'],['xbox','Xbox','#83c83f'],['itch','itch.io','#fa5c5c'],['battlenet','Battle.net','#18b7f1'],['gamejolt','Game Jolt','#b1ee36']];
  const games=[
    {id:782330,name:'DOOM Eternal',store:'steam',size:'80.6 GB',installed:true},
    {id:1091500,name:'Cyberpunk 2077',store:'gog',size:'86.2 GB',installed:true},
    {id:1245620,name:'ELDEN RING',store:'steam',size:'58.5 GB',installed:true},
    {id:413150,name:'Stardew Valley',store:'gog',size:'734 MB',installed:true},
    {id:1145360,name:'Hades',store:'epic',size:'11.4 GB',installed:true},
    {id:548430,name:'Deep Rock Galactic',store:'steam',size:'3.6 GB',installed:true},
    {id:250900,name:'The Binding of Isaac: Rebirth',store:'steam',size:'1.3 GB',installed:false},
    {id:368260,name:"Marvel’s Midnight Suns",store:'epic',size:'61.2 GB',installed:false},
    {id:391540,name:'UNDERTALE',store:'gog',size:'189 MB',installed:true},
    {id:105600,name:'Terraria',store:'steam',size:'602 MB',installed:false},
    {id:620,name:'Portal 2',store:'steam',size:'12.2 GB',installed:true},
    {id:1240440,name:'Halo Infinite',store:'xbox',size:'67.5 GB',installed:false}
  ];
  return { schemas,routes,navigation,stores,games };
})();
