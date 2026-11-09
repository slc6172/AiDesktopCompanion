// Panel contents: Enter / Shift+Enter / IME composing / auto-grow / image drop. run: PROJ=<p> ../run.sh s37.js
const wait = (ms) => new Promise(r => setTimeout(r, ms));
module.exports = async (win, shot, ev) => {
  await ev(`setPanelOpen(true)`); await wait(300);
  const key = (opts) => ev(`(() => { const e = new KeyboardEvent('keydown', Object.assign({key:'Enter', bubbles:true, cancelable:true}, ${JSON.stringify(opts)})); return document.getElementById('input').dispatchEvent(e); })()`);
  const count = () => ev(`document.querySelectorAll('#log .msg.me').length`);
  await ev(`document.getElementById('input').value = '第一行'`);
  let before = await count(); await key({}); await wait(200);
  console.log("Enter sends:", (await count()) === before + 1);
  await ev(`document.getElementById('input').value = '甲'`); before = await count(); const notPrevented = await key({shiftKey:true}); await wait(150);
  console.log("Shift+Enter leaves newline alone:", notPrevented === true, "| not sent:", (await count()) === before);
  before = await count(); await key({isComposing:true}); await wait(150); console.log("composing Enter not sent:", (await count()) === before);
  const h = async (n) => { await ev(`(()=>{const i=document.getElementById('input'); i.value=${JSON.stringify(Array.from({length:n},(_, k)=>'行'+k).join('\n'))}; i.dispatchEvent(new Event('input'));})()`); return ev(`({h:document.getElementById('input').offsetHeight, ov:getComputedStyle(document.getElementById('input')).overflowY})`); };
  const h1 = await h(1), h3 = await h(3), h5 = await h(5), h9 = await h(9);
  console.log("heights 1/3/5/9 lines:", h1.h, h3.h, h5.h, h9.h, "| overflow at 5:", h5.ov, "at 9:", h9.ov);
  const dropFile = (name, type, size, count=1) => ev(`(() => { const dt = new DataTransfer(); for (let i=0;i<${count};i++) dt.items.add(new File([new Uint8Array(${size})], ${JSON.stringify(name)}, {type: ${JSON.stringify(type)}})); const panel = document.getElementById('panel'); panel.dispatchEvent(new DragEvent('dragenter', {dataTransfer: dt, bubbles:true, cancelable:true})); const hintShown = !document.getElementById('dropHint').hidden; panel.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles:true, cancelable:true})); return hintShown; })()`);
  console.log("drag hint shown:", await dropFile("a.png", "image/png", 1000)); await wait(300);
  console.log("image attached by drop:", await ev(`!document.getElementById('attachPreview').hidden && pendingImage && pendingImage.mime`));
  await ev(`clearPendingImage()`); await dropFile("a.txt", "text/plain", 10); await wait(200);
  console.log("non-image rejected:", await ev(`document.getElementById('attachPreview').hidden`));
  await dropFile("big.png", "image/png", 16*1024*1024); await wait(200); console.log("oversize rejected:", await ev(`document.getElementById('attachPreview').hidden`));
  console.log("drop outside panel is default-prevented:", await ev(`(() => { const dt=new DataTransfer(); dt.items.add(new File([1],'x.png',{type:'image/png'})); const e=new DragEvent('drop',{dataTransfer:dt,bubbles:true,cancelable:true}); document.getElementById('stage').dispatchEvent(e); return e.defaultPrevented; })()`));
};
