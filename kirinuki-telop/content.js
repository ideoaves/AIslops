const SMALL_MAX = 16;
const LARGE_MIN = 24;
const THEMES = ['解説', 'ゲーム', 'ホラー', 'ニュース', '料理', '熱血', 'バラエティ', 'レトロ', '高級'];
const COLOR_COUNT = 3;
const FONT_URL = 'https://fonts.googleapis.com/css2?family=M+PLUS+Rounded+1c:wght@800&family=RocknRoll+One&family=Yuji+Syuku&family=Zen+Kaku+Gothic+New:wght@900&family=Klee+One:wght@600&family=Hachi+Maru+Pop&family=Reggae+One&family=Mochiy+Pop+One&family=DotGothic16&family=Shippori+Mincho+B1:wght@800&display=swap';

const SKIP = 'script,style,noscript,textarea,input,select,option,code,pre,kbd,samp,svg,math,canvas,[contenteditable=""],[contenteditable="true"],.切り抜き';
const SENTENCE = /(?:[^。、！？!?,.]|[.,](?=\d))*(?:[。、！？!?]|[.,](?!\d))+\s*|(?:[^。、！？!?,.]|[.,](?=\d))+/g;
const KEYWORD = /(「[^」]{1,20}」|[\d０-９][\d０-９,.，．]*[%％万億千百円人年月日回個歳]*|[ァ-ヴー]{3,})/;
const themes = new WeakMap();
let lastTheme = '';
let colorIndex = 0;

// 段落要素ごとに、直前の段落と被らないテーマを割り当てる
function themeOf(block) {
  if (!themes.has(block)) {
    const others = THEMES.filter(t => t !== lastTheme);
    themes.set(block, lastTheme = others[Math.floor(Math.random() * others.length)]);
  }
  return themes.get(block);
}

// 文ごとにテーマ・大きさ・色番号を付けた枠に分け、小中では数字などを強調枠にして返す
function telop(text, px, theme) {
  const size = px >= LARGE_MIN ? '大' : px > SMALL_MAX ? '中' : '小';
  const frag = document.createDocumentFragment();
  for (const sentence of text.match(SENTENCE) ?? [text]) {
    colorIndex = colorIndex % COLOR_COUNT + 1;
    const box = Object.assign(document.createElement('span'), { className: `切り抜き ${theme} ${size} 色${colorIndex}` });
    frag.append(box);
    if (size === '大') { box.append(sentence); continue; }
    sentence.split(KEYWORD).forEach((part, i) => {
      if (part) box.append(i % 2 ? Object.assign(document.createElement('span'), { className: '強調', textContent: part }) : part);
    });
  }
  return frag;
}

// テキストノードを、親の文字サイズと所属する段落（一番近いブロック要素）と一緒に再帰的に集める
function collect(node, px, block, out) {
  if (node.nodeType === Node.TEXT_NODE) return node.nodeValue.trim() && out.push([node, px, block]);
  if (node.nodeType !== Node.ELEMENT_NODE || node.matches(SKIP)) return;
  const css = getComputedStyle(node);
  const own = css.display.startsWith('inline') ? block : node;
  node.childNodes.forEach(child => collect(child, parseFloat(css.fontSize), own, out));
}

// サイズを先に全部読んでから置き換える（読み書きを交互にすると再計算で重くなるため）
function decorate(root) {
  const list = [];
  const parent = root.parentElement ?? document.body;
  collect(root, parseFloat(getComputedStyle(parent).fontSize), parent, list);
  list.forEach(([node, px, block]) => node.replaceWith(telop(node.nodeValue, px, themeOf(block))));
}

document.head?.append(Object.assign(document.createElement('link'), { rel: 'stylesheet', href: FONT_URL }));
decorate(document.body);
new MutationObserver(records => records.forEach(r => r.addedNodes.forEach(n => n.parentElement?.closest(SKIP) || decorate(n))))
  .observe(document.body, { childList: true, subtree: true });
