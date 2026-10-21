"use strict";
/* Sora's shop - Blue Archive style shop UI (top bar, category tabs, item grid, filter, footer).
   Placeholder data only: every item, price and currency below is made up, and nothing is saved.
   Layout lives in shop_ui.css; this file builds the DOM, scales it to the window and handles the clicks. */
(function(){
const $=(s,r)=>(r||document).querySelector(s);
const fmt=n=>Number(n).toLocaleString("en-US");
const goBack=()=>{try{fetch("/__back",{method:"POST"})}catch(e){}};

// ------------------------------------------------------------------ icons (hand-drawn SVG stand-ins)
const HEX="50,4 92,27 92,73 50,96 8,73 8,27";
const DEFS=`<svg width="0" height="0" style="position:absolute"><defs>
 <linearGradient id="gHex" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#c58cf0"/><stop offset="1" stop-color="#7d46c4"/></linearGradient>
 <linearGradient id="gHexIn" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f3e4ff"/><stop offset="1" stop-color="#cfa8f2"/></linearGradient>
 <linearGradient id="gGold" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffe98a"/><stop offset="1" stop-color="#f1a722"/></linearGradient>
 <linearGradient id="gGreen" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#b6f06a"/><stop offset="1" stop-color="#3fae2f"/></linearGradient>
 <linearGradient id="gBlue" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#9be3ff"/><stop offset="1" stop-color="#2a8fe0"/></linearGradient>
 <linearGradient id="gSteel" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#d4e0f5"/><stop offset="1" stop-color="#6f86b8"/></linearGradient>
 <linearGradient id="gTeal" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#a6f3e8"/><stop offset="1" stop-color="#2fa99e"/></linearGradient>
 <linearGradient id="gLime" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#e3f58a"/><stop offset="1" stop-color="#8bb82c"/></linearGradient>
 <linearGradient id="gPink" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffb8e8"/><stop offset="1" stop-color="#b95fd8"/></linearGradient>
 <linearGradient id="gCard" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#cdd4ea"/></linearGradient>
<linearGradient id="gBag" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#d9e5fa"/></linearGradient>
 <linearGradient id="gBunny" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7fe9ff"/><stop offset="1" stop-color="#a98cff"/></linearGradient>
</defs></svg>`;
const S=(vb,body,cls)=>`<svg viewBox="${vb}" class="${cls||""}" xmlns="http://www.w3.org/2000/svg">${body}</svg>`;
const hex24=(g,st)=>`<polygon points="12,1.5 21.5,7 21.5,17 12,22.5 2.5,17 2.5,7" fill="url(#${g})" stroke="${st}" stroke-width="1.6" stroke-linejoin="round"/><polygon points="12,6 17.6,9.2 17.6,14.8 12,18 6.4,14.8 6.4,9.2" fill="#fff" opacity=".45"/>`;
const ICONS={
 energy:c=>S("0 0 24 24",`<path d="M14 1.5 4.5 13.5h6L8.8 22.5 19.5 9.6h-6.4z" fill="url(#gGreen)" stroke="#2c7d22" stroke-width="1.4" stroke-linejoin="round"/>`,c),
 credit:c=>S("0 0 24 24",`<rect x="1.5" y="5" width="21" height="14" rx="2.5" fill="url(#gGold)" stroke="#b9780f" stroke-width="1.5" transform="rotate(-12 12 12)"/><path d="M14.3 9.8a3.3 3.3 0 1 0 0 4.4" fill="none" stroke="#b9780f" stroke-width="1.8" stroke-linecap="round" transform="rotate(-12 12 12)"/>`,c),
 gem:c=>S("0 0 24 24",`<path d="M12 1.8 21 8l-3 13.2H6L3 8z" fill="url(#gBlue)" stroke="#1f6fb9" stroke-width="1.5" stroke-linejoin="round"/><path d="M3 8h18M12 1.8 9 8l3 13.2L15 8z" fill="none" stroke="#e8f8ff" stroke-width="1" opacity=".85"/>`,c),
 cert:c=>S("0 0 24 24",`<rect x="2" y="4.5" width="20" height="15" rx="2.5" fill="url(#gCard)" stroke="#6a5fb0" stroke-width="1.5"/><rect x="4.5" y="7.5" width="6" height="6" rx="1" fill="#8f62cc"/><path d="M13 8.5h6M13 11.5h6M5 16.5h14" stroke="#6a5fb0" stroke-width="1.3" stroke-linecap="round"/>`,c),
 kakera:c=>S("0 0 24 24",hex24("gPink","#7b3d9c"),c),
 raid:c=>S("0 0 24 24",`<path d="M3 8 12 3l9 5v9l-9 5-9-5z" fill="url(#gGold)" stroke="#a96d0c" stroke-width="1.5" stroke-linejoin="round"/><path d="M3 8l9 5 9-5M12 13v9" fill="none" stroke="#a96d0c" stroke-width="1.2"/>`,c),
 final:c=>S("0 0 24 24",hex24("gSteel","#44598a"),c),
 tact:c=>S("0 0 24 24",`<circle cx="12" cy="12" r="9.5" fill="url(#gTeal)" stroke="#1d7f76" stroke-width="1.6"/><circle cx="12" cy="12" r="4.5" fill="#fff" opacity=".5"/>`,c),
 fire:c=>S("0 0 24 24",`<circle cx="12" cy="12" r="9.5" fill="url(#gGreen)" stroke="#2c7d22" stroke-width="1.6"/><path d="M7 12h10M12 7v10" stroke="#fff" stroke-width="2" opacity=".7" stroke-linecap="round"/>`,c),
 wanted:c=>S("0 0 24 24",`<circle cx="12" cy="12" r="9.5" fill="url(#gLime)" stroke="#6b8a1e" stroke-width="1.6"/><circle cx="12" cy="12" r="5" fill="none" stroke="#fff" stroke-width="2" opacity=".7"/>`,c),
 plus:c=>S("0 0 24 24",`<path d="M12 2.5v19M2.5 12h19" stroke="#6dbdee" stroke-width="1.9" stroke-linecap="round"/>`,c),
 gear:c=>S("0 0 24 24",`<path fill="#42609a" stroke="#2c4579" stroke-width=".8" d="M10.3 1.5h3.4l.5 2.7 1.7.7 2.3-1.6 2.4 2.4-1.6 2.3.7 1.7 2.7.5v3.4l-2.7.5-.7 1.7 1.6 2.3-2.4 2.4-2.3-1.6-1.7.7-.5 2.7h-3.4l-.5-2.7-1.7-.7-2.3 1.6-2.4-2.4 1.6-2.3-.7-1.7-2.7-.5v-3.4l2.7-.5.7-1.7-1.6-2.3 2.4-2.4 2.3 1.6 1.7-.7z"/><circle cx="12" cy="12" r="3.6" fill="#e8f1ff"/>`,c),
 home:c=>S("0 0 24 24",`<path d="M12 2.5 1.5 12h3v9h5.5v-6h4v6h5.5v-9h3z" fill="#42609a" stroke="#2c4579" stroke-width=".8" stroke-linejoin="round"/>`,c),
 arrow:c=>S("0 0 24 24",`<path d="M20 12H5" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"/><path d="M11.5 5.5 5 12l6.5 6.5" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`,c),
 filter:c=>S("0 0 24 24",`<path d="M2.5 3.5h19l-7.2 9v7l-4.6 2v-9z" fill="#fff"/>`,c),
 clock:c=>S("0 0 24 24",`<circle cx="12" cy="13.5" r="9" fill="#1f78cf"/><rect x="9.2" y="1.5" width="5.6" height="3" rx="1.2" fill="#1f78cf"/><path d="M12 8.5v5.6l3.4 1.9" fill="none" stroke="#fff" stroke-width="2.3" stroke-linecap="round"/>`,c),
 info:c=>S("0 0 24 24",`<circle cx="12" cy="12" r="9.5" fill="none" stroke="#1c2b46" stroke-width="2"/><circle cx="12" cy="7.6" r="1.4" fill="#1c2b46"/><path d="M12 11v6.2" stroke="#1c2b46" stroke-width="2.3" stroke-linecap="round"/>`,c),
 gembuy:c=>S("0 0 64 64",`<g transform="rotate(8 32 34)"><path d="M21 15c0-9 22-9 22 0" fill="none" stroke="#a9c8f0" stroke-width="3.2" stroke-linecap="round"/><rect x="9" y="13" width="46" height="46" rx="6" fill="url(#gBag)" stroke="#fff" stroke-width="2.6"/><path d="M11 53h42v3.5a2.5 2.5 0 0 1-2.5 2.5h-37A2.5 2.5 0 0 1 11 56.5z" fill="#8fb4ee" opacity=".55"/><path d="M23 47c-3.5-7-1.2-13 3.4-15.2L25.2 21l5.6 8.6L32 29l1.2.6L38.8 21l-1.2 10.8C42.2 34 44.5 40 41 47c-3.2 4.8-14.8 4.8-18 0z" fill="url(#gBunny)"/></g>`,c),
};
// item art: a big faint hex behind a purple hex that holds a placeholder portrait
function itemArt(hue){
 const skin=`hsl(${(hue+30)%360} 55% 82%)`,hair=`hsl(${hue} 45% 28%)`,bg=`hsl(${hue} 60% 86%)`;
 return `<svg class="bg" viewBox="0 0 100 100" preserveAspectRatio="none"><rect x="3" y="3" width="94" height="94" rx="14" fill="#fff" opacity=".62"/><path d="M62 3 36 97" stroke="#fff" stroke-width="5" opacity=".8"/></svg>`+
 `<svg class="it" viewBox="0 0 100 110"><polygon points="${HEX}" fill="url(#gHex)" stroke="#5f2fa6" stroke-width="3" stroke-linejoin="round" transform="translate(0 5)"/>`+
 `<polygon points="${HEX}" fill="url(#gHexIn)" transform="translate(0 5) translate(50 50) scale(.84) translate(-50 -50)"/>`+
 `<circle cx="50" cy="55" r="29" fill="${bg}"/><ellipse cx="50" cy="86" rx="22" ry="15" fill="${hair}"/>`+
 `<circle cx="50" cy="52" r="15" fill="${skin}"/><path d="M34 52a16 16 0 0 1 32 0c-5-8-11-10-16-10s-11 2-16 10z" fill="${hair}"/></svg>`;
}

// ------------------------------------------------------------------ placeholder data
const STU=["ハスミ（水着）","セイア（水着）","コハル（水着）","ノゾミ","ヒカリ","ナギサ（水着）","アスナ（制服）","セイア","ミユ（水着）","サクラコ（アイドル）","マリー（アイドル）","ジュンコ（正月）",
 "アコ","アリス","アヤネ","アズサ","ホシノ","イロハ","キサキ","モモイ（メイド）","ニコ","セリカ","シロコ","ワカモ"];
const TABS=[
 {id:"kakera1",label:"カケラ(文字)",cur:"kakera",amount:3200,name:s=>`${s}のカケラ`,price:[600,600,900],qty:10,per:[3,3,5]},
 {id:"kakera2",label:"カケラ(その他)",cur:"kakera",amount:3200,name:(s,i)=>`汎用カケラ ${String.fromCharCode(65+i%26)}`,price:[300,450],qty:20,per:[10,10,5]},
 {id:"raid",label:"総力戦",cur:"raid",amount:52000,name:(s,i)=>`総力戦サンプル ${i+1}`,price:[1200,2400,3600],qty:3,per:[2,4,6]},
 {id:"final",label:"大決戦",cur:"final",amount:18000,name:(s,i)=>`大決戦サンプル ${i+1}`,price:[1000,1500],qty:3,per:[2,3]},
 {id:"tact",label:"戦術対抗戦",cur:"tact",amount:9800,name:(s,i)=>`対抗戦サンプル ${i+1}`,price:[500,800,1200],qty:5,per:[3,5]},
 {id:"fire",label:"合同火力演習",cur:"fire",amount:4500,name:(s,i)=>`演習サンプル ${i+1}`,price:[400,700],qty:5,per:[5,10]},
 {id:"wanted",label:"指名手配",cur:"wanted",amount:120,name:(s,i)=>`指名手配サンプル ${i+1}`,price:[20,40,60],qty:1,per:[3,5]},
 {id:"cert",label:"熟達証書",cur:"cert",amount:7080,name:s=>`${s}の神名文字`,price:[1800,1800,1800,1800,2400],qty:5,per:[2,2,2,6]},
];
const CERT_ICON={cert:"cert",kakera:"kakera",raid:"raid",final:"final",tact:"tact",fire:"fire",wanted:"wanted"};
const ap={now:125,max:240},wallet={credit:395678886,gem:57780};
let sel=TABS.length-1,filterOn=false,bar;

// 熟達証書 tab: the first twelve cards are copied from the reference screenshot ([name, price, purchases left]); the rest is filler
const CERT_SEED=[["ハスミ（水着）",1800,2],["セイア（水着）",1800,0],["コハル（水着）",1800,6],["ノゾミ",1800,2],
 ["ヒカリ",1800,2],["ナギサ（水着）",2400,2],["アスナ（制服）",1800,2],["セイア",1800,2],
 ["ミユ（水着）",1800,2],["サクラコ（アイドル）",1800,2],["マリー（アイドル）",1800,2],["ジュンコ（正月）",1800,2]];
const CERT_MORE=["アコ","アリス","アヤネ","アズサ","ホシノ","イロハ","キサキ","モモイ（メイド）","ニコ","セリカ","シロコ","ワカモ","ヒナ（ドレス）","ミカ","ナツ","ハルナ",
 "イズミ","ヨシミ","ユウカ","ノア","チナツ","ハナエ","マキ","アカリ","カヨコ","ムツキ","ハルカ","ネル","ツバキ","ミドリ","ユズ","アル","レイサ","ツムギ","フウカ","ヒフミ",
 "ウイ","コユキ","リオ","トキ","スミレ","ホタル","クルミ","サオリ","ミサキ","アツコ","ヒヨリ","カズサ","ハナコ","ユメ","チセ","シュン"];
TABS.forEach((t,ti)=>{                       // deterministic placeholder stock per tab
 t.items=[];
 if(t.id==="cert"){
  CERT_SEED.concat(CERT_MORE.map((n,i)=>[n,i%7===3?2400:1800,[2,2,6,2,1,2,4][i%7]])).forEach(([n,price,left],i)=>
   t.items.push({name:n+"の神名文字",price,qty:5,left,hue:(i*47+ti*61+260)%360}));
  return;
 }
 for(let i=0;i<16;i++){
  const stu=STU[(i+ti*5)%STU.length];
  t.items.push({name:t.name(stu,i),price:t.price[(i*7+ti)%t.price.length],qty:t.qty,left:t.per[(i*5+ti)%t.per.length],hue:(i*47+ti*61+260)%360});
 }
 if(t.items[1])t.items[1].left=0;
});

// ------------------------------------------------------------------ DOM
const stage=document.createElement("div");stage.id="stage";
stage.innerHTML=DEFS+`
<div id="topbar">
 <div id="title">ショップ</div><div id="help" class="hit" title="ヘルプ">?</div>
 <div id="wallet">
  <div class="cur">${ICONS.energy("ico")}<span class="v" id="apv" style="width:85px"></span>${ICONS.plus("plus hit")}</div>
  <div class="sep" style="margin:0 16px 0 17px"></div>
  <div class="cur credit">${ICONS.credit("ico")}<span class="v" id="crv" style="width:107px"></span></div>
  <div class="sep" style="margin:0 13px 0 32px"></div>
  <div class="cur">${ICONS.gem("ico")}<span class="v" id="gmv" style="width:87px"></span>${ICONS.plus("plus hit")}</div>
  <div class="sep" style="margin:0 19px 0 17px"></div>
  <div class="tb-btn hit" id="gear" title="設定">${ICONS.gear()}</div>
  <div class="sep" style="margin:0 14px 0 17px"></div>
  <div class="tb-btn hit" id="home" title="メインメニューへ">${ICONS.home()}</div>
 </div>
</div>
<button id="back" title="戻る" aria-label="Back to main menu">${ICONS.arrow()}</button>
<div id="tabs"></div>
<div id="gembuy" class="hit">${ICONS.gembuy()}<div>青輝石購入</div></div>
<div id="shop">
 <div id="chip"></div>
 <div id="filter" class="hit">${ICONS.filter()}<span>フィルター</span><b>OFF</b></div>
 <div id="panel"><div id="grid"></div><div id="bar"><i></i></div></div>
</div>
<div id="foot">
 <div class="tm">${ICONS.clock()}<span>初期化まで</span><em id="reset"></em></div>
 <div id="confirm" class="hit">${ICONS.info()}<span>熟達証書の確認</span></div>
</div>
<div id="toast"></div>`;
document.body.appendChild(stage);
const grid=$("#grid",stage),toastEl=$("#toast",stage);

function fit(){const s=innerHeight/745;stage.style.transform=`scale(${s})`;stage.style.width=(innerWidth/s)+"px"}
addEventListener("resize",fit);fit();

let tt=0;
function toast(msg){toastEl.textContent=msg;toastEl.classList.add("show");clearTimeout(tt);tt=setTimeout(()=>toastEl.classList.remove("show"),1600)}

function renderWallet(){
 $("#apv",stage).textContent=`${ap.now}/${ap.max}`;
 $("#crv",stage).textContent=fmt(wallet.credit);
 $("#gmv",stage).textContent=fmt(wallet.gem);
 const t=TABS[sel];
 $("#chip",stage).innerHTML=ICONS[CERT_ICON[t.cur]]()+`<span>${fmt(t.amount)}</span>`;
}
function renderTabs(){
 const el=$("#tabs",stage);el.innerHTML="";
 TABS.forEach((t,i)=>{
  const d=document.createElement("div");d.className="tab hit"+(i===sel?" on":"");
  d.innerHTML=ICONS[CERT_ICON[t.cur]]()+`<span>${t.label}</span>`;
  d.onclick=()=>{if(i===sel)return;sel=i;grid.scrollTop=0;renderTabs();renderWallet();renderGrid()};
  el.appendChild(d);
 });
}
function renderGrid(){
 const t=TABS[sel];grid.innerHTML="";
 t.items.forEach((it,i)=>{
  if(filterOn&&it.left<=0)return;
  const c=document.createElement("div");c.className="card"+(it.left<=0?" out":"");
  c.innerHTML=`<div class="nm${it.name.length>14?" sm":""}">${it.name}</div><div class="art">${itemArt(it.hue)}<div class="qty">x${it.qty}</div></div>`+
   `<div class="left">あと${it.left}回購入可能</div>`+
   `<div class="buy"><div class="price">${ICONS[CERT_ICON[t.cur]]()}<span>${fmt(it.price)}</span></div><div class="go">購入</div></div>`;
  $(".buy",c).onclick=()=>buy(t,it,c);
  grid.appendChild(c);
 });
 syncBar();
}
function buy(t,it,card){
 if(it.left<=0){toast("購入可能回数がありません");return}
 if(t.amount<it.price){card.classList.remove("shake");void card.offsetWidth;card.classList.add("shake");toast("所持数が足りません");return}
 t.amount-=it.price;it.left--;toast("購入しました（仮）");
 const y=grid.scrollTop;renderWallet();renderGrid();grid.scrollTop=y;syncBar();
}
function syncBar(){                           // thin scroll indicator on the panel's right edge
 const i=$("#bar i",stage),box=$("#bar",stage),h=grid.clientHeight,sh=grid.scrollHeight;
 if(sh<=h+1){box.style.display="none";return}
 box.style.display="block";
 const th=Math.max(30,box.clientHeight*h/sh);
 i.style.height=th+"px";i.style.top=(box.clientHeight-th)*(grid.scrollTop/(sh-h))+"px";
}
grid.addEventListener("scroll",syncBar);
grid.addEventListener("wheel",e=>e.stopPropagation(),{passive:true});

// ------------------------------------------------------------------ buttons
$("#back",stage).addEventListener("click",goBack);
$("#home",stage).addEventListener("click",goBack);
$("#gear",stage).addEventListener("click",()=>toast("設定（準備中）"));
$("#help",stage).addEventListener("click",()=>toast("ヘルプ（準備中）"));
$("#gembuy",stage).addEventListener("click",()=>toast("青輝石購入（準備中）"));
$("#confirm",stage).addEventListener("click",()=>toast("熟達証書の確認（準備中）"));
stage.querySelectorAll(".plus").forEach(p=>p.addEventListener("click",()=>toast("チャージ（準備中）")));
$("#filter",stage).addEventListener("click",()=>{
 filterOn=!filterOn;const f=$("#filter",stage);f.classList.toggle("on",filterOn);$("b",f).textContent=filterOn?"ON":"OFF";
 grid.scrollTop=0;renderGrid();
});
stage.addEventListener("pointerdown",e=>e.stopPropagation());
addEventListener("keydown",e=>{if(e.key==="Escape")goBack()});

// ------------------------------------------------------------------ reset timer (placeholder: 27 days 16 hours from opening)
const end=Date.now()+(27*24+16)*3600e3;
function tick(){const ms=Math.max(0,end-Date.now()),d=Math.floor(ms/864e5),h=Math.floor(ms%864e5/36e5);$("#reset",stage).textContent=`${d}日${h}時間`}
tick();setInterval(tick,30000);

renderTabs();renderWallet();renderGrid();
requestAnimationFrame(syncBar);
})();
