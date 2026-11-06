/* Geometry and motion adapted from DroidDeck 0.6.9, GPL-3.0. */
'use strict';
window.DDMotion = (() => {
  const ease = 'cubic-bezier(.2,.8,.2,1)';
  const reduced = () => document.body.classList.contains('no-motion') || matchMedia('(prefers-reduced-motion: reduce)').matches;
  const active = new WeakMap();
  function spring(element, to, { damping = .7, stiffness = 400, set = null, from = {} } = {}) {
    if (!element) return;
    if (active.has(element)) cancelAnimationFrame(active.get(element).frame);
    const before = active.get(element)?.values || {};
    const values = {}, velocity = {};
    for (const key in to) {
      values[key] = from[key] ?? before[key] ?? (parseFloat(getComputedStyle(element)[key]) || 0);
      velocity[key] = 0;
    }
    if (reduced()) {
      Object.assign(values, to);
      if (set) set(values); else for (const key in values) element.style[key] = `${values[key]}px`;
      active.set(element, { values, frame: 0 }); return;
    }
    let last = performance.now();
    function tick(now) {
      const dt = Math.min((now - last) / 1000, .032); last = now;
      let settled = true;
      for (const key in to) {
        velocity[key] += (-stiffness * (values[key] - to[key]) - 2 * damping * Math.sqrt(stiffness) * velocity[key]) * dt;
        values[key] += velocity[key] * dt;
        if (Math.abs(values[key] - to[key]) > .12 || Math.abs(velocity[key]) > .12) settled = false;
      }
      if (set) set(values); else for (const key in values) element.style[key] = `${values[key]}px`;
      active.set(element, { values, frame: settled ? 0 : requestAnimationFrame(tick) });
    }
    active.set(element, { values, frame: requestAnimationFrame(tick) });
  }
  function animate(element, frames, duration, extra = {}) {
    if (!element?.animate) return null;
    return element.animate(frames, { duration: reduced() ? 0 : duration, easing: ease, fill: 'both', ...extra });
  }
  function pane(element, direction = 0) {
    animate(element, [{ opacity: 0, transform: direction ? `translateX(${direction * 45}px)` : 'translateY(18px)' }, { opacity: 1, transform: 'none' }], 420, { delay: reduced() ? 0 : 80 });
  }
  function chip(from,to) {
    if(reduced()||!from||!to)return;
    const el=document.createElement('div');
    Object.assign(el.style,{position:'fixed',zIndex:'100',pointerEvents:'none',border:'1px solid var(--primary)',background:'color-mix(in srgb,var(--primary) 12%,transparent)',borderRadius:'99px'});
    document.body.append(el);
    const v={left:from.left,right:from.right,top:from.top,bottom:from.bottom},speed={left:0,right:0,top:0,bottom:0};let begin,last;
    const forward=to.left>=from.left,lead=forward?'right':'left',trail=forward?'left':'right';
    function tick(now){begin??=now;last??=now;const dt=Math.min((now-last)/1000,.032);last=now;let stop=true;
      for(const key of ['left','right','top','bottom']){if(key===trail&&now-begin<40){stop=false;continue;}const stiffness=key===lead?700:360,damping=key===lead?.62:.78;speed[key]+=(-stiffness*(v[key]-to[key])-2*damping*Math.sqrt(stiffness)*speed[key])*dt;v[key]+=speed[key]*dt;if(Math.abs(v[key]-to[key])>.1||Math.abs(speed[key])>.1)stop=false;}
      Object.assign(el.style,{left:`${v.left}px`,top:`${v.top}px`,width:`${Math.max(0,v.right-v.left)}px`,height:`${Math.max(0,v.bottom-v.top)}px`});
      if(stop||now-begin>1200)el.remove();else requestAnimationFrame(tick);
    }requestAnimationFrame(tick);
  }
  async function launchFlood(origin,done){
    if(!origin||reduced()){done();return;}
    const b=origin.getBoundingClientRect(),el=document.createElement('div');
    Object.assign(el.style,{position:'fixed',zIndex:'110',pointerEvents:'none',background:'var(--primary)',borderRadius:'12px',left:`${b.left}px`,top:`${b.top}px`,width:`${b.width}px`,height:`${b.height}px`});
    document.body.append(el);const grow=animate(el,[{left:`${b.left}px`,top:`${b.top}px`,width:`${b.width}px`,height:`${b.height}px`,borderRadius:'12px'},{left:'0px',top:'0px',width:`${innerWidth}px`,height:`${innerHeight}px`,borderRadius:'0px'}],480);
    if(grow)await grow.finished.catch(()=>{});done();const fade=animate(el,[{opacity:1},{opacity:0}],260);if(fade)await fade.finished.catch(()=>{});el.remove();
  }
  async function flood(source, destination, draw) {
    if (!source || reduced()) { draw(); return; }
    const rect = source.getBoundingClientRect(), target = destination.getBoundingClientRect();
    const ghost = document.createElement('div'); ghost.className = 'flood';
    const img = source.querySelector('img'); if (img) ghost.append(img.cloneNode());
    Object.assign(ghost.style, { left: `${rect.left}px`, top: `${rect.top}px`, width: `${rect.width}px`, height: `${rect.height}px` });
    document.body.append(ghost);
    const effect = animate(ghost, [{ left: `${rect.left}px`, top: `${rect.top}px`, width: `${rect.width}px`, height: `${rect.height}px`, borderRadius:'12px' }, { left: `${target.left}px`, top: `${target.top}px`, width: `${target.width}px`, height: `${target.height}px`, borderRadius:'0px' }], 480);
    setTimeout(draw, 140);
    if (effect) await effect.finished.catch(() => {});
    const fade = animate(ghost, [{ opacity:1 }, { opacity:0 }], 140);
    if (fade) await fade.finished.catch(() => {});
    ghost.remove();
  }
  function flight(source, target) {
    if (!source || !target || reduced()) return;
    const a = source.getBoundingClientRect(), b = target.getBoundingClientRect();
    const dot = document.createElement('div'); dot.className = 'flight-dot';
    document.getElementById('flight-layer').append(dot);
    const start = { x:a.x+a.width/2,y:a.y+a.height/2 }, end = { x:b.x+b.width/2,y:b.y+b.height/2 };
    const control = { x:(start.x+end.x)/2,y:Math.min(start.y,end.y)-80 };
    let born;
    function tick(now) {
      born ??= now; const elapsed=now-born;
      if (elapsed>450) { dot.remove(); return; }
      if (elapsed<150) {
        const p=elapsed/150,w=a.width+(14-a.width)*Math.min(1,p*1.4),h=a.height+(14-a.height)*Math.max(0,(p-.25)/.75);
        Object.assign(dot.style,{left:`${start.x-w/2}px`,top:`${start.y-h/2}px`,width:`${w}px`,height:`${h}px`});
      } else {
        const p=(elapsed-150)/300,q=1-p,x=q*q*start.x+2*q*p*control.x+p*p*end.x,y=q*q*start.y+2*q*p*control.y+p*p*end.y;
        Object.assign(dot.style,{left:`${x-7}px`,top:`${y-7}px`,width:'14px',height:'14px',transform:`scaleX(${1+.5*Math.sin(Math.PI*p)}) scaleY(${1-.25*Math.sin(Math.PI*p)})`});
      }
      requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }
  function wireSheet(layer) {
    const handle=layer.querySelector('.handle'),sheet=layer.querySelector('.lift-sheet');
    if (!handle || !sheet) return;
    let y=null;
    handle.addEventListener('pointerdown',event=>{y=event.clientY;handle.setPointerCapture(event.pointerId);sheet.style.transition='none';});
    handle.addEventListener('pointermove',event=>{if(y!==null)sheet.style.transform=`translateY(${Math.max(0,event.clientY-y)}px)`;});
    handle.addEventListener('pointerup',event=>{const distance=Math.max(0,event.clientY-y);y=null;sheet.style.transition='none';if(distance>90)window.DD.closeLayer();else spring(sheet,{offset:0},{from:{offset:distance},damping:.7,stiffness:380,set:values=>sheet.style.transform=`translateY(${values.offset}px)`});});
    handle.addEventListener('pointercancel',()=>{y=null;sheet.style.transition='';sheet.style.transform='';});
  }
  function lift(layer){const sheet=layer.querySelector('.lift-sheet');if(!sheet)return;sheet.style.transition='none';spring(sheet,{offset:0},{from:{offset:sheet.offsetHeight||600},damping:.7,stiffness:380,set:values=>sheet.style.transform=`translateY(${values.offset}px)`});}
  function fold(layer){const sheet=layer.querySelector('.lift-sheet');if(!sheet||reduced())return 220;spring(sheet,{offset:sheet.offsetHeight||600},{damping:.75,stiffness:380,set:values=>sheet.style.transform=`translateY(${values.offset}px)`});return 520;}
  function logo(canvas, run = true) {
    const ctx=canvas.getContext('2d');let frame;
    const CX=63.98,CY=111.86,OUTER=111.86,INNER=71.81,LEFT=56.055,RIGHT=71.885;
    const angle=(x,y)=>Math.atan2(y-CY,x-CX),leftward=a=>a<0?a:a-2*Math.PI;
    const span=(a,b,n)=>Array.from({length:n},(_,i)=>a+(b-a)*i/(n-1));
    const rays=[...span(angle(LEFT,0),angle(-31.98,0),9).slice(0,-1),...span(angle(-31.98,0),leftward(angle(-31.98,223.72)),25).slice(0,-1),...span(leftward(angle(-31.98,223.72)),leftward(angle(LEFT,223.72)),9)];
    const at=(a,r)=>[CX+r*Math.cos(a),CY+r*Math.sin(a)];
    const square=rays.map(a=>{const c=Math.cos(a),s=Math.sin(a),hits=[];if(c<-.000000001)hits.push((-31.98-CX)/c);if(s<-.000000001)hits.push(-CY/s);if(s>.000000001)hits.push((223.72-CY)/s);const t=Math.min(...hits);return [CX+t*c,CY+t*s];});
    square[0]=[LEFT,0];square[square.length-1]=[LEFT,223.72];
    const arc=rays.map(a=>at(a,OUTER)),dy=Math.sqrt(OUTER**2-(LEFT-CX)**2);arc[0]=[LEFT,CY-dy];arc[arc.length-1]=[LEFT,CY+dy];
    const iy=Math.sqrt(INNER**2-(LEFT-CX)**2);
    const inner=span(Math.atan2(iy,LEFT-CX),Math.atan2(-iy,LEFT-CX)+2*Math.PI,rays.length).map(a=>at(a,INNER));
    const oy2=Math.sqrt(OUTER**2-(RIGHT-CX)**2),iy2=Math.sqrt(INNER**2-(RIGHT-CX)**2);
    const right=[...span(Math.atan2(-oy2,RIGHT-CX),Math.atan2(oy2,RIGHT-CX),40).map(a=>at(a,OUTER)),...span(Math.atan2(iy2,RIGHT-CX),Math.atan2(-iy2,RIGHT-CX),40).map(a=>at(a,INNER))];
    function curve(p,x1,y1,x2,y2){let lo=0,hi=1,u=p;const at=(v,a,b)=>3*(1-v)**2*v*a+3*(1-v)*v*v*b+v**3;for(let i=0;i<18;i++){if(at(u,x1,x2)<p)lo=u;else hi=u;u=(lo+hi)/2;}return at(u,y1,y2);}
    const settle=p=>curve(p,.5,0,.3,1),turnCurve=p=>curve(p,.65,0,.35,1);
    function draw(now) {
      if(!canvas.isConnected){cancelAnimationFrame(frame);return;}
      const scale=devicePixelRatio||1,w=canvas.clientWidth,h=canvas.clientHeight;
      if(canvas.width!==w*scale||canvas.height!==h*scale){canvas.width=w*scale;canvas.height=h*scale;}
      ctx.setTransform(scale,0,0,scale,0,0);ctx.clearRect(0,0,w,h);
      const p=run&&!reduced()?(now%1900)/1900:0;
      const bend=p<.1?0:p<.24?settle((p-.1)/.14):p<.76?1:p<.9?1-settle((p-.76)/.14):0;
      const turn=p<.16||p>.84?0:turnCurve((p-.16)/.68)*Math.PI*2;
      const ball=p<.12?1:p<.3?1-.2*settle((p-.12)/.18):p<.7?.8:p<.88?.8+.2*settle((p-.7)/.18):1;
      ctx.save();ctx.scale(w/239.92,h/223.72);ctx.translate(55.98,0);ctx.translate(CX,CY);ctx.rotate(turn);ctx.translate(-CX,-CY);
      ctx.fillStyle=getComputedStyle(document.documentElement).getPropertyValue('--ink');
      const left=square.map((point,i)=>[point[0]+(arc[i][0]-point[0])*bend,point[1]+(arc[i][1]-point[1])*bend]);
      for(const points of [[...left,...inner],right]){ctx.beginPath();points.forEach((v,i)=>i?ctx.lineTo(...v):ctx.moveTo(...v));ctx.closePath();ctx.fill();}
      ctx.restore();ctx.save();ctx.scale(w/239.92,h/223.72);ctx.translate(55.98,0);ctx.fillStyle=getComputedStyle(document.documentElement).getPropertyValue('--primary');ctx.beginPath();ctx.arc(CX,CY,55.98*ball,0,Math.PI*2);ctx.fill();ctx.restore();
      frame=requestAnimationFrame(draw);
    }
    frame=requestAnimationFrame(draw);
  }
  return { spring, animate, pane, flood, flight, chip, launchFlood, wireSheet, lift, fold, logo, reduced, ease };
})();
