// アイコンを押したタブの装飾をON/OFFする
chrome.action.onClicked.addListener(tab => chrome.scripting.executeScript({
  target: { tabId: tab.id },
  func: () => document.documentElement.classList.toggle('切り抜きオフ'),
}));
