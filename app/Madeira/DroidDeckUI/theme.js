/* Port of DroidDeck ui/ThemeColors.kt (GPL-3.0), including contrast fitting. */
'use strict';
window.DDTheme=(()=>{
  const clamp=(v,a=0,b=1)=>Math.max(a,Math.min(b,v));
  const rgb=hex=>[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255);
  const hex=channels=>'#'+channels.map(v=>Math.round(clamp(v)*255).toString(16).padStart(2,'0')).join('');
  function hsv(color){const [r,g,b]=rgb(color),hi=Math.max(r,g,b),d=hi-Math.min(r,g,b);let h=d===0?0:hi===r?60*((g-b)/d%6):hi===g?60*((b-r)/d+2):60*((r-g)/d+4);return [(h+360)%360,hi===0?0:d/hi,hi];}
  function fromHsv(h,s,v){h=(h%360+360)%360;s=clamp(s);v=clamp(v);const c=v*s,x=c*(1-Math.abs(h/60%2-1)),m=v-c;
    const channels=h<60?[c,x,0]:h<120?[x,c,0]:h<180?[0,c,x]:h<240?[0,x,c]:h<300?[x,0,c]:[c,0,x];return hex(channels.map(c=>c+m));}
  function luminance(color){const c=rgb(color).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return c[0]*.2126+c[1]*.7152+c[2]*.0722;}
  function contrast(a,b){const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);}
  function readable(color){let [h,s,v]=hsv(color),out=color;
    while(v<1&&luminance(out)<.1){v=Math.min(1,v+.04);out=fromHsv(h,s,v);}
    while(s>0&&luminance(out)<.1){s=Math.max(0,s-.04);out=fromHsv(h,s,v);}return out;}
  function move(ink,color){let [h,s,v]=hsv(color);return ink==='#03111f'?v<1?fromHsv(h,s,Math.min(1,v+.04)):s>0?fromHsv(h,Math.max(0,s-.04),v):color:fromHsv(h,s,Math.max(0,v-.04));}
  const gradient=(a,b,p)=>hex(rgb(a).map((v,i)=>v+(rgb(b)[i]-v)*p));
  function fits(ink,a,b){return Array.from({length:33},(_,i)=>contrast(ink,gradient(a,b,i/32))).every(v=>v>=4.52);}
  function palette(a,b){a=readable(a);b=readable(b);const dark='#03111f',white='#ffffff';
    const ink=Math.min(contrast(dark,a),contrast(dark,b))>=Math.min(contrast(white,a),contrast(white,b))?dark:white;
    let tries=0;while(!fits(ink,a,b)&&tries++<120){const nextA=move(ink,a),nextB=move(ink,b);if(nextA===a&&nextB===b)break;a=nextA;b=nextB;}
    const [h,s]=hsv(a),tint=(sat,v)=>fromHsv(h,sat*clamp(s/.35),v);
    return [tint(.5,.045),tint(.45,.075),tint(.42,.115),tint(.4,.16),tint(.36,.22),tint(.05,.97),tint(.16,.68),a,b,ink];}
  return {hsv,fromHsv,luminance,contrast,palette};
})();
