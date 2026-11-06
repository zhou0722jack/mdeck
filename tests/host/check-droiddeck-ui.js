#!/usr/bin/env node
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'../..'),ui=path.join(root,'app/Madeira/DroidDeckUI');
class Element {
  constructor(){this.innerHTML='';this.style={setProperty(){}};this.classList={add(){},remove(){},toggle(){},contains(){return false;}};this.isConnected=true;this.dataset={};}
  remove(){this.isConnected=false;} append(){} before(){} focus(){} setAttribute(){} addEventListener(){}
  getBoundingClientRect(){return {x:0,y:0,left:0,top:0,right:800,bottom:600,width:800,height:600};}
  querySelector(){return new Element();} querySelectorAll(){return [];}
}
const ids=new Map();const document={documentElement:new Element(),body:new Element(),hidden:false,activeElement:null,
  getElementById(id){if(!ids.has(id))ids.set(id,new Element());return ids.get(id);},createElement(){return new Element();},
  querySelector(){return null;},querySelectorAll(){return [];},addEventListener(){}};
const context={document,console,localStorage:{getItem(){return null;},setItem(){}},navigator:{getGamepads(){return [];}},
  requestAnimationFrame(){return 0;},cancelAnimationFrame(){},setInterval(){return 0;},clearInterval(){},
  setTimeout(){return 0;},clearTimeout(){},addEventListener(){},matchMedia(){return {matches:false};},
  innerWidth:800,innerHeight:600,performance:{now(){return 0;}},fetch(){throw Error('UI must not request a backend');}};
context.getComputedStyle=()=>({offset:0});
context.window=context;vm.createContext(context);
for(const name of ['catalog','theme','motion','pages','details','panels','app']){
  const source=fs.readFileSync(path.join(ui,name+'.js'),'utf8');
  new vm.Script(source,{filename:name+'.js'}).runInContext(context);
  assert(!/\b(?:fetch|XMLHttpRequest|WebSocket|EventSource)\s*\(/.test(source),name+' backend call');
}
assert.equal(context.DD_CATALOG.commit,'0a07926ef3477c90db911d169904137cfc5e2505');
assert.equal(context.DD_PAGES.navigation.length,8);
for(const [a,b] of [['#000000','#001022'],['#8b5cf6','#22d3ee'],['#ff0000','#00ff00'],['#ffffff','#f9f9f9']]){
  const palette=context.DDTheme.palette(a,b),ink=palette[9];
  assert(context.DDTheme.contrast(ink,palette[7])>=4.5);
  assert(context.DDTheme.contrast(ink,palette[8])>=4.5);
}
for(const [route] of context.DD_PAGES.navigation){
  context.DD.navigate(route);
  assert(ids.get('pane').innerHTML.length>100,route);
  assert(!ids.get('pane').innerHTML.includes('undefined'),route+' has undefined display value');
}
for(const route of Object.keys(context.DD_PAGES.routes)){
  context.DD.route(route);
  assert(context.DD.state.layers.length>0,route);
  context.DD.closeLayer();
}
context.DD.navigate('games');
context.DD.prefs.sort='size';context.DD.render();
const sortedHtml=ids.get('pane').innerHTML;
assert(sortedHtml.indexOf('Cyberpunk 2077')<sortedHtml.indexOf('UNDERTALE'),'GB sizes sort before smaller MB sizes');
context.DD.knownAction('set-collection','favorites',new Element());
assert(ids.get('pane').innerHTML.includes('DOOM Eternal'));
assert(!ids.get('pane').innerHTML.includes('Stardew Valley'),'favorites actually filters the cards');
context.DD.knownAction('favorite','782330',new Element());
assert(!context.DD.state.games.find(g=>g.id===782330).favorite);
context.DD.knownAction('favorite','782330',new Element());
assert(context.DD.state.games.find(g=>g.id===782330).favorite);
context.DD.knownAction('finish-reset','',new Element());
assert.equal(ids.get('shell').inert,false,'reset releases modal input isolation');
for(const game of context.DD_PAGES.games)assert(fs.existsSync(path.join(ui,`assets/game-${game.id}.jpg`)),game.name);
const assets=JSON.parse(fs.readFileSync(path.join(root,'docs/droiddeck-assets.json'),'utf8')).assets;
for(const asset of assets){const data=fs.readFileSync(path.join(ui,'assets',asset.file));assert.equal(data.length,asset.bytes,asset.file);assert.equal(crypto.createHash('sha256').update(data).digest('hex'),asset.sha256,asset.file);}
const html=fs.readFileSync(path.join(ui,'index.html'),'utf8');
assert(html.includes("connect-src 'none'"));assert(html.includes("form-action 'none'"));
for(const asset of [...html.matchAll(/(?:src|href)="([^"]+)"/g)])assert(fs.existsSync(path.join(ui,asset[1])),asset[1]);
// This renderer is now a retained design reference, not the native app entry.
const app=fs.readFileSync(path.join(root,'app/Madeira/MadeiraApp.swift'),'utf8');
assert(!app.includes('DroidDeckShell()'));
const manifest=JSON.parse(fs.readFileSync(path.join(root,'docs/droiddeck-source-manifest.json'),'utf8'));
assert.equal(manifest.files.length,110);
console.log('PASS: all 8 main routes and '+Object.keys(context.DD_PAGES.routes).length+' secondary route renderers');
console.log('PASS: 110-source reference inventory and all bundled fixture assets');
console.log('PASS: reference renderer makes no backend calls and is not the native application entry');
console.log('PASS: reference page local-content policy');
console.log('PASS: gradient contrast, file-size sorting, favorites state and modal reset');
console.log('No Xcode, Swift compilation, APK/IPA build, or device execution was performed.');
